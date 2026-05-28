"""
Validate scraped content before downstream analysis; optional enhanced retry.
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MIN_WORDS_HIGH = 400
_MIN_WORDS_MEDIUM = 150
_MIN_WORDS_LOW = 50

_CAPTCHA = re.compile(
    r"(captcha|recaptcha|hcaptcha|verify you are human|access denied|"
    r"please enable javascript|cloudflare|attention required|bot detection)",
    re.I,
)
_LOGIN_WALL = re.compile(
    r"(sign in to continue|log in to view|members only|create an account to)",
    re.I,
)
_PRICE = re.compile(
    r"(?:₹|rs\.?|inr|\$|€|£)\s*[\d,]+(?:\.\d{2})?|[\d,]+\s*(?:₹|rs|inr|usd)",
    re.I,
)
_CTA = re.compile(
    r"\b(add to cart|buy now|shop now|get started|add to bag|order now)\b",
    re.I,
)
_PRODUCT_JSON = re.compile(r'"@type"\s*:\s*["\']Product["\']', re.I)
_HOMEPAGE_SIGNAL = re.compile(
    r"\b(home|welcome|shop all|collections|our story|featured products)\b",
    re.I,
)
_BOILERPLATE_REPEAT = re.compile(
    r"(copyright|all rights reserved|privacy policy|terms of service|cookie policy)",
    re.I,
)


def validate_scrape(
    *,
    markdown: str,
    scrape_html: str = "",
    dom_technical_seo: dict[str, Any] | None = None,
    url: str = "",
) -> dict[str, Any]:
    """Return scrape quality assessment (no LLM)."""
    dom = dom_technical_seo or {}
    text = (markdown or "").strip()
    html = (scrape_html or "").lower()
    combined = f"{text}\n{html}".lower()
    words = text.split()
    word_count = len(words)

    warnings: list[str] = []
    missing_sections: list[str] = []

    possible_bot_block = bool(_CAPTCHA.search(combined) or "cf-browser-verification" in html)
    login_wall = bool(_LOGIN_WALL.search(combined))
    is_js_heavy = bool(
        re.search(r"__NEXT_DATA__|reactroot|ng-version|data-reactroot|shopify", html)
        or (word_count < 200 and len(html) > 5000)
    )

    has_title = bool(dom.get("title_tag") or re.search(r"^#\s+\S", text, re.M))
    has_price = bool(_PRICE.search(text))
    has_cta = bool(_CTA.search(text))
    has_product_name = bool(
        dom.get("title_tag")
        or re.search(r"^#\s+(.+)$", text, re.M)
        or _PRODUCT_JSON.search(html)
    )

    if not has_product_name:
        missing_sections.append("product_name")
    if not has_price:
        missing_sections.append("pricing")
    if not has_cta:
        missing_sections.append("cta")

    boilerplate_hits = len(_BOILERPLATE_REPEAT.findall(combined))
    nav_only_risk = word_count < 120 and boilerplate_hits >= 2

    if possible_bot_block:
        warnings.append("Possible bot protection or CAPTCHA detected")
    if login_wall:
        warnings.append("Login wall may be blocking full page content")
    if nav_only_risk:
        warnings.append("Content looks like navigation/footer boilerplate only")
    if is_js_heavy and word_count < _MIN_WORDS_MEDIUM:
        warnings.append("Heavy JavaScript site with thin extracted text")

    product_schema = bool(dom.get("product_schema_present")) or bool(_PRODUCT_JSON.search(html))
    if _HOMEPAGE_SIGNAL.search(combined[:3000]) and not product_schema:
        detected_page_type = "homepage"
    elif product_schema or (has_price and has_product_name):
        detected_page_type = "product"
    else:
        detected_page_type = "unknown"

    if detected_page_type == "homepage":
        if "pricing" in missing_sections and has_cta:
            missing_sections.remove("pricing")

    # Completeness 0-1
    checks = [has_title, has_product_name, word_count >= _MIN_WORDS_LOW, not possible_bot_block, not login_wall]
    if detected_page_type == "product":
        checks.extend([has_price or has_cta])
    content_completeness_score = round(sum(1 for c in checks if c) / max(len(checks), 1), 2)

    if possible_bot_block or login_wall:
        scrape_quality = "low"
        confidence = 0.25
    elif word_count >= _MIN_WORDS_HIGH and content_completeness_score >= 0.75:
        scrape_quality = "high"
        confidence = 0.9
    elif word_count >= _MIN_WORDS_MEDIUM and content_completeness_score >= 0.55:
        scrape_quality = "medium"
        confidence = 0.65
    else:
        scrape_quality = "low"
        confidence = max(0.2, content_completeness_score * 0.5)

    usable_for_analysis = (
        not possible_bot_block
        and not login_wall
        and word_count >= _MIN_WORDS_LOW
        and content_completeness_score >= 0.4
    )

    return {
        "scrape_quality": scrape_quality,
        "confidence": round(confidence, 2),
        "is_js_heavy": is_js_heavy,
        "possible_bot_block": possible_bot_block,
        "content_completeness_score": content_completeness_score,
        "missing_sections": missing_sections,
        "detected_page_type": detected_page_type,
        "usable_for_analysis": usable_for_analysis,
        "warnings": warnings,
        "word_count": word_count,
    }


async def enhanced_scrape_retry(state: AgentState) -> dict[str, Any] | None:
    """Try Playwright then Firecrawl when validation failed."""
    from app.agents.scraper_agent import (
        _backfill_dom_metadata,
        _fetch_with_firecrawl,
        _fetch_with_jina,
        _fetch_with_playwright,
        _playwright_enabled,
        _try_fetch,
    )
    from app.core.config import get_settings

    url = (state.get("url") or "").strip()
    if not url:
        return None

    settings = get_settings()
    best_content = state.get("markdown_content") or ""
    best_html = state.get("scrape_html") or ""
    best_dom = state_dict(state, "dom_technical_seo")
    method = state.get("scraper_method") or "retry"

    if _playwright_enabled():
        text, dom, html_snip, err = await _try_fetch("playwright_retry", _fetch_with_playwright, url)
        if text and len(text) > len(best_content):
            best_content, best_dom, best_html, method = text, dom, html_snip, "playwright_retry"

    if settings.firecrawl_api_key and len(best_content) < 2500:
        text, dom, html_snip, err = await _try_fetch("firecrawl_retry", _fetch_with_firecrawl, url)
        if text and len(text) > len(best_content):
            best_content, best_dom, best_html, method = text, dom, html_snip, "firecrawl_retry"

    if len(best_content) < len(state.get("markdown_content") or ""):
        return None

    best_dom = await _backfill_dom_metadata(url, best_dom)
    return {
        "markdown_content": best_content,
        "scrape_html": best_html,
        "dom_technical_seo": best_dom,
        "scraper_method": method,
    }


async def scrape_quality_agent(state: AgentState) -> AgentState:
    """
    Validate scrape; retry with enhanced methods if unusable.
    Sets scrape_validation and partial_analysis flags on state.
    """
    markdown = state.get("markdown_content") or ""
    if not markdown:
        return {"errors": ["scrape_quality: no markdown_content"]}

    t0 = time.monotonic()
    validation = validate_scrape(
        markdown=markdown,
        scrape_html=state.get("scrape_html") or "",
        dom_technical_seo=state_dict(state, "dom_technical_seo"),
        url=state.get("url") or "",
    )
    retries = int(state.get("scrape_retry_count") or 0)
    retry_methods: list[str] = []

    if not validation["usable_for_analysis"] and retries < 2:
        logger.info("scrape_quality.retry", url=state.get("url"), attempt=retries + 1)
        retry_update = await enhanced_scrape_retry(state)
        if retry_update:
            retry_methods.append(retry_update.get("scraper_method", "retry"))
            validation = validate_scrape(
                markdown=retry_update["markdown_content"],
                scrape_html=retry_update.get("scrape_html") or "",
                dom_technical_seo=retry_update.get("dom_technical_seo"),
                url=state.get("url") or "",
            )
            out: dict[str, Any] = {
                **retry_update,
                "scrape_validation": validation,
                "scrape_retry_count": retries + 1,
                "scrape_retry_methods": (state.get("scrape_retry_methods") or []) + retry_methods,
            }
            if not validation["usable_for_analysis"]:
                out["partial_analysis"] = True
                validation["warnings"] = validation.get("warnings", []) + [
                    "Partial audit: scrape quality is low after retries. Scores are conservative."
                ]
            return out

    partial = not validation["usable_for_analysis"]
    if partial:
        validation["warnings"] = validation.get("warnings", []) + [
            "Partial audit only — page content may be incomplete. Do not treat scores as definitive."
        ]

    duration_ms = int((time.monotonic() - t0) * 1000)
    return {
        "scrape_validation": validation,
        "partial_analysis": partial,
        "agent_reports": [
            {
                "agent": "scrape_quality",
                "model": "heuristic",
                "output": validation,
                "duration_ms": duration_ms,
            }
        ],
    }
