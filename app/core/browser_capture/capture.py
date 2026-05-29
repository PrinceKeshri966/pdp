"""
Unified browser-first capture — single Playwright session for all audit artifacts.

Replaces fragmented Playwright launches (scraper, visual_ux, screenshot, extraction retry)
with one comprehensive capture pass.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from app.core.browser_capture.dom_seo import extract_dom_seo_facts
from app.core.browser_capture.lighthouse import run_lighthouse_audit
from app.core.browser_capture.schema_validator import validate_schema_markup
from app.core.browser_capture.technical_crawl import crawl_technical_seo
from app.core.browser_capture.vision_ux import analyze_screenshot_ux
from app.core.extraction.platform_detector import detect_platform
from app.core.html_metadata import (
    BROWSER_UA,
    MAX_CONTENT_CHARS,
    MAX_SCRAPE_HTML_CHARS,
    extract_dom_metadata,
    html_to_text,
)
from app.core.logging import get_logger
from app.core.playwright_env import playwright_enabled

logger = get_logger(__name__)

_VIEWPORTS = {
    "desktop": {"width": 1366, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

_PRODUCT_WAIT_SELECTORS = [
    "h1", "[itemprop='name']", "[data-product-title]", ".product-title",
    ".product__title", "button[name='add']", "[class*='add-to-cart']",
    ".price", "[itemprop='price']", "[class*='product-price']",
    "[class*='rating']", "[class*='review']", ".jdgm-widget", ".yotpo",
]

_REVIEW_TAB_SELECTORS = [
    "a[href*='review']", "button:has-text('Review')", "button:has-text('Reviews')",
    "[data-tab*='review']", ".jdgm-rev-widg__reviews-tab", ".yotpo-reviews-tab",
    ".stamped-tab-reviews", "[data-tab='reviews']", "#stamped-main-widget",
    "[data-oke-reviews-widget]", ".okeReviews-reviewsTab",
]

_NETWORK_URL_HINTS = (
    "product", "graphql", "catalog", "item", "sku", "variant", "api",
    "inventory", "stock", "pricing", "price", "yotpo", "judge.me", "loox",
    "stamped", "okendo", "oke-reviews", "reviews", "rating", "wc/store", "wp-json", "magento", "shopify", ".js",
)

_ELEMENT_BOUNDS_JS = """async () => {
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    function visibleRect(el) {
        if (!el || el.nodeType !== 1) return null;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return null;
        const st = getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) return null;
        return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width),
                 height: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) };
    }
    function smallestMatch(selector, testFn) {
        let best = null, bestArea = Infinity;
        for (const el of document.querySelectorAll(selector)) {
            if (testFn && !testFn(el)) continue;
            const r = visibleRect(el);
            if (!r) continue;
            const area = r.width * r.height;
            if (area < bestArea) { best = el; bestArea = area; }
        }
        return best;
    }
    const h1El = smallestMatch('h1', el => !!(el.innerText || '').trim());
    const ctaRe = /add to cart|buy now|shop now|get started|order now/i;
    const ctaEl = smallestMatch('button, a[role=button], a.btn, [class*="cta"], input[type=submit]',
        el => ctaRe.test((el.innerText || el.value || el.getAttribute('aria-label') || '').trim()));
    const trustRe = /secure|guarantee|verified|ssl|free shipping|money back|★|rating|review/i;
    const trustEl = smallestMatch('*', el => {
        if (['SCRIPT','STYLE','SVG','PATH'].includes(el.tagName)) return false;
        return trustRe.test((el.innerText || '').slice(0, 120)) && el.children.length <= 3;
    });
    const faqEl = smallestMatch('[class*="faq"], details, [itemtype*="FAQPage"]', el => !!(el.innerText || '').trim());
    const priceRe = /₹|\\$|€|£|\\d+[.,]\\d{2}/i;
    const pricingEl = smallestMatch('[class*="price"], [itemprop="price"], [data-price]',
        el => priceRe.test((el.innerText || '').slice(0, 80)));
    let ctaAbove = false, sticky = false;
    for (const el of document.querySelectorAll('button, a[role=button], .btn, [class*="cta"]')) {
        const t = (el.innerText || '').trim();
        if (!ctaRe.test(t)) continue;
        const r = el.getBoundingClientRect();
        if (r.top < vh && r.bottom > 0) ctaAbove = true;
        const st = getComputedStyle(el);
        if ((st.position === 'fixed' || st.position === 'sticky') && r.width > 40) sticky = true;
    }
    return {
        ctaAbove, sticky,
        trustVisible: !!trustEl && trustEl.getBoundingClientRect().top < vh * 1.5,
        hero: !!h1El,
        textLen: (document.body?.innerText || '').length,
        element_bounds: {
            h1: visibleRect(h1El), cta: visibleRect(ctaEl),
            trust: visibleRect(trustEl), faq: visibleRect(faqEl), pricing: visibleRect(pricingEl),
        },
        viewport_width: vw, viewport_height: vh,
    };
}"""


def browser_capture_enabled() -> bool:
    return playwright_enabled()


def _maybe_product_json(url: str, body_text: str) -> dict[str, Any] | None:
    if not body_text or len(body_text) > 500_000:
        return None
    low = url.lower()
    if not any(k in low for k in _NETWORK_URL_HINTS):
        if "application/json" not in low and not low.endswith(".json"):
            return None
    try:
        data = json.loads(body_text)
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return {"url": url, "body": data, "category": _categorize_api_url(url)}
    return None


def _categorize_api_url(url: str) -> str:
    low = url.lower()
    if any(k in low for k in ("review", "rating", "yotpo", "judge.me", "loox", "stamped", "okendo", "oke-reviews")):
        return "reviews"
    if any(k in low for k in ("variant", "sku", "option")):
        return "variants"
    if any(k in low for k in ("inventory", "stock", "availability")):
        return "inventory"
    if any(k in low for k in ("price", "pricing", "offer")):
        return "pricing"
    if any(k in low for k in ("product", "catalog", "item", "graphql")):
        return "product"
    return "other"


async def _slow_scroll(page) -> None:
    try:
        height = await page.evaluate("() => document.body.scrollHeight")
        steps = min(12, max(4, height // 700))
        for i in range(steps):
            y = int((i + 1) * height / steps)
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(400)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(600)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def _open_review_sections(page) -> None:
    for sel in _REVIEW_TAB_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=1500)
                await page.wait_for_timeout(1000)
        except Exception:
            continue


async def browser_capture(
    url: str,
    *,
    include_vision: bool = True,
    include_lighthouse: bool = True,
    include_technical_crawl: bool = True,
) -> dict[str, Any]:
    """
    Primary browser-first capture. Returns all artifacts needed by downstream agents.
    """
    from playwright.async_api import async_playwright

    network_payloads: list[dict[str, Any]] = []
    network_urls: list[str] = []
    redirect_chain: list[str] = [url]
    final_url = url
    raw_html = ""
    inner_text = ""
    desktop_page = None
    screenshots: dict[str, str] = {}
    visual_facts: dict[str, Any] = {}
    mobile_quality = "average"
    lighthouse_result: dict[str, Any] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_UA,
            viewport=_VIEWPORTS["desktop"],
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
                rurl = response.url
                rurl_low = rurl.lower()
                if "json" not in ct and not rurl_low.endswith(".json") and not any(h in rurl_low for h in _NETWORK_URL_HINTS):
                    return
                if not response.ok:
                    return
                network_urls.append(rurl)
                body_text = await response.text()
                parsed = _maybe_product_json(rurl, body_text)
                if parsed:
                    network_payloads.append(parsed)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if resp:
                final_url = resp.url
                redirect_chain = [url]
                if final_url != url:
                    redirect_chain.append(final_url)

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(2500)

            for sel in _PRODUCT_WAIT_SELECTORS:
                try:
                    await page.wait_for_selector(sel, timeout=1500)
                except Exception:
                    continue

            await _slow_scroll(page)
            await _open_review_sections(page)
            await page.wait_for_timeout(1500)

            raw_html = await page.content()
            inner_text = await page.evaluate("() => document.body?.innerText || ''")
            desktop_page = page

            eval_result = await page.evaluate(_ELEMENT_BOUNDS_JS)
            visual_facts = {
                "cta_above_fold": bool(eval_result.get("ctaAbove")),
                "sticky_cta_detected": bool(eval_result.get("sticky")),
                "trust_badges_visible": bool(eval_result.get("trustVisible")),
                "hero_section_detected": bool(eval_result.get("hero")),
                "element_bounds": eval_result.get("element_bounds") or {},
                "viewport_width": eval_result.get("viewport_width") or 1366,
                "viewport_height": eval_result.get("viewport_height") or 900,
                "capture_ok": True,
                "warnings": [],
            }

            try:
                png = await page.screenshot(full_page=False, type="png")
                screenshots["desktop"] = base64.b64encode(png).decode("ascii")
                visual_facts["screenshot_base64"] = screenshots["desktop"]
            except Exception as exc:
                visual_facts.setdefault("warnings", []).append(f"Desktop screenshot failed: {exc}")

            # Mobile viewport pass (same browser, new context)
            mobile_ctx = await browser.new_context(viewport=_VIEWPORTS["mobile"], user_agent=BROWSER_UA)
            mobile_page = await mobile_ctx.new_page()
            try:
                await mobile_page.goto(final_url or url, wait_until="domcontentloaded", timeout=30000)
                await mobile_page.wait_for_timeout(1200)
                mobile_eval = await mobile_page.evaluate(
                    "() => ({ overflow: document.documentElement.scrollWidth > window.innerWidth + 20, textLen: (document.body?.innerText || '').length })"
                )
                if mobile_eval.get("overflow"):
                    mobile_quality = "poor"
                elif (mobile_eval.get("textLen") or 0) > 500:
                    mobile_quality = "good"
                try:
                    mob_png = await mobile_page.screenshot(full_page=False, type="png")
                    screenshots["mobile"] = base64.b64encode(mob_png).decode("ascii")
                except Exception:
                    pass
            finally:
                await mobile_ctx.close()

            visual_facts["mobile_layout_quality"] = mobile_quality

            # Lighthouse/CDP metrics must run before browser closes
            if include_lighthouse and desktop_page:
                lighthouse_result = await run_lighthouse_audit(final_url or url, raw_html, page=desktop_page)

        finally:
            await context.close()
            await browser.close()

    dom_meta = extract_dom_metadata(raw_html)
    dom_seo = extract_dom_seo_facts(raw_html, url=final_url or url)
    platform_info = detect_platform(url=url, html=raw_html, network_urls=network_urls)
    markdown = (inner_text or html_to_text(raw_html))[:MAX_CONTENT_CHARS]
    html_snip = raw_html[:MAX_SCRAPE_HTML_CHARS] if raw_html else ""

    schema_validation = validate_schema_markup(raw_html)
    technical_crawl_result: dict[str, Any] = {}
    vision_result: dict[str, Any] = {}

    if include_technical_crawl:
        technical_crawl_result = await crawl_technical_seo(
            url, raw_html, redirect_chain=redirect_chain, final_url=final_url
        )

    if include_vision and screenshots.get("desktop"):
        vision_result = await analyze_screenshot_ux(screenshots["desktop"], url=final_url or url)
        if vision_result.get("available"):
            visual_facts["vision_analysis"] = vision_result

    # Enrich dom_technical_seo from DOM SEO + schema + technical crawl
    enriched_dom = {
        **dom_meta,
        "dom_seo_source": "rendered_dom",
        "schema_types": schema_validation.get("detected_types", []),
        "twitter_card_present": bool(technical_crawl_result.get("twitter_cards", {}).get("present")),
        "hreflang_present": bool(technical_crawl_result.get("hreflang", {}).get("present")),
        "canonical_url": (technical_crawl_result.get("canonical") or {}).get("urls", [None])[0],
    }

    # Categorize network payloads
    api_summary = {}
    for p in network_payloads:
        cat = p.get("category", "other")
        api_summary.setdefault(cat, []).append(p["url"])

    browser_artifacts = {
        "dom_seo": dom_seo,
        "schema_validation": schema_validation,
        "lighthouse": lighthouse_result,
        "technical_crawl": technical_crawl_result,
        "screenshots": {k: f"[base64:{len(v)} chars]" for k, v in screenshots.items()},
        "network_api_summary": api_summary,
        "redirect_chain": redirect_chain,
        "final_url": final_url,
    }

    return {
        "markdown_content": markdown,
        "scrape_html": html_snip,
        "dom_technical_seo": enriched_dom,
        "network_payloads": network_payloads[:80],
        "platform_info": platform_info,
        "scraper_method": "playwright_browser",
        "browser_capture": browser_artifacts,
        "visual_ux_facts": visual_facts,
        "screenshots_base64": screenshots,
        "capture_confidence": _compute_capture_confidence(
            markdown, network_payloads, raw_html, schema_validation, lighthouse_result
        ),
    }


def _compute_capture_confidence(
    markdown: str,
    network: list,
    html: str,
    schema: dict,
    lighthouse: dict,
) -> float:
    score = 0.5
    if len(markdown) > 500:
        score += 0.15
    if len(html) > 2000:
        score += 0.1
    if network:
        score += 0.1
    if schema.get("detected_types"):
        score += 0.05
    if lighthouse.get("available"):
        score += 0.1
    return round(min(1.0, score), 2)


async def browser_capture_light(url: str) -> dict[str, Any]:
    """Lightweight browser capture for competitor URLs (no vision/lighthouse)."""
    return await browser_capture(
        url,
        include_vision=False,
        include_lighthouse=False,
        include_technical_crawl=False,
    )
