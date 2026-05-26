"""
app/agents/ux_agent.py

UXAgent  (Mode 1 – Phase 2, Parallel)   Model: Claude Haiku
─────────────────────────────────────────────────────────────
Analyzes PDP UX and conversion optimization signals.
Checks CTA placement, trust signals, mobile UX, storytelling,
urgency patterns, and visual hierarchy.
"""
from __future__ import annotations

import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")  # Haiku

_SYSTEM_PROMPT = """
You are an expert in e-commerce UX and Conversion Rate Optimization (CRO),
following Baymard Institute research standards (world's largest e-commerce UX research).
Analyze the product page content for conversion effectiveness.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema (Baymard Institute + Nielsen Norman Group standards):
{
  "conversion_score": float (0-10),
  "cta_analysis": {
    "found": boolean,
    "above_fold": boolean,
    "sticky_on_scroll": boolean,
    "text_quality": "weak|average|strong",
    "color_contrast": "poor|adequate|strong",
    "multiple_ctas": boolean,
    "score": float (0-10)
  },
  "product_imagery": {
    "multiple_angles": boolean,
    "zoom_capability": boolean,
    "lifestyle_images": boolean,
    "video_present": boolean,
    "image_count_adequate": boolean,
    "score": float (0-10)
  },
  "trust_signals": {
    "reviews_present": boolean,
    "rating_visible": boolean,
    "review_count_visible": boolean,
    "verified_purchase_badges": boolean,
    "security_badges": boolean,
    "payment_icons": boolean,
    "return_policy_visible": boolean,
    "shipping_info_visible": boolean,
    "money_back_guarantee": boolean,
    "score": float (0-10)
  },
  "product_information": {
    "size_guide_present": boolean,
    "material_composition": boolean,
    "care_instructions": boolean,
    "fit_description": boolean,
    "specifications_table": boolean,
    "score": float (0-10)
  },
  "mobile_ux": {
    "score": float (0-10),
    "issues": [string]
  },
  "page_layout": {
    "above_fold_content": "poor|adequate|excellent",
    "visual_hierarchy": "poor|adequate|excellent",
    "whitespace_usage": "poor|adequate|excellent",
    "score": float (0-10)
  },
  "storytelling": {
    "has_brand_story": boolean,
    "has_lifestyle_content": boolean,
    "emotional_appeal": "none|weak|moderate|strong",
    "score": float (0-10)
  },
  "urgency_scarcity": {
    "stock_counter": boolean,
    "limited_time_offer": boolean,
    "social_proof_counter": boolean,
    "recently_viewed_count": boolean,
    "score": float (0-10)
  },
  "checkout_friction": {
    "guest_checkout_implied": boolean,
    "one_click_buy": boolean,
    "cart_abandonment_risk": "low|medium|high",
    "score": float (0-10)
  },
  "recommendations": [string]
}
""".strip()


async def ux_agent(state: AgentState) -> AgentState:
    """Analyze UX and conversion optimization signals."""
    markdown = state.get("markdown_content", "")
    structured = state_dict(state, "json_structured_data")

    if not markdown:
        return {"errors": ["ux_agent: no markdown_content"]}

    logger.info("ux_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""
Analyze this product page for UX and conversion optimization:

Product Data:
{structured}

Page Content (first 6000 chars):
{markdown[:6000]}

Check: CTA placement, trust signals, mobile UX issues, brand storytelling,
urgency patterns, product imagery, and overall conversion readiness.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    ux_report, parse_err = safe_json_parse_report(raw, "ux_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "ux_agent.done",
        score=ux_report.get("conversion_score"),
        duration_ms=duration_ms,
    )

    return {
        "ux_report": ux_report,
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
