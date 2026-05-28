"""Whether Playwright (browser) features are enabled on this deployment."""
from __future__ import annotations

import os


def playwright_enabled() -> bool:
    """Off when SKIP_PLAYWRIGHT is true (default on Vercel / Render)."""
    return os.getenv("SKIP_PLAYWRIGHT", "true").lower() not in ("1", "true", "yes")


def screenshot_service_available(screenshot_api_url: str = "") -> bool:
    """True if this host or a remote Render API can run screenshots."""
    return playwright_enabled() or bool(screenshot_api_url.strip())
