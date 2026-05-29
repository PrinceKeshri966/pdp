"""
Playwright-first PDP fetch: hydration wait, scroll, XHR capture.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from app.core.html_metadata import (
    BROWSER_UA,
    MAX_CONTENT_CHARS,
    MAX_SCRAPE_HTML_CHARS,
    extract_dom_metadata,
    html_to_text,
)
from app.core.extraction.platform_detector import detect_platform
from app.core.page_type_router import _PDP_PATH

_PRODUCT_WAIT_SELECTORS = [
    "h1",
    "[itemprop='name']",
    "[data-product-title]",
    ".product-title",
    ".product__title",
    "[class*='product-name']",
    "button[name='add']",
    "[class*='add-to-cart']",
    "[class*='AddToCart']",
    "[data-testid*='add-to-cart']",
    ".price",
    "[itemprop='price']",
    "[class*='product-price']",
    "[class*='Price']",
    "[data-product-price]",
    "[class*='rating']",
    "[class*='review']",
    ".jdgm-widget",
    ".yotpo",
    ".loox-rating",
]

_REVIEW_TAB_SELECTORS = [
    "a[href*='review']",
    "button:has-text('Review')",
    "button:has-text('Reviews')",
    "[data-tab*='review']",
    "[aria-controls*='review']",
    ".jdgm-rev-widg__reviews-tab",
    ".yotpo-reviews-tab",
    "details:has-text('Review')",
    "summary:has-text('Review')",
]

_NETWORK_URL_HINTS = (
    "product", "graphql", "catalog", "item", "sku", "variant", "api",
    "yotpo", "judge.me", "loox", "stamped", "reviews", "rating",
    "wc/store", "wp-json", "magento", "shopify", ".js",
)


def url_looks_like_pdp(url: str) -> bool:
    path = urlparse(url or "").path
    return bool(_PDP_PATH.search(path or "/"))


def _playwright_enabled() -> bool:
    return os.getenv("SKIP_PLAYWRIGHT", "true").lower() not in ("1", "true", "yes")


async def _slow_scroll(page) -> None:
    try:
        height = await page.evaluate("() => document.body.scrollHeight")
        steps = min(12, max(4, height // 700))
        for i in range(steps):
            y = int((i + 1) * height / steps)
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(500)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def _trigger_lazy_load(page) -> None:
    """Hover product gallery / tabs to trigger lazy-loaded widgets."""
    lazy_selectors = [
        "[class*='gallery'] img",
        "[class*='thumbnail']",
        "[class*='accordion']",
        "[class*='tab']",
        ".product__media",
        "[data-product-image]",
    ]
    for sel in lazy_selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.hover(timeout=800)
                await page.wait_for_timeout(300)
        except Exception:
            continue


async def _open_review_sections(page) -> None:
    """Click review tabs/accordions so widgets hydrate and fire XHR."""
    for sel in _REVIEW_TAB_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(1200)
        except Exception:
            continue
    try:
        await page.evaluate(
            """() => {
                document.querySelectorAll('details').forEach(d => {
                    if (/review|rating/i.test(d.textContent || '')) d.open = true;
                });
            }"""
        )
        await page.wait_for_timeout(800)
    except Exception:
        pass


def _maybe_product_json(url: str, body_text: str) -> dict[str, Any] | None:
    if not body_text or len(body_text) > 500_000:
        return None
    low = url.lower()
    if not any(k in low for k in _NETWORK_URL_HINTS):
        if "application/json" not in low and not low.endswith(".json"):
            return None
    try:
        import json

        data = json.loads(body_text)
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return {"url": url, "body": data}
    return None


async def fetch_pdp_with_playwright(url: str, *, review_focus: bool = False) -> dict[str, Any]:
    """
    Returns markdown, html, dom_meta, network_payloads, platform_info, method label.
    """
    from playwright.async_api import async_playwright

    network_payloads: list[dict[str, Any]] = []
    network_urls: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_UA,
            viewport={"width": 1366, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )
        page = await context.new_page()

        async def on_response(response) -> None:
            try:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
                ct = (response.headers.get("content-type") or "").lower()
                rurl = response.url.lower()
                if "json" not in ct and not rurl.endswith(".json") and not any(h in rurl for h in _NETWORK_URL_HINTS):
                    return
                if not response.ok:
                    return
                network_urls.append(response.url)
                body_text = await response.text()
                parsed = _maybe_product_json(response.url, body_text)
                if parsed:
                    network_payloads.append(parsed)
            except Exception:
                pass

        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(3000 if not review_focus else 5000)
            for sel in _PRODUCT_WAIT_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=2000)
                except Exception:
                    continue
            await _trigger_lazy_load(page)
            await _slow_scroll(page)
            if review_focus:
                await _open_review_sections(page)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)
            else:
                await _open_review_sections(page)
            await page.wait_for_timeout(2000)
            raw_html = await page.content()
            inner_text = await page.evaluate("() => document.body?.innerText || ''")
        finally:
            await context.close()
            await browser.close()

    dom_meta = extract_dom_metadata(raw_html)
    platform_info = detect_platform(url=url, html=raw_html, network_urls=network_urls)
    markdown = (inner_text or html_to_text(raw_html))[:MAX_CONTENT_CHARS]
    html_snip = raw_html[:MAX_SCRAPE_HTML_CHARS] if raw_html else ""

    return {
        "markdown_content": markdown,
        "scrape_html": html_snip,
        "dom_technical_seo": dom_meta,
        "network_payloads": network_payloads[:60],
        "platform_info": platform_info,
        "scraper_method": "playwright_pdp",
    }
