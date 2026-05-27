"""
app/agents/psychology_agent.py

PsychologyAgent  (Mode 1 – Phase 2, Parallel)   Model: Claude Haiku
─────────────────────────────────────────────────────────────────────
Analyzes conversion psychology patterns on the PDP.
Suggests behavioral triggers: scarcity, social proof, authority,
urgency, pricing psychology, and emotional commerce triggers.
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
You are an expert in consumer psychology and e-commerce conversion optimization,
applying Cialdini's 7 Principles of Persuasion and BJ Fogg's Behavior Model (B=MAP).
Analyze the product page for psychological conversion triggers.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema (Cialdini + Fogg Behavior Model):
{
  "overall_psychology_score": float (0-10),
  "cialdini_principles": {
    "reciprocity": {"present": boolean, "score": float (0-10)},
    "commitment": {"present": boolean, "score": float (0-10)},
    "social_proof": {"present": boolean, "score": float (0-10)},
    "authority": {"present": boolean, "score": float (0-10)},
    "liking": {"present": boolean, "score": float (0-10)},
    "scarcity": {"present": boolean, "score": float (0-10)},
    "unity": {"present": boolean, "score": float (0-10)}
  },
  "fogg_model": {
    "motivation_score": float (0-10),
    "ability_score": float (0-10),
    "prompt_score": float (0-10),
    "behavior_likelihood": "very_low|low|medium|high|very_high"
  },
  "current_triggers_found": [string],
  "missing_triggers": [string],
  "recommended_triggers": [
    {
      "trigger": string,
      "implementation": string,
      "psychology_principle": string,
      "expected_cvr_lift": string
    }
  ],
  "pricing_psychology": {
    "current_price_display": string,
    "charm_pricing_used": boolean,
    "anchor_price_present": boolean,
    "decoy_pricing_detected": boolean,
    "peak_end_rule_applied": boolean,
    "suggestion": string,
    "anchor_price_recommendation": string
  },
  "loss_aversion": {
    "present": boolean,
    "suggestions": [string]
  },
  "emotional_appeal": {
    "current_level": "none|weak|moderate|strong",
    "identity_alignment": boolean,
    "aspirational_language": boolean,
    "suggestions": [string]
  },
  "trust_building": {
    "current_level": "none|weak|moderate|strong",
    "suggestions": [string]
  }
}
""".strip()


async def psychology_agent(state: AgentState) -> AgentState:
    """Analyze conversion psychology and suggest behavioral triggers."""
    markdown = state.get("markdown_content", "")
    structured = state_dict(state, "json_structured_data")

    if not markdown:
        return {"errors": ["psychology_agent: no markdown_content"]}

    logger.info("psychology_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""
Analyze this product page for conversion psychology:

Product Data:
{structured}

Page Content (first 5000 chars):
{markdown[:5000]}

Identify existing psychological triggers, missing ones, and suggest
specific implementations with expected conversion lift.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    psychology_report, parse_err = safe_json_parse_report(raw, "psychology_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "psychology_agent.done",
        score=psychology_report.get("overall_psychology_score"),
        duration_ms=duration_ms,
    )

    return {
        "psychology_report": psychology_report,
        "agent_reports": [
            {
                "agent": "psychology_agent",
                "model": _MODEL,
                "output": psychology_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
