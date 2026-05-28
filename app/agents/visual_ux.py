"""
Lightweight visual UX signals via Playwright (optional).
"""
from __future__ import annotations

import re
from typing import Any

from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

_VIEWPORTS = {
    "desktop": {"width": 1366, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


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
                        eval_result = await page.evaluate(
                            """() => {
                                const vh = window.innerHeight;
                                const ctaRe = /add to cart|buy now|shop now|get started|order now/i;
                                const trustRe = /secure|guarantee|verified|ssl|free shipping|money back/i;
                                const buttons = [...document.querySelectorAll('button, a[role=button], .btn, [class*="cta"]')];
                                let ctaAbove = false;
                                let sticky = false;
                                for (const el of buttons) {
                                    const t = (el.innerText || '').trim();
                                    if (!ctaRe.test(t)) continue;
                                    const r = el.getBoundingClientRect();
                                    if (r.top < vh && r.bottom > 0) ctaAbove = true;
                                    const st = getComputedStyle(el);
                                    if ((st.position === 'fixed' || st.position === 'sticky') && r.width > 40) sticky = true;
                                }
                                const trustVisible = [...document.querySelectorAll('*')].some(el => {
                                    const t = (el.innerText || '').slice(0, 80);
                                    return trustRe.test(t) && el.getBoundingClientRect().top < vh * 1.5;
                                });
                                const hero = !!document.querySelector('header, .hero, [class*="hero"], main h1');
                                const textLen = (document.body?.innerText || '').length;
                                return { ctaAbove, sticky, trustVisible, hero, textLen };
                            }"""
                        )
                        facts["cta_above_fold"] = bool(eval_result.get("ctaAbove"))
                        facts["sticky_cta_detected"] = bool(eval_result.get("sticky"))
                        facts["trust_badges_visible"] = bool(eval_result.get("trustVisible"))
                        facts["hero_section_detected"] = bool(eval_result.get("hero"))
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
