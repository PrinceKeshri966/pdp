"""
app/agents/competitor_agent.py

CompetitorAgent  (Mode 1 – Phase 2, Parallel)   Model: Claude Haiku
─────────────────────────────────────────────────────────────────────
Benchmarks the product against competitors.

Strategy (MVP Hybrid):
  1. If user provided competitor_urls → try Jina scrape (max 2 URLs)
  2. If Jina fails (403/timeout/thin content) → Claude knowledge fallback
  3. If no URLs provided → Claude knowledge only (fast, always works)
"""
from __future__ import annotations

import time

import httpx

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

_MODEL = get_model("seo")  # Haiku
_JINA_BASE = "https://r.jina.ai/"
_JINA_THIN = 500

_SYSTEM_PROMPT = """
You are an expert e-commerce competitor intelligence analyst following
Semrush and Ahrefs competitive analysis frameworks.
Analyze the product and its competitive landscape.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema:
{
  "competitors_analyzed": [string],
  "data_source": "live_scrape|claude_knowledge",
  "market_positioning": {
    "price_tier": "budget|mid-range|premium|luxury",
    "price_positioning_index": float,
    "target_segment": string,
    "differentiation": string,
    "market_maturity": "emerging|growing|mature|declining"
  },
  "benchmark_scores": {
    "avg_seo_score": float (0-10),
    "avg_ai_visibility_score": float (0-10),
    "avg_conversion_score": float (0-10),
    "avg_content_depth_score": float (0-10)
  },
  "feature_comparison": {
    "product_images_avg": int,
    "description_word_count_avg": int,
    "has_video_pct": float,
    "has_size_guide_pct": float,
    "has_reviews_pct": float,
    "avg_review_count": int
  },
  "share_of_voice": {
    "estimated_keyword_overlap_pct": float,
    "top_shared_keywords": [string],
    "your_unique_keywords": [string]
  },
  "traffic_estimate": {
    "your_tier": "low|medium|high",
    "competitor_avg_tier": "low|medium|high",
    "gap_assessment": string
  },
  "backlink_gap": {
    "your_authority_estimate": "low|medium|high",
    "competitor_avg_authority": "low|medium|high",
    "recommendation": string
  },
  "your_gaps_vs_competitors": [string],
  "winning_patterns": [string],
  "opportunities": [string],
  "category_best_practices": [string],
  "first_mover_opportunities": [string]
}
""".strip()


async def _try_jina(url: str) -> str | None:
    """Try to fetch competitor URL via Jina. Returns None on failure."""
    try:
        headers = {"Accept": "text/markdown", "X-Return-Format": "markdown"}
        if _settings.jina_api_key:
            headers["Authorization"] = f"Bearer {_settings.jina_api_key}"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(f"{_JINA_BASE}{url}", headers=headers)
            resp.raise_for_status()
            text = resp.text
            return text if len(text) > _JINA_THIN else None
    except Exception as exc:
        logger.warning("competitor_agent.jina_failed", url=url, error=str(exc))
        return None


async def competitor_agent(state: AgentState) -> AgentState:
    """Benchmark product against competitors using live data or Claude knowledge."""
    structured = state_dict(state, "json_structured_data")
    competitor_urls = state.get("competitor_urls") or []

    if not structured:
        return {"errors": ["competitor_agent: no json_structured_data"]}

    logger.info("competitor_agent.start", model=_MODEL, urls=len(competitor_urls))
    t0 = time.monotonic()

    # ── Try live scraping if user provided URLs ────────────────────────────────
    scraped_context = ""
    data_source = "claude_knowledge"

    for url in competitor_urls[:2]:  # max 2 URLs
        content = await _try_jina(url)
        if content:
            scraped_context += f"\n\nCompetitor URL: {url}\n{content[:3000]}"
            data_source = "live_scrape"
            logger.info("competitor_agent.jina_success", url=url)

    # ── Build prompt ──────────────────────────────────────────────────────────
    if scraped_context:
        user_message = f"""
Product being analyzed:
{structured}

Live competitor data:
{scraped_context}

Benchmark this product against the scraped competitors.
Identify gaps, winning patterns, and opportunities.
""".strip()
    else:
        user_message = f"""
Product being analyzed:
{structured}

No live competitor data available. Use your knowledge of the industry
to benchmark this product against typical competitors in its category.
Identify gaps, winning patterns, and opportunities based on industry standards.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    competitor_report, parse_err = safe_json_parse_report(raw, "competitor_agent")
    if parse_err:
        return {"errors": [parse_err]}
    competitor_report["data_source"] = data_source  # ensure correct source is recorded

    logger.info("competitor_agent.done", source=data_source, duration_ms=duration_ms)

    return {
        "competitor_report": competitor_report,
        "agent_reports": [
            {
                "agent": "competitor_agent",
                "model": _MODEL,
                "output": competitor_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
