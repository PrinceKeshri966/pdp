"""
Hard-fail scrape gate — stop pipeline before extraction on invalid pages.
"""
from __future__ import annotations

import re
from typing import Any

_MIN_CONTENT_WORDS = 50

_GATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "page_not_found",
        re.compile(
            r"\b404\b|page not found|page doesn't exist|page does not exist|"
            r"this page (?:is )?not available|error 404|http 404",
            re.I,
        ),
    ),
    (
        "product_not_found",
        re.compile(
            r"product not found|product unavailable|item not found|"
            r"no longer available|this product is (?:currently )?unavailable|"
            r"sorry, this (?:product|item) (?:is )?not available",
            re.I,
        ),
    ),
    (
        "access_denied",
        re.compile(
            r"access denied|403 forbidden|\b403\b|forbidden|permission denied|"
            r"you don't have permission|request blocked",
            re.I,
        ),
    ),
    (
        "captcha_block",
        re.compile(
            r"captcha|recaptcha|hcaptcha|verify you are human|robot check|"
            r"checking your browser|just a moment|attention required|"
            r"cf-browser-verification|challenge-platform|"
            r"your connection needs to be verified|cloudflare ray id",
            re.I,
        ),
    ),
    (
        "login_required",
        re.compile(
            r"sign in to continue|log in to view|login required|members only|"
            r"create an account to|please log in|sign in to shop",
            re.I,
        ),
    ),
]

_USER_MESSAGES = {
    "empty_content": "The page returned no usable content for analysis.",
    "page_not_found": "This URL appears to be a 404 / page-not-found response.",
    "product_not_found": "The product page was not found or is unavailable.",
    "access_denied": "Access to this page was denied (403 / blocked).",
    "captcha_block": "The site returned a CAPTCHA or bot-check page.",
    "login_required": "This page requires login and could not be audited.",
}


def evaluate_scrape_gate(
    *,
    markdown: str = "",
    scrape_html: str = "",
    dom_technical_seo: dict[str, Any] | None = None,
    url: str = "",
) -> dict[str, Any] | None:
    """
    Return structured hard-fail payload, or None if the scrape may proceed.
    """
    dom = dom_technical_seo or {}
    text = (markdown or "").strip()
    html = (scrape_html or "").lower()
    title = str(dom.get("title_tag") or "")
    combined = f"{title}\n{text}\n{html[:120000]}"

    http_status = dom.get("http_status") or dom.get("status_code")
    if http_status in (403, 401):
        code = "login_required" if http_status == 401 else "access_denied"
        return _hard_fail(code, detail=f"HTTP {http_status}", url=url)
    if http_status == 404:
        return _hard_fail("page_not_found", detail="HTTP 404", url=url)

    for code, pattern in _GATE_PATTERNS:
        if pattern.search(combined):
            return _hard_fail(code, detail=f"Matched {code} signal in page content.", url=url)

    word_count = len(text.split())
    if not text or word_count < _MIN_CONTENT_WORDS:
        return _hard_fail(
            "empty_content",
            detail=f"Extracted {word_count} words (minimum {_MIN_CONTENT_WORDS}).",
            url=url,
        )

    return None


def _hard_fail(code: str, *, detail: str, url: str) -> dict[str, Any]:
    return {
        "hard_fail": True,
        "code": code,
        "message": _USER_MESSAGES.get(code, "Page could not be analyzed."),
        "detail": detail,
        "url": url,
        "recoverable": False,
        "agents_skipped": [
            "context_router",
            "visual_ux",
            "extractor",
            "seo",
            "aeo",
            "ux",
            "competitor",
            "psychology",
            "validator",
            "prioritization",
            "autofix",
            "content_gen",
        ],
    }
