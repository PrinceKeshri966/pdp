"""
app/agents/scraper_agent.py

ScraperAgent (Mode 1 – Node 1)
────────────────────────────────
Cloud-safe scrape chain with deterministic HTML technical metadata parsing.
"""
from __future__ import annotations

import os
import re
import time
from html import unescape

import httpx

from app.agents.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

_JINA_BASE = "https://r.jina.ai/"
_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1/scrape"
_JINA_THIN_THRESHOLD = 1500
_MIN_USABLE_CHARS = 200
_MAX_CONTENT_CHARS = 80_000
_MAX_SCRAPE_HTML_CHARS = 120_000
_HTTP_TIMEOUT = 45.0
_JINA_TIMEOUT = 60.0

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _playwright_enabled() -> bool:
    """Check if Playwright execution environment is unblocked."""
    return os.getenv("SKIP_PLAYWRIGHT", "true").lower() not in ("1", "true", "yes")


def _extract_dom_metadata(html: str) -> dict[str, str | bool | None]:
    """Parse raw structural HTML natively to secure absolute source code facts."""
    title_tag = None
    meta_desc = None
    canonical_present = False
    product_schema_present = False
    faq_schema_present = False
    og_present = False

    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.I)
    if title_match:
        title_tag = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
    if not title_tag:
        og_title = re.search(
            r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        if not og_title:
            og_title = re.search(
                r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
                html,
                re.I,
            )
        if og_title:
            title_tag = unescape(og_title.group(1)).strip()

    # Extract Meta Description via robust regex matching groups
    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']', html, re.I)
    if desc_match:
        meta_desc = unescape(desc_match.group(1)).strip()

    # Determine critical tags
    if re.search(r'<link[^>]*rel=["\']canonical["\']', html, re.I):
        canonical_present = True
    if re.search(r'<meta[^>]*property=["\']og:title["\']', html, re.I) or re.search(r'<meta[^>]*name=["\']og:title["\']', html, re.I):
        og_present = True

    # Scan Structured JSON-LD blocks (split closing tag so this .py file is safe inside HTML <script> blocks)
    _ld_close = "<" + "/script>"
    for script in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)' + _ld_close,
        html,
        re.I,
    ):
        try:
            content = script.group(1).lower()
            if '"@type"\s*:\s*["\']product["\']' in content or "'@type'\s*:\s*['\"]product['\"]" in content:
                product_schema_present = True
            if '"@type"\s*:\s*["\']faqpage["\']' in content or "'@type'\s*:\s*['\"]faqpage['\"]" in content:
                faq_schema_present = True
        except Exception:
            continue

    return {
        "title_tag": title_tag,
        "meta_description": meta_desc,
        "canonical_present": canonical_present,
        "product_schema_present": product_schema_present,
        "faq_schema_present": faq_schema_present,
        "open_graph_present": og_present,
    }


def _html_to_text(html: str) -> str:
    """Strip markup wrappers while preserving layout content streams."""
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_CONTENT_CHARS]


async def _fetch_with_firecrawl(
    url: str,
) -> tuple[str, dict[str, str | bool | None] | None, str]:
    """Execute target pull through Firecrawl engine interface."""
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
    """Pull remote resources using Jina processing endpoints."""
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
        
        # Secondary fallback request hook to capture raw header strings if Jina omits tags
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
    """Native raw resource pipeline execution bypass wrapper."""
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


async def _fetch_with_playwright(url: str) -> tuple[str, dict[str, str | bool | None], str]:
    """Local debugging viewport worker process instantiation router."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=_BROWSER_UA)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            try:
                await page.wait_for_selector("main, article, [data-product], .product", timeout=5000)
            except Exception:
                pass
            raw_html = await page.content()
            dom_meta = _extract_dom_metadata(raw_html)
            content = await page.evaluate("() => document.body.innerText")
            html_snip = raw_html[:_MAX_SCRAPE_HTML_CHARS] if raw_html else ""
            return content[:_MAX_CONTENT_CHARS], dom_meta, html_snip
        finally:
            await context.close()
            await browser.close()


async def _backfill_dom_metadata(
    url: str, dom_meta: dict[str, str | bool | None] | None
) -> dict[str, str | bool | None]:
    """Ensure title/meta/canonical come from raw HTML when markdown-only scrapers omit them."""
    meta = dict(dom_meta or {})
    if meta.get("title_tag") and meta.get("meta_description"):
        return meta
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            extracted = _extract_dom_metadata(resp.text)
            for key, val in extracted.items():
                if val is not None and val is not False and meta.get(key) in (None, False, ""):
                    meta[key] = val
    except Exception as exc:
        logger.warning("scraper_agent.dom_backfill_failed", url=url, error=str(exc))
    return meta


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
    """Coordinate multi-engine content recovery routines and bind true DOM parameters."""
    url = (state.get("url") or "").strip()
    if not url:
        state["errors"] = state.get("errors", []) + ["scraper_agent: no URL provided"]
        state["status"] = "failed"
        return state

    logger.info("scraper_agent.start", url=url, skip_playwright=not _playwright_enabled())
    t0 = time.monotonic()
    attempt_errors: list[str] = []
    content = ""
    method = "none"
    detected_dom_meta = None
    scrape_html = ""

    # 1 — Firecrawl Engine Execution
    if _settings.firecrawl_api_key:
        text, dom, html_snip, err = await _try_fetch("firecrawl", _fetch_with_firecrawl, url)
        if err:
            attempt_errors.append(err)
        if text:
            content, detected_dom_meta, scrape_html, method = text, dom, html_snip, "firecrawl"

    # 2 — Jina Parsing Pipeline Engine
    if len(content) < _JINA_THIN_THRESHOLD:
        text, dom, html_snip, err = await _try_fetch("jina", _fetch_with_jina, url)
        if err:
            attempt_errors.append(err)
        if text and len(text) > len(content):
            content, detected_dom_meta, scrape_html, method = text, dom, html_snip or scrape_html, "jina"

    # 3 — Fallback HTTPX Execution
    if len(content) < _JINA_THIN_THRESHOLD:
        text, dom, html_snip, err = await _try_fetch("httpx", _fetch_with_httpx, url)
        if err:
            attempt_errors.append(err)
        if text and len(text) > len(content):
            content, detected_dom_meta, scrape_html, method = text, dom, html_snip or scrape_html, "httpx"

    # 4 — Local Environment Playwright Context Router
    if _playwright_enabled() and len(content) < _JINA_THIN_THRESHOLD:
        text, dom, html_snip, err = await _try_fetch("playwright", _fetch_with_playwright, url)
        if err:
            attempt_errors.append(err)
        if text and len(text) > len(content):
            content, detected_dom_meta, scrape_html, method = text, dom, html_snip or scrape_html, "playwright"

    duration_ms = int((time.monotonic() - t0) * 1000)

    if len(content) < _MIN_USABLE_CHARS:
        summary = f"scraper_agent: fetch failure. Details: {' | '.join(attempt_errors[:3])}"
        state["errors"] = state.get("errors", []) + [summary]
        state["status"] = "failed"
        return state

    logger.info("scraper_agent.done", method=method, chars=len(content))

    detected_dom_meta = await _backfill_dom_metadata(url, detected_dom_meta)
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
    
    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "scraper_agent",
            "model": f"scraper/{method}",
            "input": {"url": url},
            "output_preview": content[:500],
            "output_chars": len(content),
            "scraper_method": method,
            "duration_ms": duration_ms,
            "fallback_errors": attempt_errors[:5],
        }
    ]
    return state