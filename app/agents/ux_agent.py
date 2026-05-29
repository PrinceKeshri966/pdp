"""
app/agents/ux_agent.py

UXAgent — deterministic UX facts + Claude for CRO reasoning only.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.agents.claude_client import claude
from app.agents.context_router import format_context_for_llm
from app.core.page_type_router import is_pdp
from app.rulesets.base import filter_pdp_leakage, ruleset_prompt_block
from app.core.recommendation_meta import enrich_recommendation_list
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.agents.scoring_engine import apply_reliability_caps, blend_score, compute_deterministic_scores
from app.agents.ux_preprocessor import extract_ux_facts
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")

_SYSTEM_PROMPT = """
You are an e-commerce CRO expert (Baymard Institute standards).
PRECOMPUTED_UX_FACTS already list CTAs, trust badges, shipping/returns visibility, etc.
Do NOT re-detect those booleans.

Return ONLY valid JSON:
{
  "conversion_score": float (0-10),
  "friction_points": [string],
  "conversion_blockers": [string],
  "cta_analysis": {
    "text_quality": "weak|average|strong",
    "above_fold": boolean,
    "score": float (0-10)
  },
  "page_layout": {
    "above_fold_content": "poor|adequate|excellent",
    "visual_hierarchy": "poor|adequate|excellent",
    "score": float (0-10)
  },
  "storytelling": {
    "emotional_appeal": "none|weak|moderate|strong",
    "score": float (0-10)
  },
  "checkout_friction": {
    "cart_abandonment_risk": "low|medium|high",
    "score": float (0-10)
  },
  "recommendations": [string]
}
""".strip()


def merge_ux_report(
    facts: dict[str, Any],
    llm: dict[str, Any],
    *,
    page_type: str = "unknown",
    vision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pdp_page = is_pdp(page_type)
    ctas = facts.get("cta_candidates") or []
    trust_n = len(facts.get("trust_badges") or [])
    trust_score = min(10.0, 4.0 + trust_n * 0.8) if trust_n else 3.0

    vision = vision or {}
    vision_available = bool(vision.get("available"))
    cta_score = (llm.get("cta_analysis") or {}).get("score", 6.0)
    layout_score = (llm.get("page_layout") or {}).get("score", 6.0)
    mobile_score = 7.0 if facts.get("mobile_ux_hints") else 5.0

    if vision_available:
        cta_vis = float(vision.get("cta_visibility") or 0)
        if cta_vis > 0:
            cta_score = cta_score * 0.4 + cta_vis * 0.6
        trust_vis = float(vision.get("trust_signals_visible") or 0)
        if trust_vis > 0:
            trust_score = trust_score * 0.4 + trust_vis * 0.6
        hierarchy = float(vision.get("visual_hierarchy") or 0)
        if hierarchy > 0:
            layout_score = layout_score * 0.4 + hierarchy * 0.6
        hero_clarity = float(vision.get("above_fold_clarity") or 0)
        if hero_clarity > 0:
            layout_score = layout_score * 0.7 + hero_clarity * 0.3
        mobile_est = float(vision.get("mobile_readiness_estimate") or 0)
        if mobile_est > 0:
            mobile_score = mobile_score * 0.4 + mobile_est * 0.6

    return {
        "conversion_score": llm.get("conversion_score", 6.0),
        "vision_ux_score": vision.get("overall_ux_score") if vision_available else None,
        "cta_analysis": {
            "found": facts.get("cta_count", 0) > 0,
            "above_fold": bool(facts.get("above_fold_cta")) or llm.get("cta_analysis", {}).get("above_fold", False),
            "sticky_on_scroll": bool(facts.get("sticky_cta_detected")),
            "text_quality": (llm.get("cta_analysis") or {}).get("text_quality", "average"),
            "color_contrast": vision.get("color_contrast_risk", "adequate") if vision_available else "adequate",
            "multiple_ctas": facts.get("cta_count", 0) > 1,
            "score": round(cta_score, 1),
            "vision_verified": vision_available,
        },
        "product_imagery": {
            "multiple_angles": facts.get("images_count", 0) > 2,
            "zoom_capability": bool(facts.get("zoom_capability_detected")),
            "lifestyle_images": int(facts.get("lifestyle_image_count") or 0) > 0,
            "video_present": facts.get("has_video", False),
            "image_count_adequate": facts.get("images_count", 0) >= 3,
            "packshot_count": facts.get("packshot_count", 0),
            "lifestyle_count": facts.get("lifestyle_image_count", 0),
            "score": min(10.0, facts.get("images_count", 0) * 1.5) if facts.get("images_count") else 4.0,
        },
        "trust_signals": {
            "reviews_present": facts.get("reviews_visible", False),
            "rating_visible": facts.get("avg_rating_visible", False),
            "review_count_visible": facts.get("review_count_visible", False),
            "verified_purchase_badges": False,
            "security_badges": facts.get("security_badges", False),
            "payment_icons": bool(facts.get("payment_mentions")),
            "return_policy_visible": facts.get("return_policy_visible", False),
            "shipping_info_visible": facts.get("shipping_visible", False),
            "money_back_guarantee": facts.get("money_back_guarantee", False),
            "score": round(trust_score, 1),
        },
        "product_information": (
            {
                "size_guide_present": facts.get("has_size_guide", False),
                "material_composition": bool(facts.get("material_composition_detected")),
                "care_instructions": False,
                "fit_description": bool(facts.get("fit_description_detected")),
                "specifications_table": bool(facts.get("specifications_table_detected")),
                "score": 6.0 if facts.get("has_size_guide") else 4.0,
            }
            if pdp_page
            else {"applicable": False, "score": None, "note": "N/A for non-PDP page type"}
        ),
        "mobile_ux": {
            "score": round(mobile_score, 1),
            "issues": [] if facts.get("mobile_ux_hints") else ["No explicit mobile UX signals in content"],
            "vision_verified": vision_available,
        },
        "page_layout": {
            **(llm.get("page_layout") or {"above_fold_content": "adequate", "visual_hierarchy": "adequate", "whitespace_usage": "adequate", "score": 6.0}),
            "score": round(layout_score, 1),
            "vision_verified": vision_available,
        },
        "storytelling": llm.get("storytelling") or {"has_brand_story": False, "has_lifestyle_content": False, "emotional_appeal": "weak", "score": 5.0},
        "urgency_scarcity": {
            "stock_counter": any("left" in u.lower() for u in facts.get("urgency_snippets") or []),
            "limited_time_offer": bool(facts.get("urgency_snippets")),
            "social_proof_counter": facts.get("reviews_visible", False),
            "recently_viewed_count": False,
            "score": 6.0 if facts.get("urgency_snippets") else 3.0,
        },
        "checkout_friction": llm.get("checkout_friction") or {"guest_checkout_implied": False, "one_click_buy": False, "cart_abandonment_risk": "medium", "score": 5.0},
        "friction_points": llm.get("friction_points") or [],
        "conversion_blockers": llm.get("conversion_blockers") or [],
        "recommendations": llm.get("recommendations") or [],
        "page_type": page_type,
        "vision_analysis": vision if vision_available else None,
        "_precomputed_facts": {k: v for k, v in facts.items() if not k.startswith("_")},
    }


async def ux_agent(state: AgentState) -> AgentState:
    packages = state.get("agent_context_packages") or {}
    ux_ctx = packages.get("ux")
    if not ux_ctx:
        return {"errors": ["ux_agent: no agent_context_packages.ux"]}

    structured = state_dict(state, "json_structured_data")
    ux_facts = extract_ux_facts(
        page_contexts=state.get("page_contexts"),
        structured=structured,
        markdown=state.get("markdown_content") or "",
        scrape_html=state.get("scrape_html") or "",
    )

    page_info = state_dict(state, "page_type_info")
    page_type = page_info.get("page_type") or state_dict(state, "scrape_validation").get("page_type") or "unknown"
    page_note = ruleset_prompt_block(page_type) + "\n\n"

    logger.info("ux_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""{page_note}PRECOMPUTED_UX_FACTS:
{json.dumps({k: v for k, v in ux_facts.items() if k != '_deterministic'}, separators=(',', ':'))}

UX context package:
{format_context_for_llm(ux_ctx, max_chars=2500)}

Analyze conversion friction and CRO opportunities only."""

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=1536,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    llm_layer, parse_err = safe_json_parse_report(raw, "ux_agent")
    if parse_err:
        return {"errors": [parse_err]}

    visual = state_dict(state, "visual_ux_facts")
    if not visual.get("vision_analysis"):
        bc_visual = (state.get("browser_capture") or {}).get("visual_ux_facts") or {}
        if bc_visual.get("vision_analysis"):
            visual = {**visual, "vision_analysis": bc_visual["vision_analysis"]}
    visual_ok = bool(visual.get("capture_ok"))

    ux_report = merge_ux_report(ux_facts, llm_layer, page_type=page_type, vision=visual.get("vision_analysis"))
    for key in ("friction_points", "conversion_blockers", "recommendations"):
        filtered, flagged = filter_pdp_leakage(ux_report.get(key) or [], page_type)
        ux_report[key] = filtered
        if flagged:
            ux_report.setdefault("_leakage_filtered", []).extend(flagged)

    if visual_ok:
        vis_cta = bool(visual.get("cta_above_fold"))
        ux_report["cta_analysis"]["above_fold"] = vis_cta
        if visual.get("sticky_cta_detected") is not None:
            ux_report["cta_analysis"]["sticky_on_scroll"] = bool(visual.get("sticky_cta_detected"))
        if not vis_cta and ux_report["cta_analysis"].get("above_fold"):
            ux_report["cta_analysis"]["score"] = min(
                float(ux_report["cta_analysis"].get("score") or 6), 5.0
            )
        ux_report["trust_signals"]["security_badges"] = ux_report["trust_signals"].get(
            "security_badges"
        ) or visual.get("trust_badges_visible", False)
        if visual.get("mobile_layout_quality") == "poor":
            ux_report["mobile_ux"]["issues"] = (ux_report["mobile_ux"].get("issues") or []) + [
                "Mobile layout overflow detected (visual capture)"
            ]

    det = compute_deterministic_scores(
        ux_facts=ux_facts,
        scrape_validation=state_dict(state, "scrape_validation"),
        extraction_confidence=state_dict(state, "extraction_confidence"),
        page_type=page_type,
        visual_ux_facts=visual,
    )
    blended = blend_score(det["deterministic_scores"]["ux"], ux_report.get("conversion_score"))
    if not visual_ok:
        blended = min(blended, 6.5)
    ux_report["conversion_score"] = apply_reliability_caps(blended, dict(state))
    ux_report["recommendations_enriched"] = enrich_recommendation_list(
        ux_report.get("recommendations") or [],
        base_confidence=0.75 if visual_ok else 0.5,
        source="visual+llm" if visual_ok else "llm",
        page_type_validated=not ux_report.get("_leakage_filtered"),
        visual_verified=visual_ok,
    )

    logger.info("ux_agent.done", score=ux_report.get("conversion_score"), duration_ms=duration_ms)

    return {
        "ux_report": ux_report,
        "ux_preprocessor_facts": ux_facts,
        "agent_reports": [
            {
                "agent": "ux_agent",
                "model": _MODEL,
                "output": ux_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
