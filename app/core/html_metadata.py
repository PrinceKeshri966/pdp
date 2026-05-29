"""Shared HTML metadata parsing (no agent imports)."""
from __future__ import annotations

import re
from html import unescape

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
MAX_CONTENT_CHARS = 80_000
MAX_SCRAPE_HTML_CHARS = 120_000


def extract_dom_metadata(html: str) -> dict[str, str | bool | None]:
    title_tag = None
    meta_desc = None
    canonical_present = False
    product_schema_present = False
    faq_schema_present = False
    og_present = False

    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", html, re.I)
    if title_match:
        title_tag = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
    if not title_tag:
        og_title = re.search(
            r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        if not og_title:
            og_title = re.search(
                r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
                html,
                re.I,
            )
        if og_title:
            title_tag = unescape(og_title.group(1)).strip()

    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']description["\']', html, re.I)
    if desc_match:
        meta_desc = unescape(desc_match.group(1)).strip()

    if re.search(r'<link[^>]*rel=["\']canonical["\']', html, re.I):
        canonical_present = True
    if re.search(r'<meta[^>]*property=["\']og:title["\']', html, re.I):
        og_present = True

    _ld_close = "</script>"
    for script in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)' + _ld_close,
        html,
        re.I,
    ):
        content = script.group(1).lower()
        if "product" in content and "@type" in content:
            product_schema_present = True
        if "faqpage" in content and "@type" in content:
            faq_schema_present = True

    return {
        "title_tag": title_tag,
        "meta_description": meta_desc,
        "canonical_present": canonical_present,
        "product_schema_present": product_schema_present,
        "faq_schema_present": faq_schema_present,
        "open_graph_present": og_present,
    }


def html_to_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CONTENT_CHARS]
