"""Browser-first scraping architecture — unified Playwright capture."""
from app.core.browser_capture.capture import browser_capture, browser_capture_enabled
from app.core.browser_capture.confidence import compute_section_confidence

__all__ = ["browser_capture", "browser_capture_enabled", "compute_section_confidence"]
