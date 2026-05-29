"""
Playwright PDP fetch — delegates to unified browser_capture module.
Kept for backward compatibility with extraction pipeline second-pass.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.core.page_type_router import _PDP_PATH


def url_looks_like_pdp(url: str) -> bool:
    path = urlparse(url or "").path
    return bool(_PDP_PATH.search(path or "/"))


async def fetch_pdp_with_playwright(url: str, *, review_focus: bool = False) -> dict[str, Any]:
    """Backward-compatible wrapper around unified browser_capture."""
    from app.core.browser_capture.capture import browser_capture

    capture = await browser_capture(
        url,
        include_vision=False,
        include_lighthouse=False,
        include_technical_crawl=False,
    )
    return {
        "markdown_content": capture.get("markdown_content"),
        "scrape_html": capture.get("scrape_html"),
        "dom_technical_seo": capture.get("dom_technical_seo"),
        "network_payloads": capture.get("network_payloads"),
        "platform_info": capture.get("platform_info"),
        "scraper_method": "playwright_pdp",
    }
