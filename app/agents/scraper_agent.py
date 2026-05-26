"""
app/agents/scraper_agent.py

ScraperAgent  (Mode 1 – Node 1)
────────────────────────────────
Hybrid scraper: tries Jina Reader first (fast, free).
Falls back to Playwright if Jina returns thin content (< 800 chars)
or raises an HTTP error — handles JS-heavy / Shopify storefronts.

LangGraph signature:  async (state: AgentState) -> AgentState
"""
from __future__ import annotations

import time

import httpx
from playwright.async_api import async_playwright

from app.agents.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

_JINA_BASE = "https://r.jina.ai/"
_JINA_THIN_THRESHOLD = 800   # chars — below this we consider Jina output insufficient


# ── Jina Reader ───────────────────────────────────────────────────────────────
async def _fetch_with_jina(url: str) -> str:
    jina_url = f"{_JINA_BASE}{url}"
    headers: dict[str, str] = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
    }
    if _settings.jina_api_key:
        headers["Authorization"] = f"Bearer {_settings.jina_api_key}"

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(jina_url, headers=headers)
        resp.raise_for_status()
        return resp.text


# ── Playwright fallback ───────────────────────────────────────────────────────
async def _fetch_with_playwright(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        try:
            # domcontentloaded is safer than networkidle on e-commerce sites
            # (analytics pixels / chat widgets keep network busy indefinitely)
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)

            # Give JS a moment to render product content
            try:
                await page.wait_for_selector(
                    "main, article, [data-product], .product-detail, .product",
                    timeout=5000,
                )
            except Exception:
                pass  # selector not found — still grab whatever rendered

            content: str = await page.evaluate("""() => {
                const el = (
                    document.querySelector('main') ||
                    document.querySelector('article') ||
                    document.querySelector('[data-product]') ||
                    document.querySelector('.product') ||
                    document.body
                );
                return el.innerText;
            }""")
            return content
        finally:
            # CRITICAL: always release browser resources
            await context.close()
            await browser.close()


# ── LangGraph node ────────────────────────────────────────────────────────────
async def scraper_agent(state: AgentState) -> AgentState:
    """
    Hybrid scrape: Jina first → Playwright fallback.
    Writes markdown_content + scraper_method into state.
    """
    url = state.get("url", "")
    if not url:
        state["errors"] = state.get("errors", []) + ["scraper_agent: no URL provided"]
        state["status"] = "failed"
        return state

    logger.info("scraper_agent.start", url=url)
    t0 = time.monotonic()
    method = "jina"

    try:
        content = await _fetch_with_jina(url)

        if len(content) < _JINA_THIN_THRESHOLD:
            logger.warning(
                "scraper_agent.jina_thin_content",
                chars=len(content),
                threshold=_JINA_THIN_THRESHOLD,
            )
            try:
                content = await _fetch_with_playwright(url)
                method = "playwright"
            except Exception as pw_exc:
                # Render/Docker often has no Playwright browsers — keep Jina output
                logger.warning(
                    "scraper_agent.playwright_skip_thin",
                    error=str(pw_exc),
                    fallback_chars=len(content),
                )

    except httpx.HTTPError as exc:
        logger.warning("scraper_agent.jina_failed", error=str(exc))
        try:
            content = await _fetch_with_playwright(url)
            method = "playwright"
        except Exception as pw_exc:
            err = f"scraper_agent: both Jina and Playwright failed – {pw_exc}"
            logger.error("scraper_agent.playwright_failed", error=err)
            state["errors"] = state.get("errors", []) + [err]
            state["status"] = "failed"
            return state

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info("scraper_agent.done", method=method, chars=len(content), duration_ms=duration_ms)

    state["markdown_content"] = content
    state["scraper_method"] = method
    state["agent_reports"] = state.get("agent_reports", []) + [
        {
            "agent": "scraper_agent",
            "model": f"jina-reader+playwright/{method}",
            "input": {"url": url},
            "output_preview": content[:500],
            "output_chars": len(content),
            "scraper_method": method,
            "duration_ms": duration_ms,
        }
    ]
    return state
