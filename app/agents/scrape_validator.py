"""
Validate scraped content before downstream analysis; optional enhanced retry.
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger
from app.core.demo_mode import is_demo_mode
from app.core.page_type_router import detect_page_type
from app.core.scrape_gate import evaluate_scrape_gate

logger = get_logger(__name__)

_MIN_WORDS_HIGH = 400
_MIN_WORDS_MEDIUM = 150
_MIN_WORDS_LOW = 50

_CAPTCHA = re.compile(
    r"(captcha|recaptcha|hcaptcha|verify you are human|access denied|"
    r"please enable javascript|attention required|bot detection|"
    r"cf-browser-verification|checking your browser|just a moment|"
    r"enable cookies to continue)",
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
    scraper_method: str = "",
    capture_confidence: float = 0.0,
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

    possible_bot_block = bool(
        _CAPTCHA.search(text)
        or "cf-browser-verification" in html
        or ("challenge-platform" in html and word_count < _MIN_WORDS_MEDIUM)
    )
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
    page_detection = detect_page_type(
        url=url,
        markdown=text,
        scrape_html=scrape_html,
        dom_technical_seo=dom,
    )
    detected_page_type = page_detection["page_type"]
    if detected_page_type == "pdp":
        detected_page_type_legacy = "product"
    else:
        detected_page_type_legacy = detected_page_type if detected_page_type != "unknown" else (
            "homepage" if _HOMEPAGE_SIGNAL.search(combined[:3000]) and not product_schema
            else ("product" if product_schema or (has_price and has_product_name) else "unknown")
        )

    if detected_page_type in ("homepage", "saas_landing", "blog"):
        if "pricing" in missing_sections and has_cta:
            missing_sections.remove("pricing")

    # Completeness 0-1
    checks = [has_title, has_product_name, word_count >= _MIN_WORDS_LOW, not possible_bot_block, not login_wall]
    if detected_page_type in ("pdp", "product", "marketplace"):
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

    if scraper_method.startswith("playwright") and scrape_quality != "low":
        confidence = min(0.98, confidence + 0.1)
        if capture_confidence > 0:
            confidence = round(min(0.98, (confidence + capture_confidence) / 2 + 0.05), 2)

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
        "detected_page_type": detected_page_type_legacy,
        "page_type": detected_page_type,
        "page_type_confidence": page_detection.get("confidence"),
        "page_type_reasons": page_detection.get("reasons", []),
        "usable_for_analysis": usable_for_analysis,
        "warnings": warnings,
        "word_count": word_count,
    }


async def enhanced_scrape_retry(state: AgentState) -> dict[str, Any] | None:
    """Browser-first retry, then Firecrawl/Jina fallbacks."""
    from app.agents.scraper_agent import (
        _fetch_with_firecrawl,
        _try_fetch,
    )
    from app.core.browser_capture.capture import browser_capture, browser_capture_enabled
    from app.core.config import get_settings

    url = (state.get("url") or "").strip()
    if not url:
        return None

    settings = get_settings()
    best_content = state.get("markdown_content") or ""
    best_html = state.get("scrape_html") or ""
    best_dom = state_dict(state, "dom_technical_seo")
    method = state.get("scraper_method") or "retry"
    best_network = state.get("network_payloads") or []
    best_platform = state.get("platform_info")
    best_browser_capture = state.get("browser_capture")
    best_visual = state.get("visual_ux_facts")
    best_capture_confidence = float(state.get("capture_confidence") or 0)

    if browser_capture_enabled():
        try:
            capture = await browser_capture(url)
            text = (capture.get("markdown_content") or "").strip()
            if text and len(text) > len(best_content):
                best_content = text
                best_dom = capture.get("dom_technical_seo") or best_dom
                best_html = capture.get("scrape_html") or best_html
                best_network = capture.get("network_payloads") or best_network
                best_platform = capture.get("platform_info") or best_platform
                best_browser_capture = capture.get("browser_capture")
                best_visual = capture.get("visual_ux_facts")
                best_capture_confidence = float(capture.get("capture_confidence") or 0)
                method = "playwright_browser_retry"
        except Exception:
            pass

    if settings.firecrawl_api_key and len(best_content) < 2500:
        text, dom, html_snip, err = await _try_fetch("firecrawl_retry", _fetch_with_firecrawl, url)
        if text and len(text) > len(best_content):
            best_content, best_dom, best_html, method = text, dom, html_snip, "firecrawl_retry"

    if len(best_content) < len(state.get("markdown_content") or ""):
        return None

    out: dict[str, Any] = {
        "markdown_content": best_content,
        "scrape_html": best_html,
        "dom_technical_seo": best_dom,
        "scraper_method": method,
    }
    if best_network:
        out["network_payloads"] = best_network
    if best_platform:
        out["platform_info"] = best_platform
    if best_browser_capture:
        out["browser_capture"] = best_browser_capture
    if best_visual:
        out["visual_ux_facts"] = best_visual
    if best_capture_confidence:
        out["capture_confidence"] = best_capture_confidence
    return out


async def scrape_quality_agent(state: AgentState) -> AgentState:
    """
    Validate scrape; hard-fail gate for invalid pages; optional retry before gate.
    """
    markdown = state.get("markdown_content") or ""
    if not markdown:
        gate = evaluate_scrape_gate(
            markdown="",
            scrape_html=state.get("scrape_html") or "",
            dom_technical_seo=state_dict(state, "dom_technical_seo"),
            url=state.get("url") or "",
        )
        return _hard_fail_state(state, gate or {
            "hard_fail": True,
            "code": "empty_content",
            "message": "The page returned no usable content for analysis.",
            "detail": "No markdown_content after scrape.",
            "url": state.get("url") or "",
            "recoverable": False,
            "agents_skipped": [],
        })

    t0 = time.monotonic()
    content = markdown
    scrape_html = state.get("scrape_html") or ""
    dom = state_dict(state, "dom_technical_seo")
    scraper_method = state.get("scraper_method") or ""
    capture_confidence = float(state.get("capture_confidence") or 0)
    retries = int(state.get("scrape_retry_count") or 0)
    retry_methods: list[str] = list(state.get("scrape_retry_methods") or [])

    validation = validate_scrape(
        markdown=content,
        scrape_html=scrape_html,
        dom_technical_seo=dom,
        url=state.get("url") or "",
        scraper_method=scraper_method,
        capture_confidence=capture_confidence,
    )

    max_retries = 0 if is_demo_mode() else 2
    if not validation["usable_for_analysis"] and retries < max_retries:
        logger.info("scrape_quality.retry", url=state.get("url"), attempt=retries + 1)
        retry_update = await enhanced_scrape_retry(state)
        if retry_update:
            retry_methods.append(retry_update.get("scraper_method", "retry"))
            content = retry_update["markdown_content"]
            scrape_html = retry_update.get("scrape_html") or scrape_html
            dom = retry_update.get("dom_technical_seo") or dom
            scraper_method = retry_update.get("scraper_method") or scraper_method
            capture_confidence = float(retry_update.get("capture_confidence") or capture_confidence)
            validation = validate_scrape(
                markdown=content,
                scrape_html=scrape_html,
                dom_technical_seo=dom,
                url=state.get("url") or "",
                scraper_method=scraper_method,
                capture_confidence=capture_confidence,
            )
            retries += 1

    gate = evaluate_scrape_gate(
        markdown=content,
        scrape_html=scrape_html,
        dom_technical_seo=dom,
        url=state.get("url") or "",
    )
    if gate:
        return _hard_fail_state(
            state,
            gate,
            markdown=content,
            scrape_html=scrape_html,
            dom=dom,
            scraper_method=scraper_method,
            validation=validation,
            retries=retries,
            retry_methods=retry_methods,
            t0=t0,
        )

    duration_ms = int((time.monotonic() - t0) * 1000)
    partial = not validation["usable_for_analysis"]
    if partial:
        validation["warnings"] = validation.get("warnings", []) + [
            "Partial audit only — page content may be incomplete. Do not treat scores as definitive."
        ]

    page_info = detect_page_type(
        url=state.get("url") or "",
        markdown=content,
        scrape_html=scrape_html,
        dom_technical_seo=dom,
    )
    if validation.get("page_type"):
        page_info["page_type"] = validation["page_type"]
        page_info["confidence"] = validation.get("page_type_confidence") or page_info["confidence"]
        page_info["reasons"] = validation.get("page_type_reasons") or page_info["reasons"]

    result: dict[str, Any] = {
        "scrape_validation": validation,
        "page_type_info": page_info,
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
    if retries:
        result.update({
            "markdown_content": content,
            "scrape_html": scrape_html,
            "dom_technical_seo": dom,
            "scraper_method": scraper_method,
            "scrape_retry_count": retries,
            "scrape_retry_methods": retry_methods,
        })
    return result


def _hard_fail_state(
    state: AgentState,
    gate: dict[str, Any],
    *,
    markdown: str = "",
    scrape_html: str = "",
    dom: dict[str, Any] | None = None,
    scraper_method: str = "",
    validation: dict[str, Any] | None = None,
    retries: int = 0,
    retry_methods: list[str] | None = None,
    t0: float | None = None,
) -> AgentState:
    """Build failed state — graph stops before extraction."""
    duration_ms = int((time.monotonic() - t0) * 1000) if t0 else 0
    validation = dict(validation or {})
    validation["hard_fail"] = gate
    validation["usable_for_analysis"] = False
    validation["scrape_quality"] = "blocked"
    validation["warnings"] = validation.get("warnings", []) + [gate["message"]]

    logger.warning(
        "scrape_gate.hard_fail",
        url=state.get("url"),
        code=gate.get("code"),
        detail=gate.get("detail"),
    )

    out: dict[str, Any] = {
        "status": "failed",
        "scrape_validation": validation,
        "partial_analysis": False,
        "errors": [f"scrape_gate:{gate['code']}: {gate['message']}"],
        "agent_reports": [
            {
                "agent": "scrape_gate",
                "model": "heuristic",
                "output": gate,
                "duration_ms": duration_ms,
            }
        ],
    }
    if markdown:
        out["markdown_content"] = markdown
    if scrape_html:
        out["scrape_html"] = scrape_html
    if dom:
        out["dom_technical_seo"] = dom
    if scraper_method:
        out["scraper_method"] = scraper_method
    if retries:
        out["scrape_retry_count"] = retries
        out["scrape_retry_methods"] = retry_methods or []
    return out
