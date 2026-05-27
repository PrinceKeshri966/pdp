"""
app/agents/business_agent.py

BusinessUnderstandingAgent  (Mode 2 – Node 1)   Model: Claude Sonnet
──────────────────────────────────────────────────────────────────────
Receives a free-text business brief from the user and extracts a
structured understanding of intent, category, audience, USPs, and
competitive positioning.

Uses the Anthropic SDK directly (AsyncAnthropic.messages.create).
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("business_understanding")

_SYSTEM_PROMPT = """
You are a senior e-commerce business strategist.
A merchant has described their product or business in plain English.
Extract a deep, structured understanding of their intent.

Return ONLY a valid JSON object – no prose, no markdown fences.

Required JSON schema:
{
  "brand_name": string,
  "product_name": string,
  "product_category": string,
  "sub_category": string,
  "primary_audience": {
    "demographics": string,
    "psychographics": string,
    "pain_points": [string],
    "purchase_motivations": [string]
  },
  "unique_selling_propositions": [string],
  "key_features": [string],
  "price_positioning": "budget|mid-range|premium|luxury",
  "competitors": [string],
  "tone_of_voice": string,
  "primary_markets": [string],
  "merchant_goals": [string],
  "content_gaps_identified": [string],
  "recommended_pdp_sections": [string]
}
""".strip()


async def business_agent(state: AgentState) -> AgentState:
    """Understand the merchant's business intent from a free-text brief."""
    business_input = state.get("business_input", "")
    if not business_input:
        state["errors"] = state.get("errors", []) + ["business_agent: no business_input"]
        state["status"] = "failed"
        return state

    logger.info("business_agent.start", model=_MODEL, chars=len(business_input))
    t0 = time.monotonic()

    # Include any uploaded file context if present to improve understanding
    uploaded_ctx = state.get("uploaded_context") or ""
    user_content = (
        (f"Uploaded context:\n\n{uploaded_ctx}\n\n") if uploaded_ctx else ""
    ) + f"Here is the merchant's business brief:\n\n{business_input}"

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)

    understanding, parse_err = safe_json_parse_report(raw, "business_agent")
    if parse_err:
        state["errors"] = state.get("errors", []) + [parse_err]
        state["status"] = "failed"
        return state

    logger.info(
        "business_agent.done",
        category=understanding.get("product_category"),
        duration_ms=duration_ms,
    )

    state["business_understanding"] = understanding
    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "business_agent",
            "model": _MODEL,
            "output": understanding,
            "duration_ms": duration_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    ]
    return state
