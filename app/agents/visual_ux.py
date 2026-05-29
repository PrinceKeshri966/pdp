"""
Lightweight visual UX signals via Playwright (optional).
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any

from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

_VIEWPORTS = {
    "desktop": {"width": 1366, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

_ELEMENT_BOUNDS_JS = """async () => {
    const vh = window.innerHeight;
    const vw = window.innerWidth;

    function visibleRect(el) {
        if (!el || el.nodeType !== 1) return null;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return null;
        const st = getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) return null;
        return {
            x: Math.round(r.x),
            y: Math.round(r.y),
            width: Math.round(r.width),
            height: Math.round(r.height),
            top: Math.round(r.top),
            left: Math.round(r.left),
        };
    }

    function smallestMatch(selector, testFn) {
        let best = null;
        let bestArea = Infinity;
        for (const el of document.querySelectorAll(selector)) {
            if (testFn && !testFn(el)) continue;
            const r = visibleRect(el);
            if (!r) continue;
            const area = r.width * r.height;
            if (area < bestArea) {
                best = el;
                bestArea = area;
            }
        }
        return best;
    }

    const h1El = smallestMatch('h1', (el) => !!(el.innerText || '').trim());
    if (h1El) {
        try { h1El.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }); } catch (_) {}
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    }

    const ctaRe = /add to cart|buy now|shop now|get started|order now|sign up|join now|download|try free/i;
    const ctaEl = smallestMatch(
        'button, a[role=button], a.btn, [class*="cta"], input[type=submit]',
        (el) => {
            const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
            return ctaRe.test(t) && t.length <= 80;
        }
    );

    const trustRe = /secure|guarantee|verified|ssl|free shipping|money back|★|rating|review/i;
    const trustEl = smallestMatch('*', (el) => {
        if (['SCRIPT', 'STYLE', 'SVG', 'PATH'].includes(el.tagName)) return false;
        const t = (el.innerText || '').slice(0, 120);
        return trustRe.test(t) && el.children.length <= 3;
    });

    const faqEl = smallestMatch(
        '[class*="faq"], details, [itemtype*="FAQPage"], [id*="faq"], [data-faq]',
        (el) => !!(el.innerText || '').trim()
    );

    const priceRe = /₹|\\$|€|£|\\d+[.,]\\d{2}|\\/mo|per month|starting at|from \\d/i;
    const pricingEl = smallestMatch(
        '[class*="price"], [class*="pricing"], [itemprop="price"], [data-price]',
        (el) => priceRe.test((el.innerText || '').slice(0, 80))
    );

    const ctaRe2 = /add to cart|buy now|shop now|get started|order now/i;
    const buttons = [...document.querySelectorAll('button, a[role=button], .btn, [class*="cta"]')];
    let ctaAbove = false;
    let sticky = false;
    for (const el of buttons) {
        const t = (el.innerText || '').trim();
        if (!ctaRe2.test(t)) continue;
        const r = el.getBoundingClientRect();
        if (r.top < vh && r.bottom > 0) ctaAbove = true;
        const st = getComputedStyle(el);
        if ((st.position === 'fixed' || st.position === 'sticky') && r.width > 40) sticky = true;
    }

    const trustVisible = !!trustEl && trustEl.getBoundingClientRect().top < vh * 1.5;
    const hero = !!h1El;
    const textLen = (document.body?.innerText || '').length;

    return {
        ctaAbove,
        sticky,
        trustVisible,
        hero,
        textLen,
        element_bounds: {
            h1: visibleRect(h1El),
            cta: visibleRect(ctaEl),
            trust: visibleRect(trustEl),
            faq: visibleRect(faqEl),
            pricing: visibleRect(pricingEl),
        },
        viewport_width: vw,
        viewport_height: vh,
    };
}"""


async def capture_visual_ux_facts(url: str) -> dict[str, Any]:
    """Capture desktop/mobile visual signals; safe defaults on failure."""
    default: dict[str, Any] = {
        "cta_above_fold": False,
        "sticky_cta_detected": False,
        "trust_badges_visible": False,
        "mobile_layout_quality": "average",
        "hero_section_detected": False,
        "capture_ok": False,
        "warnings": ["Visual UX capture skipped or unavailable"],
    }
    try:
        import os

        if os.getenv("SKIP_PLAYWRIGHT", "true").lower() in ("1", "true", "yes"):
            default["warnings"] = ["Playwright disabled — text-only UX analysis"]
            return default

        from playwright.async_api import async_playwright

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            facts: dict[str, Any] = {"capture_ok": True, "warnings": []}

            for label, vp in _VIEWPORTS.items():
                context = await browser.new_context(viewport=vp, user_agent=ua)
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await page.wait_for_timeout(1500)
                    if label == "desktop":
                        eval_result = await page.evaluate(_ELEMENT_BOUNDS_JS)
                        facts["cta_above_fold"] = bool(eval_result.get("ctaAbove"))
                        facts["sticky_cta_detected"] = bool(eval_result.get("sticky"))
                        facts["trust_badges_visible"] = bool(eval_result.get("trustVisible"))
                        facts["hero_section_detected"] = bool(eval_result.get("hero"))
                        facts["element_bounds"] = eval_result.get("element_bounds") or {}
                        facts["viewport_width"] = eval_result.get("viewport_width") or vp["width"]
                        facts["viewport_height"] = eval_result.get("viewport_height") or vp["height"]
                        try:
                            png_bytes = await page.screenshot(full_page=False, type="png")
                            facts["screenshot_base64"] = base64.b64encode(png_bytes).decode("ascii")
                        except Exception as shot_exc:
                            facts.setdefault("warnings", []).append(f"Screenshot capture failed: {shot_exc}")
                        export_dir = os.getenv("AUDIT_EXPORT_DIR", "").strip()
                        if export_dir:
                            out = Path(export_dir)
                            out.mkdir(parents=True, exist_ok=True)
                            desk = out / "screenshot_desktop.png"
                            await page.screenshot(path=str(desk), full_page=False)
                            facts["screenshots"] = {"desktop": str(desk)}
                    else:
                        mobile_eval = await page.evaluate(
                            """() => {
                                const overflow = document.documentElement.scrollWidth > window.innerWidth + 20;
                                const textLen = (document.body?.innerText || '').length;
                                return { overflow, textLen };
                            }"""
                        )
                        if mobile_eval.get("overflow"):
                            facts["mobile_layout_quality"] = "poor"
                        elif (mobile_eval.get("textLen") or 0) > 500:
                            facts["mobile_layout_quality"] = "good"
                        else:
                            facts["mobile_layout_quality"] = "average"
                        export_dir = os.getenv("AUDIT_EXPORT_DIR", "").strip()
                        if export_dir:
                            mob = Path(export_dir) / "screenshot_mobile.png"
                            await page.screenshot(path=str(mob), full_page=False)
                            facts.setdefault("screenshots", {})["mobile"] = str(mob)
                finally:
                    await context.close()
            await browser.close()
            return facts
    except Exception as exc:
        logger.warning("visual_ux.capture_failed", error=str(exc))
        default["warnings"] = [f"Visual capture failed: {exc}"]
        return default


async def visual_ux_agent(state: AgentState) -> AgentState:
    url = (state.get("url") or "").strip()
    if not url:
        return {}
    facts = await capture_visual_ux_facts(url)
    return {"visual_ux_facts": facts}
