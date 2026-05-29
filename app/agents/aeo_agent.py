"""
app/agents/aeo_agent.py

AEOAgent — deterministic AEO facts + Claude for narrative/explanation only.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.agents.aeo_preprocessor import extract_aeo_facts
from app.agents.claude_client import claude
from app.agents.context_router import format_context_for_llm
from app.rulesets.base import ruleset_prompt_block
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.scoring_engine import apply_reliability_caps, blend_score, compute_deterministic_scores
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")

_SYSTEM_PROMPT = """
You are an expert in Answer Engine Optimization (AEO), AI Overviews, and generative AI search.
PRECOMPUTED_AEO_FACTS already contain deterministic schema/FAQ/entity signals — do NOT re-detect them.

Your job: semantic reasoning and narrative ONLY. Return ONLY valid JSON (no markdown fences):
{
  "geo_signals": {
    "perplexity_citable": boolean,
    "sge_snippet_ready": boolean,
    "direct_answer_format": boolean,
    "issues": [string]
  },
  "eeat_score": {
    "overall": float (0-10),
    "experience": float (0-10),
    "expertise": float (0-10),
    "authoritativeness": float (0-10),
    "trustworthiness": float (0-10),
    "signals_found": [string],
    "signals_missing": [string]
  },
  "rag_readiness": {
    "score": float (0-10),
    "is_citable": boolean,
    "unique_value_proposition": boolean,
    "factual_claims_present": boolean,
    "issues": [string]
  },
  "semantic_richness_score": float (0-10),
  "content_quality": {
    "conversational_readiness": boolean,
    "llm_snippet_ready": boolean,
    "commodity_content": boolean,
    "has_unique_perspective": boolean,
    "content_depth": "thin|moderate|comprehensive",
    "score": float (0-10)
  },
  "brand_clarity_score": float (0-10),
  "gaps": [string],
  "recommendations": [string],
  "top_ai_queries_missed": [string],
  "quick_wins_for_ai": [string],
  "ai_visibility_score": float (0-10)
}
""".strip()


def merge_aeo_report(facts: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    faq_quality_label = "none"
    fc = facts.get("faq_count") or 0
    if fc >= 5:
        faq_quality_label = "excellent"
    elif fc >= 3:
        faq_quality_label = "good"
    elif fc >= 1:
        faq_quality_label = "average"

    return {
        "ai_visibility_score": llm.get("ai_visibility_score", facts.get("deterministic_aeo_score", 5.0)),
        "deterministic_aeo_score": facts.get("deterministic_aeo_score"),
        "geo_score": llm.get("geo_score") or llm.get("semantic_richness_score") or facts.get("deterministic_aeo_score", 5.0),
        "geo_signals": llm.get("geo_signals") or {},
        "eeat_score": llm.get("eeat_score") or {},
        "rag_readiness": llm.get("rag_readiness") or {},
        "semantic_richness_score": llm.get("semantic_richness_score", 5.0),
        "faq_quality": {
            "found": fc > 0 or facts.get("faq_schema"),
            "count": fc,
            "quality": faq_quality_label,
            "conversational_format": fc > 0,
            "score": facts.get("faq_score", 5.0),
        },
        "structured_data": {
            "product_schema": facts.get("product_schema", False),
            "faq_schema": facts.get("faq_schema", False),
            "breadcrumb_schema": facts.get("breadcrumb_schema", False),
            "review_schema": facts.get("review_schema", False),
            "speakable_schema": facts.get("speakable_schema", False),
            "score": facts.get("structured_data_score", 5.0),
        },
        "entity_coverage": facts.get("entity_coverage"),
        "answerability_coverage": facts.get("answerability_coverage"),
        "content_quality": llm.get("content_quality") or {},
        "brand_clarity_score": llm.get("brand_clarity_score", 5.0),
        "gaps": llm.get("gaps") or [],
        "recommendations": llm.get("recommendations") or [],
        "top_ai_queries_missed": llm.get("top_ai_queries_missed") or [],
        "quick_wins_for_ai": llm.get("quick_wins_for_ai") or [],
        "_precomputed_facts": {k: v for k, v in facts.items() if not k.startswith("_")},
    }


async def aeo_agent(state: AgentState) -> AgentState:
    """Analyze AI/LLM visibility with deterministic base + LLM narrative."""
    packages = state.get("agent_context_packages") or {}
    aeo_ctx = packages.get("aeo")
    if not aeo_ctx:
        return {"errors": ["aeo_agent: no agent_context_packages.aeo"]}

    structured = state_dict(state, "json_structured_data")
    plan = state_dict(state, "agent_plan")
    page_type = state_dict(state, "page_type_info").get("page_type") or "unknown"
    seo_facts = state_dict(state, "seo_preprocessor_facts")
    browser_capture = (state.get("browser_capture") or {})
    t0 = time.monotonic()

    aeo_facts = extract_aeo_facts(
        html=state.get("scrape_html") or "",
        markdown=state.get("markdown_content") or "",
        structured=structured,
        seo_facts=seo_facts,
        browser_capture=browser_capture,
    )

    if not plan.get("run_aeo_deep", True):
        det_score = aeo_facts.get("deterministic_aeo_score", 5.0)
        aeo_report = merge_aeo_report(aeo_facts, {"ai_visibility_score": det_score})
        aeo_report["ai_visibility_score"] = apply_reliability_caps(float(det_score), dict(state))
        aeo_report["_lightweight"] = True
        duration_ms = int((time.monotonic() - t0) * 1000)
        return {
            "aeo_report": aeo_report,
            "aeo_preprocessor_facts": aeo_facts,
            "agent_reports": [{"agent": "aeo_agent", "model": "deterministic", "output": aeo_report, "duration_ms": duration_ms}],
        }

    logger.info("aeo_agent.start", model=_MODEL)

    page_note = ruleset_prompt_block(page_type) + "\n\n"

    user_message = f"""{page_note}PRECOMPUTED_AEO_FACTS:
{json.dumps({k: v for k, v in aeo_facts.items() if k != '_deterministic'}, separators=(',', ':'))}

Product Data:
{structured}

AEO context package (main + faq + about when available):
{format_context_for_llm(aeo_ctx)}

Provide semantic AEO narrative, E-E-A-T assessment, and recommendations only."""

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    llm_layer, parse_err = safe_json_parse_report(raw, "aeo_agent")
    if parse_err:
        return {"errors": [parse_err]}

    aeo_report = merge_aeo_report(aeo_facts, llm_layer)
    det = compute_deterministic_scores(
        seo_facts=seo_facts,
        aeo_facts=aeo_facts,
        scrape_validation=state_dict(state, "scrape_validation"),
        extraction_confidence=state_dict(state, "extraction_confidence"),
        page_type=page_type,
    )
    blended = blend_score(
        det["deterministic_scores"]["aeo"],
        llm_layer.get("ai_visibility_score"),
    )
    aeo_report["ai_visibility_score"] = apply_reliability_caps(blended, dict(state))
    aeo_report["deterministic_aeo_score"] = det["deterministic_scores"]["aeo"]

    logger.info(
        "aeo_agent.done",
        score=aeo_report.get("ai_visibility_score"),
        duration_ms=duration_ms,
    )

    return {
        "aeo_report": aeo_report,
        "aeo_preprocessor_facts": aeo_facts,
        "agent_reports": [
            {
                "agent": "aeo_agent",
                "model": _MODEL,
                "output": aeo_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
