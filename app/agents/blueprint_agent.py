"""
app/agents/blueprint_agent.py

BlueprintGeneratorAgent  (Mode 2 – Node 3)   Model: Claude Sonnet
───────────────────────────────────────────────────────────────────
The final synthesis step. Combines:
  • business_understanding (from BusinessAgent)
  • pdp_research          (from PDPResearcher)
  • original business_input (raw merchant brief)

…and produces a complete, ready-to-implement PDP blueprint.

Uses the Anthropic SDK directly (AsyncAnthropic.messages.create).
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("blueprint_generator")

_SYSTEM_PROMPT = """
You are a world-class e-commerce product page architect.
Synthesise the business understanding and PDP research into a complete,
production-ready Product Detail Page blueprint.

Return ONLY a valid JSON object – no prose, no markdown fences.

Required JSON schema:
{
  "blueprint_title": string,
  "executive_summary": string,
  "page_sections": [
    {
      "section_name": string,
      "order": int,
      "purpose": string,
      "content": {
        "headline": string,
        "body_copy": string,
        "cta": string,
        "media_requirements": string,
        "design_notes": string
      }
    }
  ],
  "seo_blueprint": {
    "title_tag": string,
    "meta_description": string,
    "h1": string,
    "target_keywords": [string],
    "schema_type": string
  },
  "copy_tone_guide": string,
  "ab_test_suggestions": [
    {"element": string, "variant_a": string, "variant_b": string, "hypothesis": string}
  ],
  "implementation_checklist": [
    {"task": string, "owner": string, "priority": "high|medium|low"}
  ],
  "kpis_to_track": [string],
  "estimated_cvr_uplift_pct": float
}
""".strip()


async def blueprint_agent(state: AgentState) -> AgentState:
    """Generate the final PDP blueprint by synthesising all prior agent outputs."""
    understanding = state_dict(state, "business_understanding")
    research = state_dict(state, "pdp_research")
    business_input = state.get("business_input", "")

    if not understanding or not research:
        state["errors"] = state.get("errors", []) + [
            "blueprint_agent: missing understanding or research data"
        ]
        state["status"] = "failed"
        return state

    logger.info("blueprint_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""
Original merchant brief:
{business_input}

---
Business Understanding (JSON):
{json.dumps(understanding, indent=2)}

---
PDP Research Report (JSON):
{json.dumps(research, indent=2)}

Generate the complete PDP blueprint now.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)

    blueprint = safe_json_parse(raw)

    logger.info(
        "blueprint_agent.done",
        sections=len(blueprint.get("page_sections", [])),
        duration_ms=duration_ms,
    )

    state["final_blueprint"] = blueprint
    state["status"] = "completed"
    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "blueprint_agent",
            "model": _MODEL,
            "output": blueprint,
            "duration_ms": duration_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    ]
    return state
