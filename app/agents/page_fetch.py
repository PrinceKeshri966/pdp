"""Browser-first page fetch with Jina/HTTP fallbacks."""
from __future__ import annotations

import re
from html import unescape

import httpx

from app.core.browser_capture.capture import browser_capture_light, browser_capture_enabled
from app.core.config import get_settings

_settings = get_settings()
_JINA_BASE = "https://r.jina.ai/"
_MIN_CHARS = 200
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _html_to_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(text)).strip()[:80_000]


async def _fetch_jina(url: str) -> str | None:
    headers: dict[str, str] = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": _UA,
    }
    if _settings.jina_api_key:
        headers["Authorization"] = f"Bearer {_settings.jina_api_key}"
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.get(f"{_JINA_BASE}{url}", headers=headers)
            resp.raise_for_status()
            text = resp.text.strip()
            if len(text) >= _MIN_CHARS:
                return text
    except Exception:
        pass
    return None


async def _fetch_httpx(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _UA, "Accept": "text/html"})
            resp.raise_for_status()
            text = _html_to_text(resp.text)
            return text if len(text) >= _MIN_CHARS else None
    except Exception:
        return None


async def fetch_page_markdown(url: str) -> str | None:
    """Browser-first fetch; Jina → HTTP fallback."""
    if browser_capture_enabled():
        try:
            capture = await browser_capture_light(url)
            text = (capture.get("markdown_content") or "").strip()
            if len(text) >= _MIN_CHARS:
                return text
        except Exception:
            pass

    text = await _fetch_jina(url)
    if text:
        return text
    return await _fetch_httpx(url)


async def fetch_page_with_html(url: str) -> tuple[str | None, str | None]:
    """Return (markdown, html) — browser-first when available."""
    if browser_capture_enabled():
        try:
            capture = await browser_capture_light(url)
            md = (capture.get("markdown_content") or "").strip()
            html = capture.get("scrape_html") or ""
            if len(md) >= _MIN_CHARS:
                return md, html
        except Exception:
            pass

    md = await _fetch_jina(url)
    if md:
        return md, None
    md = await _fetch_httpx(url)
    return md, None
