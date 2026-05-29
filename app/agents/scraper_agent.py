"""
app/agents/scraper_agent.py

Browser-first scrape chain: Playwright primary, Jina/Firecrawl/HTTP as fallbacks only.
"""
from __future__ import annotations

import time

import httpx

from app.agents.state import AgentState
from app.core.browser_capture.capture import browser_capture, browser_capture_enabled
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.playwright_env import playwright_enabled

logger = get_logger(__name__)
_settings = get_settings()

_JINA_BASE = "https://r.jina.ai/"
_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1/scrape"
_MIN_USABLE_CHARS = 200
_MAX_CONTENT_CHARS = 80_000
_MAX_SCRAPE_HTML_CHARS = 120_000
_HTTP_TIMEOUT = 45.0
_JINA_TIMEOUT = 60.0

from app.core.html_metadata import BROWSER_UA, extract_dom_metadata, html_to_text

_BROWSER_UA = BROWSER_UA


def _extract_dom_metadata(html: str) -> dict[str, str | bool | None]:
    return extract_dom_metadata(html)


def _html_to_text(html: str) -> str:
    return html_to_text(html)


async def _fetch_with_firecrawl(
    url: str,
) -> tuple[str, dict[str, str | bool | None] | None, str]:
    """Fallback: Firecrawl markdown scrape."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _FIRECRAWL_BASE,
            headers={"Authorization": f"Bearer {_settings.firecrawl_api_key}"},
            json={"url": url, "formats": ["markdown", "html"], "onlyMainContent": False},
        )
        resp.raise_for_status()
        res_data = resp.json().get("data") or {}
        raw_html = res_data.get("html", "") or ""
        dom_meta = _extract_dom_metadata(raw_html) if raw_html else None
        html_snip = raw_html[:_MAX_SCRAPE_HTML_CHARS] if raw_html else ""
        return res_data.get("markdown", ""), dom_meta, html_snip


async def _fetch_with_jina(url: str) -> tuple[str, dict[str, str | bool | None] | None, str]:
    """Fallback: Jina Reader markdown scrape."""
    jina_url = f"{_JINA_BASE}{url}"
    headers: dict[str, str] = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": _BROWSER_UA,
    }
    if _settings.jina_api_key:
        headers["Authorization"] = f"Bearer {_settings.jina_api_key}"

    async with httpx.AsyncClient(timeout=_JINA_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(jina_url, headers=headers)
        resp.raise_for_status()
        dom_meta = None
        html_snip = ""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as head_client:
                h_resp = await head_client.get(url, headers={"User-Agent": _BROWSER_UA})
                if h_resp.ok:
                    dom_meta = _extract_dom_metadata(h_resp.text)
                    html_snip = h_resp.text[:_MAX_SCRAPE_HTML_CHARS]
        except Exception:
            pass
        return resp.text.strip(), dom_meta, html_snip


async def _fetch_with_httpx(url: str) -> tuple[str, dict[str, str | bool | None], str]:
    """Fallback: direct HTTP fetch."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.text
        dom_meta = _extract_dom_metadata(body)
        html_snip = body[:_MAX_SCRAPE_HTML_CHARS] if body else ""
        if len(body) > 500 and ("<html" in body.lower() or "<body" in body.lower()):
            return _html_to_text(body), dom_meta, html_snip
        return body.strip()[:_MAX_CONTENT_CHARS], dom_meta, html_snip


async def _try_fetch(
    label: str, fetcher, url: str
) -> tuple[str | None, dict[str, str | bool | None] | None, str, str | None]:
    try:
        text, dom_meta, html_snip = await fetcher(url)
        if text and len(text.strip()) >= _MIN_USABLE_CHARS:
            return text.strip(), dom_meta, html_snip or "", None
        return None, None, "", f"{label}: content too short"
    except Exception as exc:
        return None, None, "", f"{label}: {exc}"


async def scraper_agent(state: AgentState) -> AgentState:
    """
    Browser-first scraper: Playwright unified capture is primary.
    Jina → Firecrawl → HTTP only when browser unavailable or fails.
    """
    url = (state.get("url") or "").strip()
    if not url:
        state["errors"] = state.get("errors", []) + ["scraper_agent: no URL provided"]
        state["status"] = "failed"
        return state

    logger.info("scraper_agent.start", url=url, browser_first=browser_capture_enabled())
    t0 = time.monotonic()
    attempt_errors: list[str] = []
    content = ""
    method = "none"
    detected_dom_meta = None
    scrape_html = ""
    network_payloads: list = []
    platform_info: dict | None = None
    browser_capture_data: dict | None = None
    visual_ux_facts: dict | None = None
    capture_confidence = 0.0

    # ── 1. PRIMARY: Unified browser capture (Playwright) ─────────────────────
    if browser_capture_enabled():
        try:
            capture = await browser_capture(url)
            text = (capture.get("markdown_content") or "").strip()
            if text and len(text) >= _MIN_USABLE_CHARS:
                content = text
                detected_dom_meta = capture.get("dom_technical_seo")
                scrape_html = capture.get("scrape_html") or ""
                network_payloads = capture.get("network_payloads") or []
                platform_info = capture.get("platform_info")
                browser_capture_data = capture.get("browser_capture")
                visual_ux_facts = capture.get("visual_ux_facts")
                capture_confidence = capture.get("capture_confidence") or 0.0
                method = capture.get("scraper_method") or "playwright_browser"
                logger.info(
                    "scraper_agent.browser_capture_ok",
                    chars=len(content),
                    network_apis=len(network_payloads),
                    confidence=capture_confidence,
                )
        except Exception as exc:
            attempt_errors.append(f"playwright_browser: {exc}")
            logger.warning("scraper_agent.browser_capture_failed", error=str(exc))

    # ── 2. FALLBACK CHAIN (only if browser failed or disabled) ───────────────
    if len(content) < _MIN_USABLE_CHARS:
        if _settings.firecrawl_api_key:
            text, dom, html_snip, err = await _try_fetch("firecrawl", _fetch_with_firecrawl, url)
            if err:
                attempt_errors.append(err)
            if text:
                content, detected_dom_meta, scrape_html, method = text, dom, html_snip, "firecrawl"

        if len(content) < _MIN_USABLE_CHARS:
            text, dom, html_snip, err = await _try_fetch("jina", _fetch_with_jina, url)
            if err:
                attempt_errors.append(err)
            if text:
                content, detected_dom_meta, scrape_html, method = text, dom, html_snip or scrape_html, "jina"

        if len(content) < _MIN_USABLE_CHARS:
            text, dom, html_snip, err = await _try_fetch("httpx", _fetch_with_httpx, url)
            if err:
                attempt_errors.append(err)
            if text:
                content, detected_dom_meta, scrape_html, method = text, dom, html_snip or scrape_html, "httpx"

    duration_ms = int((time.monotonic() - t0) * 1000)

    if len(content) < _MIN_USABLE_CHARS:
        summary = f"scraper_agent: all scrapers failed. Details: {' | '.join(attempt_errors[:3])}"
        state["errors"] = state.get("errors", []) + [summary]
        state["status"] = "failed"
        return state

    logger.info("scraper_agent.done", method=method, chars=len(content), browser_first=method.startswith("playwright"))

    if not detected_dom_meta:
        detected_dom_meta = {
            "title_tag": None,
            "meta_description": None,
            "canonical_present": False,
            "product_schema_present": False,
            "faq_schema_present": False,
            "open_graph_present": False,
        }

    state["markdown_content"] = content
    state["scraper_method"] = method
    state["dom_technical_seo"] = detected_dom_meta
    state["scrape_html"] = scrape_html
    if network_payloads:
        state["network_payloads"] = network_payloads
    if platform_info:
        state["platform_info"] = platform_info
    if browser_capture_data:
        state["browser_capture"] = browser_capture_data
    if visual_ux_facts:
        state["visual_ux_facts"] = visual_ux_facts
    if capture_confidence:
        state["capture_confidence"] = capture_confidence

    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "scraper_agent",
            "model": f"scraper/{method}",
            "input": {"url": url, "browser_first": method.startswith("playwright")},
            "output_preview": content[:500],
            "output_chars": len(content),
            "scraper_method": method,
            "network_apis_captured": len(network_payloads),
            "capture_confidence": capture_confidence,
            "duration_ms": duration_ms,
            "fallback_errors": attempt_errors[:5],
        }
    ]
    return state
