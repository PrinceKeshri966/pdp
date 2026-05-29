"""
CompetitorAgent — real side-by-side compare from live scrapes (no dummy data).
Parallel fetch + Redis/memory snapshot cache.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

from app.agents.competitor_discovery import discover_competitor_urls, resolve_homepage_mode
from app.agents.page_features import (
    build_comparison_matrix,
    features_from_markdown,
    features_from_structured,
    gaps_from_matrix,
)
from app.agents.page_fetch import fetch_page_markdown
from app.agents.state import AgentState, state_dict
from app.core.cache import cache_get, cache_key, cache_set, competitor_cache_ttl
from app.agents.competitor_intelligence import synthesize_competitor_intelligence
from app.core.browser_capture.competitor_benchmark import build_benchmark_metrics
from app.core.demo_mode import is_demo_mode
from app.core.logging import get_logger

logger = get_logger(__name__)


def _site_label(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url[:40]


def _features_usable(feat: dict) -> bool:
    if not feat:
        return False
    wc = feat.get("page_word_count") or 0
    imgs = feat.get("images_count") or 0
    return wc >= 50 or imgs >= 1 or feat.get("has_reviews") or feat.get("price")


async def _extract_features_with_llm(markdown: str, url: str) -> dict:
    from app.agents.claude_client import claude
    from app.agents.json_utils import safe_json_parse
    from app.agents.model_router import get_model

    response = await claude.messages.create(
        model=get_model("scraper_parser"),
        max_tokens=500,
        system="Extract product page features. Return ONLY valid JSON, no prose.",
        messages=[
            {
                "role": "user",
                "content": f"""From this product page content, extract:
{{
  "product_name": string,
  "images_count": int,
  "has_video": boolean,
  "has_reviews": boolean,
  "review_count": int or null,
  "avg_rating": float or null,
  "page_word_count": int,
  "has_size_guide": boolean,
  "has_return_policy": boolean,
  "price": string or null
}}

Page URL: {url}
Content (first 3000 chars):
{markdown[:3000]}""",
            }
        ],
    )
    return safe_json_parse(response.content[0].text)


def _skipped_competitor_report(reason: str) -> dict[str, Any]:
    return {
        "competitors_analyzed": [],
        "data_source": "skipped",
        "skipped": True,
        "skip_reason": reason,
        "live_compare": {"sites": [], "rows": []},
        "your_gaps_vs_competitors": [],
        "winning_patterns": [],
        "opportunities": [],
        "feature_comparison": {},
    }


async def _scrape_competitor_site(url: str, compare_page_type: str) -> dict[str, Any]:
    """Fetch one competitor with optional cache."""
    cache_k = cache_key("competitor_snap", url, compare_page_type)
    cached = await cache_get(cache_k)
    if is_demo_mode() and not cached:
        # Demo: prefer any cached snapshot for same host (faster CTO walkthrough)
        host_key = cache_key("competitor_snap", urlparse(url).netloc, compare_page_type)
        cached = await cache_get(host_key)
    if cached and cached.get("features"):
        cached["_cache_hit"] = True
        return {
            "role": "competitor",
            "name": _site_label(url),
            "url": url,
            "page_type": compare_page_type,
            "scrape_ok": True,
            "features": cached["features"],
            "from_cache": True,
        }

    markdown = await fetch_page_markdown(url)
    if not markdown:
        return {
            "role": "competitor",
            "name": _site_label(url),
            "url": url,
            "page_type": compare_page_type,
            "scrape_ok": False,
            "features": {},
        }

    feat = features_from_markdown(markdown, url)
    if not _features_usable(feat):
        logger.info("competitor_agent.llm_fallback", url=url)
        feat = await _extract_features_with_llm(markdown, url)

    await cache_set(cache_k, {"features": feat, "url": url}, competitor_cache_ttl(compare_page_type))
    return {
        "role": "competitor",
        "name": _site_label(url),
        "url": url,
        "page_type": compare_page_type,
        "scrape_ok": True,
        "features": feat,
    }


def _avg_feature(sites: list[dict[str, Any]], key: str) -> float | None:
    vals = [s["features"].get(key) for s in sites[1:] if s.get("scrape_ok") and s.get("features")]
    nums = [float(v) for v in vals if isinstance(v, (int, float)) and v is not None]
    return round(sum(nums) / len(nums), 1) if nums else None


async def competitor_agent(state: AgentState) -> AgentState:
    plan = state_dict(state, "agent_plan")
    if not plan.get("run_competitor", True):
        reason = (plan.get("skipped_reasons") or {}).get("competitor", "agent plan skip")
        report = _skipped_competitor_report(reason)
        return {
            "competitor_report": report,
            "agent_reports": [
                {"agent": "competitor_agent", "model": "skipped", "output": report, "duration_ms": 0}
            ],
        }

    structured = state_dict(state, "json_structured_data")
    if not structured:
        return {"errors": ["competitor_agent: no json_structured_data"]}

    user_url = (state.get("url") or structured.get("product_url") or "").strip()
    competitor_urls = state.get("competitor_urls") or []
    compare_as = (state.get("compare_as") or "auto").lower().strip()
    homepage_mode = resolve_homepage_mode(user_url, compare_as)
    compare_page_type = "homepage" if homepage_mode else "product"
    t0 = time.monotonic()

    you = features_from_structured(structured)
    sites: list[dict[str, Any]] = [
        {
            "role": "you",
            "name": "Your site",
            "url": user_url,
            "page_type": compare_page_type,
            "scrape_ok": True,
            "features": you,
        }
    ]

    urls = await discover_competitor_urls(
        user_url,
        structured.get("product_name") or "",
        structured.get("categories") or [],
        existing=competitor_urls,
        limit=3,
        homepage_mode=homepage_mode,
    )
    logger.info("competitor_agent.discovered", count=len(urls), urls=urls)

    if urls:
        results = await asyncio.gather(
            *[_scrape_competitor_site(u, compare_page_type) for u in urls],
            return_exceptions=True,
        )
        for url, res in zip(urls, results):
            if isinstance(res, Exception):
                logger.warning("competitor_agent.scrape_error", url=url, error=str(res))
                sites.append(
                    {
                        "role": "competitor",
                        "name": _site_label(url),
                        "url": url,
                        "page_type": compare_page_type,
                        "scrape_ok": False,
                        "features": {},
                    }
                )
            else:
                sites.append(res)

    scraped = sum(1 for s in sites if s.get("role") == "competitor" and s.get("scrape_ok"))
    rows = build_comparison_matrix(
        [s for s in sites if s.get("scrape_ok")],
        homepage_mode=homepage_mode,
    )
    gaps = gaps_from_matrix([s for s in sites if s.get("scrape_ok")], rows)
    wins = [f"You lead on {r['label']}" for r in rows if r.get("you_win")]

    data_source = "live_scrape" if scraped else ("user_only" if not urls else "partial")

    benchmark_metrics = build_benchmark_metrics(
        your_features=you,
        competitor_features=[s["features"] for s in sites if s.get("role") == "competitor" and s.get("scrape_ok")],
        your_lighthouse=(state.get("browser_capture") or {}).get("lighthouse"),
        your_schema=(state.get("browser_capture") or {}).get("schema_validation"),
    )
    feature_comparison = {
        "product_images_avg": _avg_feature(sites, "images_count"),
        "description_word_count_avg": _avg_feature(sites, "page_word_count"),
        "has_video_pct": round(
            100 * sum(1 for s in sites[1:] if s.get("scrape_ok") and s["features"].get("has_video"))
            / max(scraped, 1),
            0,
        ),
        "has_size_guide_pct": round(
            100
            * sum(1 for s in sites[1:] if s.get("scrape_ok") and s["features"].get("has_size_guide"))
            / max(scraped, 1),
            0,
        ),
        "has_reviews_pct": round(
            100
            * sum(1 for s in sites[1:] if s.get("scrape_ok") and s["features"].get("has_reviews"))
            / max(scraped, 1),
            0,
        ),
        "avg_review_count": _avg_feature(sites, "review_count"),
    }
    intelligence = synthesize_competitor_intelligence(
        sites=sites,
        structured=structured,
        gaps=gaps,
        wins=wins,
        feature_comparison=feature_comparison,
        benchmark_metrics=benchmark_metrics,
    ) if scraped else {}

    competitor_report: dict[str, Any] = {
        "competitors_analyzed": [_site_label(s["url"]) for s in sites if s["role"] == "competitor"],
        "data_source": data_source,
        "live_compare": {
            "compare_as": compare_as,
            "compare_page_type": compare_page_type,
            "metrics_note": (
                "Each number is measured on the exact URL shown above (one homepage or one product page per site), "
                "from live rendered DOM at audit time — not sitewide averages."
            ),
            "sites": sites,
            "rows": rows,
        },
        "benchmark_metrics": benchmark_metrics,
        "your_gaps_vs_competitors": gaps,
        "winning_patterns": wins,
        "opportunities": gaps[:5],
        "feature_comparison": feature_comparison,
        **intelligence,
    }

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info("competitor_agent.done", scraped=scraped, rows=len(rows), duration_ms=duration_ms)

    return {
        "competitor_report": competitor_report,
        "agent_reports": [
            {
                "agent": "competitor_agent",
                "model": "live_scrape",
                "output": competitor_report,
                "duration_ms": duration_ms,
            }
        ],
    }
