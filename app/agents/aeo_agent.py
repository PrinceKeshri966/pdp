"""
app/agents/aeo_agent.py

AEOAgent  (Mode 1 – Phase 2, Parallel)   Model: Claude Haiku
──────────────────────────────────────────────────────────────
AEO = Answer Engine Optimization.
Analyzes whether the PDP is discoverable and retrievable by
AI answer engines: ChatGPT, Gemini, Claude, Perplexity.

Checks semantic richness, FAQ quality, structured data,
conversational readiness, and LLM snippet readiness.
"""
from __future__ import annotations

import time

from app.agents.claude_client import claude
from app.agents.competitor_discovery import resolve_homepage_mode
from app.agents.context_router import format_context_for_llm
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")  # Haiku

_SYSTEM_PROMPT = """
You are an expert in Answer Engine Optimization (AEO), AI Overviews, and generative AI search.
You follow Google's official AI optimization guide and E-E-A-T (Experience, Expertise,
Authoritativeness, Trustworthiness) framework.

Analyze the product page and determine how well it will be cited by AI answer engines:
ChatGPT, Google AI Overviews, Gemini, Claude, and Perplexity.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema (based on Google AI Optimization Guide + E-E-A-T framework):
{
  "ai_visibility_score": float (0-10),
  "geo_score": float (0-10),
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
  "faq_quality": {
    "found": boolean,
    "count": int,
    "quality": "none|poor|average|good|excellent",
    "conversational_format": boolean,
    "score": float (0-10)
  },
  "structured_data": {
    "product_schema": boolean,
    "faq_schema": boolean,
    "breadcrumb_schema": boolean,
    "review_schema": boolean,
    "speakable_schema": boolean,
    "score": float (0-10)
  },
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
  "quick_wins_for_ai": [string]
}
""".strip()


async def aeo_agent(state: AgentState) -> AgentState:
    """Analyze AI/LLM visibility and answer engine optimization."""
    packages = state.get("agent_context_packages") or {}
    aeo_ctx = packages.get("aeo")
    if not aeo_ctx:
        return {"errors": ["aeo_agent: no agent_context_packages.aeo"]}

    structured = state_dict(state, "json_structured_data")

    logger.info("aeo_agent.start", model=_MODEL)
    t0 = time.monotonic()

    page_url = state.get("url") or ""
    homepage_mode = resolve_homepage_mode(page_url, state.get("compare_as"))
    page_note = (
        "Page type: HOMEPAGE. Missing Product schema is normal; score Organization/WebSite/FAQ schema instead.\n\n"
        if homepage_mode
        else ""
    )

    user_message = f"""{page_note}Analyze this page for AI answer engine visibility (AEO/GEO):

Product Data:
{structured}

AEO context package (main + faq + about when available):
{format_context_for_llm(aeo_ctx)}

Evaluate: E-E-A-T signals, RAG-readiness, FAQ quality, structured data types,
conversational language readiness, brand clarity, and which AI queries this page would miss.""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    aeo_report, parse_err = safe_json_parse_report(raw, "aeo_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "aeo_agent.done",
        score=aeo_report.get("ai_visibility_score"),
        duration_ms=duration_ms,
    )

    return {
        "aeo_report": aeo_report,
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
