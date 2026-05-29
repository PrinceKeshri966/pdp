"""
DOM-based SEO extraction — primary source of truth (not markdown).
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

from app.core.html_metadata import extract_dom_metadata


def extract_dom_seo_facts(html: str, url: str = "") -> dict[str, Any]:
    """Extract SEO facts directly from rendered DOM HTML."""
    dom = extract_dom_metadata(html)
    low = html.lower()

    h1_values: list[str] = []
    h2_count = h3_count = 0
    for m in re.finditer(r"<(h[1-3])[^>]*>([\s\S]*?)</\1>", html, re.I):
        tag, inner = m.group(1).lower(), unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        if tag == "h1" and inner:
            h1_values.append(inner)
        elif tag == "h2":
            h2_count += 1
        elif tag == "h3":
            h3_count += 1

    imgs = re.findall(r"<img[^>]*>", html, re.I)
    alt_texts = []
    missing_alt = 0
    for img in imgs:
        alt_m = re.search(r'alt=["\']([^"\']*)["\']', img, re.I)
        if alt_m:
            alt_texts.append(alt_m.group(1).strip())
        else:
            missing_alt += 1

    internal = external = 0
    base_host = urlparse(url).netloc.lower().replace("www.", "") if url else ""
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I):
        href = m.group(1)
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        host = urlparse(href).netloc.lower().replace("www.", "") if "://" in href else base_host
        if not host or host == base_host:
            internal += 1
        else:
            external += 1

    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    word_count = len(text.split()) if text else 0

    canonical = bool(re.search(r'<link[^>]*rel=["\']canonical["\']', html, re.I))
    og = bool(re.search(r'property=["\']og:', html, re.I))
    twitter = bool(re.search(r'name=["\']twitter:', html, re.I))
    hreflang = bool(re.search(r'hreflang=', html, re.I))
    viewport = bool(re.search(r'name=["\']viewport["\']', html, re.I))
    lazy = bool(re.search(r'loading=["\']lazy["\']', html, re.I))
    render_blocking = bool(re.search(r"<script[^>]*(?!async|defer)[^>]*src=", html, re.I))

    schema_types: list[str] = []
    for t in ("Product", "FAQPage", "BreadcrumbList", "Review", "Organization", "WebSite"):
        if re.search(rf'["\']@type["\']\s*:\s*["\']{t}["\']', low):
            schema_types.append(t)

    return {
        "source": "rendered_dom",
        "title_tag": dom.get("title_tag"),
        "meta_description": dom.get("meta_description"),
        "h1_values": h1_values,
        "h1_count": len(h1_values),
        "h2_count": h2_count,
        "h3_count": h3_count,
        "word_count": word_count,
        "images": {"total": len(imgs), "missing_alt": missing_alt, "with_alt": len(alt_texts)},
        "links": {"internal": internal, "external": external},
        "canonical_present": canonical or bool(dom.get("canonical_present")),
        "open_graph_present": og or bool(dom.get("open_graph_present")),
        "twitter_card_present": twitter,
        "hreflang_present": hreflang,
        "mobile_friendly": viewport,
        "schema_types": schema_types,
        "lazy_loading": lazy,
        "render_blocking_scripts": render_blocking,
        "confidence": 0.92 if word_count > 100 else 0.65,
    }
