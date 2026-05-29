"""
PrioritizationAgent — template-first synthesis; LLM only for deep audits.
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.scoring_engine import apply_reliability_caps
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger
from app.templates.recommendation_templates import build_prioritized_from_facts

logger = get_logger(__name__)

_MODEL = get_model("seo")  # Haiku — fast synthesis


def _health_from_scores(seo: dict, aeo: dict, ux: dict, psych: dict, competitor: dict) -> dict[str, float]:
    comp_score = 6.0
    if competitor.get("live_compare", {}).get("rows"):
        wins = sum(1 for r in competitor["live_compare"]["rows"] if r.get("you_win"))
        comp_score = min(10.0, 5.0 + wins * 1.2)
    return {
        "seo": float(seo.get("overall_seo_score") or 5),
        "ai_visibility": float(aeo.get("ai_visibility_score") or 5),
        "ux_conversion": float(ux.get("conversion_score") or 5),
        "competitor_position": comp_score,
        "psychology": float(psych.get("overall_psychology_score") or 5),
    }


def _template_diagnosis(state: AgentState) -> dict:
    seo = state_dict(state, "seo_report")
    aeo = state_dict(state, "aeo_report")
    ux = state_dict(state, "ux_report")
    psych = state_dict(state, "psychology_report")
    competitor = state_dict(state, "competitor_report")
    page_type = state_dict(state, "page_type_info").get("page_type") or "unknown"

    breakdown = _health_from_scores(seo, aeo, ux, psych, competitor)
    overall = round(sum(breakdown.values()) / len(breakdown), 1)
    recs = build_prioritized_from_facts(
        seo_facts=state_dict(state, "seo_preprocessor_facts"),
        seo_report=seo,
        aeo_report=aeo,
        ux_facts=state_dict(state, "ux_preprocessor_facts"),
        visual=state_dict(state, "visual_ux_facts"),
        page_type=page_type,
    )
    quick = [r["action"] for r in recs if r.get("effort") == "low"][:4]
    long_term = [r["action"] for r in recs if r.get("effort") == "high"][:4]
    depth = state.get("audit_depth") or "standard"
    return {
        "overall_health_score": overall,
        "score_breakdown": breakdown,
        "prioritized_recommendations": recs,
        "quick_wins": quick or (seo.get("quick_wins") or [])[:4],
        "long_term_fixes": long_term,
        "executive_summary": (
            f"Audit ({depth}) for {page_type} page. "
            f"SEO {breakdown['seo']}/10, AI visibility {breakdown['ai_visibility']}/10, "
            f"UX {breakdown['ux_conversion']}/10. "
            f"{len(recs)} prioritized actions from deterministic templates and agent findings."
        ),
        "_synthesis": "template",
    }


_SYSTEM_PROMPT = """
You are a senior optimization strategist. Refine (not replace) the template action plan.
Return ONLY valid JSON with keys: executive_summary, prioritized_recommendations (max 6), quick_wins, long_term_fixes.
Keep scores unchanged — do not invent product facts.
""".strip()


async def prioritization_agent(state: AgentState) -> AgentState:
    seo = state_dict(state, "seo_report")
    aeo = state_dict(state, "aeo_report")
    ux = state_dict(state, "ux_report")

    if not any([seo, aeo, ux]):
        return {
            "errors": ["prioritization_agent: no analysis reports available"],
            "status": "failed",
        }

    t0 = time.monotonic()
    final_diagnosis = _template_diagnosis(state)
    audit_depth = state.get("audit_depth") or state_dict(state, "agent_plan").get("audit_depth", "standard")

    if audit_depth == "deep":
        logger.info("prioritization_agent.llm_refine", model=_MODEL)
        user_message = json.dumps(
            {
                "template_plan": final_diagnosis.get("prioritized_recommendations", [])[:6],
                "scores": final_diagnosis.get("score_breakdown"),
                "page_type": state_dict(state, "page_type_info").get("page_type"),
            },
            separators=(",", ":"),
        )
        try:
            response = await claude.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()
            llm_layer, parse_err = safe_json_parse_report(raw, "prioritization_agent")
            if not parse_err and llm_layer:
                if llm_layer.get("executive_summary"):
                    final_diagnosis["executive_summary"] = llm_layer["executive_summary"]
                if llm_layer.get("prioritized_recommendations"):
                    final_diagnosis["prioritized_recommendations"] = llm_layer["prioritized_recommendations"]
                if llm_layer.get("quick_wins"):
                    final_diagnosis["quick_wins"] = llm_layer["quick_wins"]
                if llm_layer.get("long_term_fixes"):
                    final_diagnosis["long_term_fixes"] = llm_layer["long_term_fixes"]
                final_diagnosis["_synthesis"] = "template+haiku"
        except Exception as exc:
            logger.warning("prioritization_agent.llm_skip", error=str(exc))

    vr = state_dict(state, "validation_report")
    det = state_dict(state, "deterministic_scores").get("deterministic_scores") or {}
    sb = final_diagnosis.setdefault("score_breakdown", {})
    if det:
        sb["deterministic_seo"] = det.get("seo")
        sb["deterministic_ux"] = det.get("ux")

    llm_health = final_diagnosis.get("overall_health_score")
    if llm_health is not None:
        capped = apply_reliability_caps(float(llm_health), dict(state))
        if vr.get("report_reliability") == "low":
            capped = min(capped, 5.5)
        elif vr.get("hallucination_risk") == "high":
            capped = min(capped, 6.0)
        final_diagnosis["overall_health_score"] = capped
        final_diagnosis["score_capped_for_reliability"] = capped != llm_health

    rel = state.get("audit_reliability") or {}
    if rel:
        final_diagnosis["audit_reliability"] = rel
    final_diagnosis["audit_depth"] = audit_depth

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "prioritization_agent.done",
        health_score=final_diagnosis.get("overall_health_score"),
        synthesis=final_diagnosis.get("_synthesis"),
        duration_ms=duration_ms,
    )

    return {
        "final_diagnosis": final_diagnosis,
        "status": "completed",
        "agent_reports": [
            {
                "agent": "prioritization_agent",
                "model": _MODEL if final_diagnosis.get("_synthesis") == "template+haiku" else "template",
                "output": final_diagnosis,
                "duration_ms": duration_ms,
            }
        ],
    }
