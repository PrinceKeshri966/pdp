"""
app/agents/psychology_agent.py

PsychologyAgent — deterministic trigger extraction + Claude persuasion reasoning.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.agents.claude_client import claude
from app.agents.context_router import format_context_for_llm
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.psychology_preprocessor import extract_psychology_facts
from app.agents.scoring_engine import apply_reliability_caps, blend_score, compute_deterministic_scores
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")

_SYSTEM_PROMPT = """
You are a consumer psychology & persuasion expert (Cialdini + Fogg B=MAP).
PRECOMPUTED_PSYCH_FACTS list detected scarcity, urgency, social proof snippets, etc.
Do NOT re-list raw snippets.

Return ONLY valid JSON:
{
  "overall_psychology_score": float (0-10),
  "fogg_model": {
    "motivation_score": float (0-10),
    "ability_score": float (0-10),
    "prompt_score": float (0-10),
    "behavior_likelihood": "very_low|low|medium|high|very_high"
  },
  "missing_triggers": [string],
  "recommended_triggers": [
    {"trigger": string, "implementation": string, "psychology_principle": string, "expected_cvr_lift": string}
  ],
  "pricing_psychology": {"suggestion": string, "anchor_price_recommendation": string},
  "loss_aversion": {"suggestions": [string]},
  "emotional_appeal": {"suggestions": [string]},
  "trust_building": {"suggestions": [string]}
}
""".strip()


def _cialdini_from_facts(facts: dict[str, Any]) -> dict[str, Any]:
    def block(present: bool, score: float = 6.0) -> dict[str, Any]:
        return {"present": present, "score": score if present else 2.0}

    return {
        "reciprocity": block(bool(facts.get("reciprocity_signals"))),
        "commitment": block(bool(facts.get("commitment_signals"))),
        "social_proof": block(bool(facts.get("social_proof_snippets") or facts.get("has_reviews")), 7.5),
        "authority": block(bool(facts.get("authority_claims")), 7.0),
        "liking": block(bool(facts.get("emotional_phrases")), 6.0),
        "scarcity": block(bool(facts.get("scarcity_language")), 7.0),
        "unity": block(bool(facts.get("unity_detected")), 6.5),
    }


def merge_psychology_report(facts: dict[str, Any], llm: dict[str, Any], *, det_score: float | None = None) -> dict[str, Any]:
    triggers: list[str] = []
    triggers.extend(facts.get("scarcity_language") or [])
    triggers.extend(facts.get("urgency_language") or [])
    triggers.extend(facts.get("social_proof_snippets") or [])
    triggers.extend(facts.get("authority_claims") or [])

    cialdini = _cialdini_from_facts(facts)
    scores = [v["score"] for v in cialdini.values() if v.get("present")]

    return {
        "overall_psychology_score": det_score
        if det_score is not None
        else (
            llm.get("overall_psychology_score")
            or (round(sum(scores) / max(len(scores), 1), 1) if scores else 5.0)
        ),
        "deterministic_psychology_score": det_score,
        "cialdini_principles": cialdini,
        "fogg_model": llm.get("fogg_model")
        or {
            "motivation_score": 6.0,
            "ability_score": 6.0,
            "prompt_score": 5.0,
            "behavior_likelihood": "medium",
        },
        "current_triggers_found": list(dict.fromkeys(triggers))[:12],
        "missing_triggers": llm.get("missing_triggers") or [],
        "recommended_triggers": llm.get("recommended_triggers") or [],
        "pricing_psychology": {
            "current_price_display": facts.get("price_display"),
            "charm_pricing_used": facts.get("charm_pricing_detected", False),
            "anchor_price_present": facts.get("anchor_price_present", False),
            "decoy_pricing_detected": bool(facts.get("decoy_pricing_detected")),
            "peak_end_rule_applied": bool(facts.get("peak_end_rule_detected")),
            "suggestion": (llm.get("pricing_psychology") or {}).get("suggestion", ""),
            "anchor_price_recommendation": (llm.get("pricing_psychology") or {}).get(
                "anchor_price_recommendation", ""
            ),
        },
        "loss_aversion": llm.get("loss_aversion")
        or {"present": bool(facts.get("urgency_language")), "suggestions": []},
        "emotional_appeal": {
            "current_level": "moderate" if len(facts.get("emotional_phrases") or []) > 2 else "weak",
            "identity_alignment": bool(facts.get("identity_alignment_detected")),
            "aspirational_language": bool(facts.get("emotional_phrases")),
            "suggestions": (llm.get("emotional_appeal") or {}).get("suggestions", []),
        },
        "trust_building": {
            "current_level": "moderate" if facts.get("has_reviews") else "weak",
            "suggestions": (llm.get("trust_building") or {}).get("suggestions", []),
        },
        "_precomputed_facts": {k: v for k, v in facts.items() if not k.startswith("_")},
    }


async def psychology_agent(state: AgentState) -> AgentState:
    plan = state_dict(state, "agent_plan")
    if not plan.get("run_psychology", True):
        stub = {
            "overall_psychology_score": 5.0,
            "skipped": True,
            "skip_reason": (plan.get("skipped_reasons") or {}).get("psychology", "agent plan"),
        }
        return {
            "psychology_report": stub,
            "agent_reports": [{"agent": "psychology_agent", "model": "skipped", "output": stub, "duration_ms": 0}],
        }

    packages = state.get("agent_context_packages") or {}
    psych_ctx = packages.get("psychology")
    if not psych_ctx:
        return {"errors": ["psychology_agent: no agent_context_packages.psychology"]}

    structured = state_dict(state, "json_structured_data")
    psych_facts = extract_psychology_facts(
        page_contexts=state.get("page_contexts"),
        structured=structured,
        markdown=state.get("markdown_content") or "",
        scrape_html=state.get("scrape_html") or "",
    )

    logger.info("psychology_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""PRECOMPUTED_PSYCH_FACTS:
{json.dumps({k: v for k, v in psych_facts.items() if k != '_deterministic'}, separators=(',', ':'))}

Psychology context package:
{format_context_for_llm(psych_ctx, max_chars=2500)}

Product: {structured.get('product_name', '')}

Recommend persuasion improvements and behavioral triggers only."""

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    llm_layer, parse_err = safe_json_parse_report(raw, "psychology_agent")
    if parse_err:
        return {"errors": [parse_err]}

    psychology_report = merge_psychology_report(psych_facts, llm_layer)
    det = compute_deterministic_scores(
        psych_facts=psych_facts,
        scrape_validation=state_dict(state, "scrape_validation"),
        extraction_confidence=state_dict(state, "extraction_confidence"),
    )
    det_psych = det["deterministic_scores"]["psychology"]
    psych_facts["deterministic_psychology_score"] = det_psych
    blended = blend_score(det_psych, llm_layer.get("overall_psychology_score"))
    psychology_report = merge_psychology_report(psych_facts, llm_layer, det_score=blended)
    if psychology_report.get("overall_psychology_score") is not None:
        psychology_report["overall_psychology_score"] = apply_reliability_caps(
            float(psychology_report["overall_psychology_score"]), dict(state)
        )
    logger.info(
        "psychology_agent.done",
        score=psychology_report.get("overall_psychology_score"),
        duration_ms=duration_ms,
    )

    return {
        "psychology_report": psychology_report,
        "psychology_preprocessor_facts": psych_facts,
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
