"""
app/agents/pdp_researcher_agent.py

PDPResearcherAgent  (Mode 2 – Node 2)   Model: Claude Haiku (fast)
────────────────────────────────────────────────────────────────────
Takes the structured business understanding and generates a research
report on best-practice PDP patterns, content requirements, and
conversion benchmarks for the specific product category.

Uses the Anthropic SDK directly (AsyncAnthropic.messages.create).
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse
from app.agents.model_router import get_model
from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("pdp_researcher")

_SYSTEM_PROMPT = """
You are a conversion rate optimisation (CRO) researcher specialising in
e-commerce product detail pages (PDPs).

Given a structured business understanding JSON, produce a research report
on best-practice PDP patterns for that exact product category.

Return ONLY a valid JSON object – no prose, no markdown fences.

Required JSON schema:
{
  "category_pdp_benchmarks": {
    "avg_conversion_rate_pct": float,
    "avg_images_per_pdp": int,
    "avg_description_word_count": int,
    "video_usage_rate_pct": float
  },
  "must_have_sections": [
    {"section": string, "purpose": string, "example_content": string}
  ],
  "trust_signals": [string],
  "social_proof_patterns": [string],
  "image_requirements": {
    "recommended_count": int,
    "angles": [string],
    "lifestyle_ratio_pct": float
  },
  "copy_frameworks": [
    {"framework": string, "description": string, "best_for": string}
  ],
  "cta_best_practices": [string],
  "mobile_ux_requirements": [string],
  "seo_content_requirements": {
    "recommended_word_count": int,
    "key_content_blocks": [string]
  },
  "common_mistakes_in_category": [string],
  "top_competitor_pdp_patterns": [string]
}
""".strip()


async def pdp_researcher_agent(state: AgentState) -> AgentState:
    """Research best-practice PDP patterns for the identified category."""
    understanding = state.get("business_understanding", {})
    if not understanding:
        state["errors"] = state.get("errors", []) + [
            "pdp_researcher_agent: no business_understanding"
        ]
        return state

    logger.info(
        "pdp_researcher_agent.start",
        model=_MODEL,
        category=understanding.get("product_category"),
    )
    t0 = time.monotonic()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Business understanding:\n\n"
                    f"{json.dumps(understanding, indent=2)}\n\n"
                    "Research the best PDP patterns for this product category."
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)

    research = safe_json_parse(raw)

    logger.info("pdp_researcher_agent.done", duration_ms=duration_ms)

    state["pdp_research"] = research
    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "pdp_researcher_agent",
            "model": _MODEL,
            "output": research,
            "duration_ms": duration_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    ]
    return state
