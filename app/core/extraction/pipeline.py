"""
Orchestrate multi-strategy extraction + optional LLM gap-fill + second pass.
"""
from __future__ import annotations

import os
import time
from typing import Any

from app.agents.extraction_confidence import score_extraction_confidence
from app.core.extraction.dom_extractors import (
    extract_dom_selectors,
    extract_network_product_payloads,
    extract_next_data,
    extract_open_graph,
    extract_review_widgets,
)
from app.core.extraction.json_ld import extract_json_ld_product
from app.core.extraction.platform_api import fetch_platform_api_product
from app.core.extraction.voter import vote_product_fields
from app.core.logging import get_logger

logger = get_logger(__name__)

# Defaults aligned with extractor_agent schema
_PRODUCT_DEFAULTS: dict[str, Any] = {
    "currency": "INR",
    "availability": "InStock",
    "condition": "NewCondition",
    "rating_max": 5.0,
    "has_video": False,
    "has_size_guide": False,
    "has_reviews": False,
    "images_count": 0,
    "related_products_count": 0,
    "features": [],
    "categories": [],
    "image_urls": [],
    "video_urls": [],
    "color_variants": [],
    "size_variants": [],
    "trust_badges": [],
}


def _playwright_enabled() -> bool:
    return os.getenv("SKIP_PLAYWRIGHT", "true").lower() not in ("1", "true", "yes")


def _needs_retry(merged: dict[str, Any]) -> bool:
    name = (merged.get("product_name") or "").strip().lower()
    if not name or name in ("unknown", "product", "mamaearth", "boat", "home"):
        if len(name) <= 12:
            return True
    if not merged.get("price"):
        return True
    if not merged.get("has_reviews") and not merged.get("review_count"):
        return True
    return False


async def _llm_extract_gap_fill(
    markdown: str,
    url: str,
    partial: dict[str, Any],
    *,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Haiku only for fields still missing after deterministic merge."""
    missing = [
        k
        for k in ("product_name", "price", "description", "brand")
        if not partial.get(k)
    ]
    if not missing or not markdown:
        return {}
    from app.agents.claude_client import claude
    from app.agents.json_utils import safe_json_parse_report
    from app.agents.model_router import get_model

    model = get_model("scraper_parser")
    prompt = (
        f"URL: {url}\n"
        f"Fill ONLY these missing fields from page text: {missing}\n"
        f"Return JSON object with only those keys. No hallucination — omit if not in text.\n\n"
        f"{markdown[:max_chars]}"
    )
    try:
        response = await claude.messages.create(
            model=model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        data, err = safe_json_parse_report(raw, "extraction_gap_fill")
        return data if not err and isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("extraction.llm_gap_failed", error=str(exc))
        return {}


async def _refetch_for_missing_fields(url: str, *, review_focus: bool) -> dict[str, Any]:
    """Second-pass Playwright re-scrape when critical fields are missing."""
    if not _playwright_enabled():
        return {}
    from app.core.extraction.playwright_pdp import fetch_pdp_with_playwright

    try:
        return await fetch_pdp_with_playwright(url, review_focus=review_focus)
    except Exception as exc:
        logger.warning("extraction.refetch_failed", url=url, error=str(exc))
        return {}


def _apply_defaults(data: dict[str, Any], url: str) -> dict[str, Any]:
    out = {**_PRODUCT_DEFAULTS, **data}
    out["product_url"] = url
    if out.get("images_count") is None and out.get("image_urls"):
        out["images_count"] = len(out["image_urls"])
    return out


async def run_extraction_pipeline(
    *,
    url: str,
    markdown: str,
    scrape_html: str,
    network_payloads: list[dict[str, Any]] | None = None,
    platform_info: dict[str, Any] | None = None,
    scrape_validation: dict[str, Any] | None = None,
    second_pass: bool = False,
) -> dict[str, Any]:
    """
    Run schema → platform API → network → DOM → OG → Next → optional LLM → vote.
    Returns { json_structured_data, extraction_confidence, extraction_meta }.
    """
    t0 = time.monotonic()
    html = scrape_html or ""
    payloads = list(network_payloads or [])
    plat = (platform_info or {}).get("platform") or "generic"

    if second_pass and _playwright_enabled():
        review_focus = True
        refetch = await _refetch_for_missing_fields(url, review_focus=review_focus)
        if refetch:
            markdown = refetch.get("markdown_content") or markdown
            html = refetch.get("scrape_html") or html
            payloads = refetch.get("network_payloads") or payloads
            platform_info = refetch.get("platform_info") or platform_info
            plat = (platform_info or {}).get("platform") or plat

    schema = extract_json_ld_product(html)
    open_graph = extract_open_graph(html)
    dom = extract_dom_selectors(html)
    dom_reviews = extract_review_widgets(html)
    for k, v in dom_reviews.items():
        if v not in (None, "", []) and k not in dom:
            dom[k] = v
    next_data = extract_next_data(html)
    network = extract_network_product_payloads(payloads)
    platform_api = await fetch_platform_api_product(url, plat, network_payloads=payloads)

    llm: dict[str, Any] = {}
    pre_merge = {**schema, **platform_api, **network, **dom}
    if second_pass or not pre_merge.get("price") or not pre_merge.get("product_name"):
        llm = await _llm_extract_gap_fill(markdown, url, pre_merge)

    merged, field_meta = vote_product_fields(
        schema=schema,
        open_graph=open_graph,
        dom=dom,
        network=network,
        platform_api=platform_api,
        next_data=next_data,
        llm=llm,
    )
    structured = _apply_defaults(merged, url)
    structured["_field_sources"] = field_meta
    structured["_extraction_strategies"] = {
        "schema": bool(schema),
        "platform_api": bool(platform_api),
        "network": bool(network),
        "dom": bool(dom),
        "open_graph": bool(open_graph),
        "next_data": bool(next_data),
        "llm_gap": bool(llm),
        "second_pass": second_pass,
        "review_widgets": bool(dom_reviews),
    }

    extraction_confidence = score_extraction_confidence(
        structured,
        scrape_validation=scrape_validation,
        field_meta=field_meta,
    )
    structured["_extraction_confidence"] = extraction_confidence

    overall = extraction_confidence.get("overall_extraction_confidence") or 0
    missing_critical = _needs_retry(structured)
    if (overall < 0.5 or missing_critical) and not second_pass:
        logger.info(
            "extraction.second_pass_triggered",
            url=url,
            overall=overall,
            missing_critical=missing_critical,
        )
        return await run_extraction_pipeline(
            url=url,
            markdown=markdown,
            scrape_html=html,
            network_payloads=payloads,
            platform_info=platform_info,
            scrape_validation=scrape_validation,
            second_pass=True,
        )

    duration_ms = int((time.monotonic() - t0) * 1000)
    return {
        "json_structured_data": structured,
        "extraction_confidence": extraction_confidence,
        "extraction_meta": {
            "duration_ms": duration_ms,
            "platform": plat,
            "second_pass": second_pass,
            "field_meta": field_meta,
            "network_payload_count": len(payloads),
        },
    }
