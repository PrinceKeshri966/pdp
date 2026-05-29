"""
Lightweight visual UX signals — reuses browser capture from scraper when available.
"""
from __future__ import annotations

from app.agents.state import AgentState, state_dict
from app.core.browser_capture.capture import browser_capture, browser_capture_enabled
from app.core.logging import get_logger

logger = get_logger(__name__)


async def visual_ux_agent(state: AgentState) -> AgentState:
    """
    Use visual UX facts from browser capture (scraper phase) when available.
    Only launches a separate browser session as last resort.
    """
    existing = state_dict(state, "visual_ux_facts")
    if existing.get("capture_ok"):
        logger.info("visual_ux.reusing_browser_capture")
        return {"visual_ux_facts": existing}

    url = (state.get("url") or "").strip()
    if not url:
        return {}

    if not browser_capture_enabled():
        return {
            "visual_ux_facts": {
                "cta_above_fold": False,
                "sticky_cta_detected": False,
                "trust_badges_visible": False,
                "mobile_layout_quality": "average",
                "hero_section_detected": False,
                "capture_ok": False,
                "warnings": ["Playwright disabled — text-only UX analysis"],
            }
        }

    try:
        capture = await browser_capture(url, include_vision=True, include_lighthouse=False, include_technical_crawl=False)
        facts = capture.get("visual_ux_facts") or {}
        if facts.get("capture_ok"):
            return {"visual_ux_facts": facts}
    except Exception as exc:
        logger.warning("visual_ux.fallback_capture_failed", error=str(exc))

    return {
        "visual_ux_facts": {
            "capture_ok": False,
            "warnings": ["Visual UX capture unavailable"],
        }
    }
