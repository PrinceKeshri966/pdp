"""
Deterministic SEO fact extraction — no LLM.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

from app.agents.scraper_agent import _extract_dom_metadata
from app.core.extraction.schema_graph import schema_flags_for_seo

_CTA_IN_META = re.compile(
    r"\b(shop now|buy now|order|get started|learn more|sign up|try free|book now)\b",
    re.I,
)
_IMG_TAG = re.compile(r"<img[^>]*>", re.I)
_ALT = re.compile(r'alt=["\']([^"\']*)["\']', re.I)
_LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.I)
_H1_MD = re.compile(r"^#\s+(.+)$", re.M)
_H2_MD = re.compile(r"^##\s+(.+)$", re.M)
_H3_MD = re.compile(r"^###\s+(.+)$", re.M)
_H_HTML = re.compile(r"<(h[1-3])[^>]*>([\s\S]*?)</\1>", re.I)
_STOP = frozenset(
    "the and for with this that from your have will are was been our not but can all".split()
)


def _clip(s: str, n: int = 200) -> str:
    return s[:n].strip() if s else ""


def _body_text(markdown: str, html: str) -> str:
    if html:
        t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
        t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        return re.sub(r"\s+", " ", unescape(t)).strip()
    t = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", markdown or "")
    t = re.sub(r"#{1,6}\s+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _readability_label(text: str) -> tuple[str, float]:
    words = text.split()
    if len(words) < 30:
        return "poor", 3.0
    sentences = max(1, len(re.split(r"[.!?]+", text)))
    avg_w = len(words) / sentences
    avg_len = sum(len(w) for w in words) / len(words)
    if avg_w < 14 and avg_len < 5.5:
        return "excellent", 9.0
    if avg_w < 20:
        return "good", 7.5
    if avg_w < 28:
        return "average", 5.5
    return "poor", 3.5


def _score_band(length: int, lo: int, hi: int, soft_max: int) -> tuple[float, list[str]]:
    issues: list[str] = []
    if length == 0:
        return 0.0, ["Missing"]
    if lo <= length <= hi:
        return 9.0, issues
    if length < lo:
        issues.append(f"Too short ({length} chars; aim {lo}-{hi})")
        return max(3.0, 6.0 - (lo - length) / 10), issues
    if length <= soft_max:
        issues.append(f"Slightly long ({length} chars; aim {lo}-{hi})")
        return 7.0, issues
    issues.append(f"Too long ({length} chars; aim {lo}-{hi})")
    return max(4.0, 7.0 - (length - soft_max) / 15), issues


def _count_links(html: str, markdown: str, base_url: str) -> tuple[int, int]:
    base_host = urlparse(base_url).netloc.lower().replace("www.", "")
    internal = external = 0
    hrefs: list[str] = []
    for m in _LINK.finditer(html or ""):
        hrefs.append(m.group(1))
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", markdown or ""):
        hrefs.append(m.group(2))
    for href in hrefs:
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        host = urlparse(href).netloc.lower().replace("www.", "") if "://" in href else base_host
        if not host or host == base_host:
            internal += 1
        else:
            external += 1
    return internal, external


def _schema_types(html: str, dom: dict[str, Any]) -> dict[str, Any]:
    """JSON-LD graph parsing — replaces regex-only @type detection."""
    schema = schema_flags_for_seo(html or "")
    if dom.get("product_schema_present") and not schema.get("has_product_schema"):
        schema["has_product_schema"] = True
        if "Product" not in schema["types"]:
            schema["types"].append("Product")
    if dom.get("faq_schema_present") and not schema.get("has_faq_schema"):
        schema["has_faq_schema"] = True
        if "FAQPage" not in schema["types"]:
            schema["types"].append("FAQPage")
    schema["detected"] = bool(schema.get("types"))
    return schema


def _sync_schema_flags(schema: dict[str, Any]) -> dict[str, Any]:
    """Reconcile boolean schema flags after merging browser_capture detected_types."""
    types = schema.get("types") or []
    schema["has_product_schema"] = bool(schema.get("has_product_schema")) or "Product" in types
    schema["has_faq_schema"] = bool(schema.get("has_faq_schema")) or "FAQPage" in types
    schema["has_review_schema"] = bool(schema.get("has_review_schema")) or "Review" in types
    schema["has_breadcrumb_schema"] = bool(schema.get("has_breadcrumb_schema")) or "BreadcrumbList" in types
    schema["detected"] = bool(types)
    return schema


def _keyword_stats(text: str, title: str, h1: str, meta: str) -> dict[str, Any]:
    words = re.findall(r"[a-z]{3,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1
    primary = ""
    if title:
        tw = [w for w in re.findall(r"[a-z]{3,}", title.lower()) if w not in _STOP]
        primary = tw[0] if tw else ""
    if not primary and h1:
        tw = [w for w in re.findall(r"[a-z]{3,}", h1.lower()) if w not in _STOP]
        primary = tw[0] if tw else ""
    if not primary and freq:
        primary = max(freq.items(), key=lambda x: x[1])[0]
    density = round(100 * freq.get(primary, 0) / max(len(words), 1), 2) if primary else 0.0
    first_100 = " ".join(words[:100])
    return {
        "primary_keyword": primary,
        "secondary_keywords": [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:8] if w != primary],
        "density_pct": density,
        "in_title": primary in title.lower() if primary and title else False,
        "in_h1": primary in h1.lower() if primary and h1 else False,
        "in_meta_description": primary in meta.lower() if primary and meta else False,
        "in_first_100_words": primary in first_100 if primary else False,
    }


def extract_seo_facts(
    *,
    url: str,
    markdown: str = "",
    scrape_html: str = "",
    dom_technical_seo: dict[str, Any] | None = None,
    page_main_summary: dict[str, Any] | None = None,
    browser_capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact structured SEO facts — prefers rendered DOM from browser capture."""
    dom = dict(dom_technical_seo or {})
    if scrape_html and not dom.get("title_tag"):
        dom = {**dom, **_extract_dom_metadata(scrape_html)}

    html = scrape_html or ""
    dom_seo = (browser_capture or {}).get("dom_seo") or {}
    use_dom = bool(dom_seo.get("source") == "rendered_dom")

    text = _body_text("" if use_dom and html else markdown, html)
    title = dom.get("title_tag") or dom_seo.get("title_tag") or (page_main_summary or {}).get("title") or ""
    meta = dom.get("meta_description") or dom_seo.get("meta_description") or (page_main_summary or {}).get("meta_description") or ""

    h1_values: list[str] = list(dom_seo.get("h1_values") or []) if use_dom else []
    h2_count = int(dom_seo.get("h2_count", 0)) if use_dom else 0
    h3_count = int(dom_seo.get("h3_count", 0)) if use_dom else 0
    for m in _H_HTML.finditer(html):
        tag, inner = m.group(1).lower(), unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        if tag == "h1" and inner and inner not in h1_values:
            h1_values.append(inner)
        elif tag == "h2":
            h2_count += 1
        elif tag == "h3":
            h3_count += 1
    if not use_dom:
        for m in _H1_MD.finditer(markdown):
            h1_values.append(m.group(1).strip())
        h2_count += len(_H2_MD.findall(markdown))
        h3_count += len(_H3_MD.findall(markdown))

    h1_val = h1_values[0] if h1_values else ""
    title_score, title_issues = _score_band(len(title), 50, 60, 70)
    meta_score, meta_issues = _score_band(len(meta), 120, 160, 200)
    h1_score = 8.0 if len(h1_values) == 1 else (4.0 if len(h1_values) == 0 else 5.0)
    h1_issues = [] if len(h1_values) == 1 else [f"H1 count is {len(h1_values)} (want exactly 1)"]

    imgs = _IMG_TAG.findall(html) if html else []
    md_imgs = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))
    total_images = len(imgs) or md_imgs
    alts = [_ALT.search(i) for i in imgs]
    alt_texts = [a.group(1).strip() for a in alts if a]
    missing_alt = max(0, len(imgs) - len(alt_texts)) if imgs else 0
    descriptive = sum(1 for a in alt_texts if len(a) > 8)

    internal, external = _count_links(html, markdown, url)
    kw = _keyword_stats(text, title, h1_val, meta)
    readability, read_score = _readability_label(text)
    word_count = len(text.split()) if text else 0
    schema_val = (browser_capture or {}).get("schema_validation") or {}
    tech_crawl = (browser_capture or {}).get("technical_crawl") or {}
    lighthouse = (browser_capture or {}).get("lighthouse") or {}
    schema = _schema_types(html, dom)
    if schema_val.get("detected_types"):
        schema["types"] = list(dict.fromkeys(schema["types"] + schema_val["detected_types"]))
        schema["detected"] = True
        schema["validation"] = schema_val.get("schemas", {})
        schema["score"] = round((schema_val.get("overall_score") or 80) / 10, 1)
    schema = _sync_schema_flags(schema)
    path = urlparse(url).path or "/"
    path_tokens = [t for t in re.split(r"[-_/]+", path.lower()) if len(t) > 2]

    lazy_loading = bool(re.search(r'loading=["\']lazy["\']', html, re.I)) if html else False
    large_images = total_images > 15 or bool(re.search(r"width=[\"']?\d{4,}", html, re.I))
    render_blocking = bool(re.search(r"<script[^>]*(?!async|defer)[^>]*src=", html, re.I)) if html else False

    return {
        "title_tag": {"value": title, "length": len(title), "score": round(title_score, 1), "issues": title_issues},
        "meta_description": {
            "value": meta,
            "length": len(meta),
            "has_cta": bool(_CTA_IN_META.search(meta)),
            "score": round(meta_score, 1),
            "issues": meta_issues,
        },
        "h1": {"value": h1_val, "count": len(h1_values), "score": round(h1_score, 1), "issues": h1_issues},
        "headings_structure": {
            "h2_count": h2_count,
            "h3_count": h3_count,
            "logical_hierarchy": h2_count > 0 or h3_count == 0,
            "keyword_in_headings": kw["primary_keyword"] in (h1_val or "").lower() if kw["primary_keyword"] else False,
            "score": 7.5 if h2_count >= 2 else (5.0 if h2_count else 4.0),
        },
        "keyword_analysis": {**kw, "score": 7.0 if kw["in_title"] and kw["in_h1"] else 5.0},
        "content_quality": {
            "word_count": word_count,
            "readability": readability,
            "thin_content": word_count < 300,
            "duplicate_content_risk": False,
            "score": round(read_score, 1),
        },
        "image_seo": {
            "total_images": total_images,
            "missing_alt": missing_alt,
            "descriptive_alt": descriptive,
            "score": 8.0 if missing_alt == 0 and total_images else (5.0 if total_images else 3.0),
        },
        "structured_data": {**schema, "score": schema.get("score") or (8.0 if schema["detected"] else 3.0)},
        "links": {
            "internal_count": internal,
            "external_count": external,
            "broken_links_risk": False,
            "score": 7.0 if internal >= 3 else 5.0,
        },
        "technical_seo": _build_technical_seo(
            dom, dom_seo, html, tech_crawl, lighthouse, large_images, render_blocking, lazy_loading
        ),
        "url_structure": {
            "path": path,
            "is_seo_friendly": len(path) < 80 and " " not in path,
            "has_keyword": bool(path_tokens),
            "issues": [],
        },
        "_deterministic": True,
        "_source": "rendered_dom" if use_dom else "markdown",
    }


def _build_technical_seo(
    dom: dict,
    dom_seo: dict,
    html: str,
    tech_crawl: dict,
    lighthouse: dict,
    large_images: bool,
    render_blocking: bool,
    lazy_loading: bool,
) -> dict[str, Any]:
    cwv = lighthouse.get("core_web_vitals") or {}
    lcp_rating = (cwv.get("LCP") or {}).get("rating", "unknown")
    cls_rating = (cwv.get("CLS") or {}).get("rating", "unknown")
    perf_score = (lighthouse.get("categories") or {}).get("performance")

    cwv_risk = "high" if lcp_rating == "poor" or cls_rating == "poor" else (
        "medium" if lcp_rating == "needs_improvement" else "low"
    )
    if not lighthouse.get("available"):
        cwv_risk = "high" if large_images and render_blocking else ("medium" if large_images else "low")

    tech_score = tech_crawl.get("score") or 7.5
    if perf_score is not None:
        tech_score = round((tech_score + perf_score / 10) / 2, 1)

    return {
        "canonical_present": bool(dom.get("canonical_present") or dom_seo.get("canonical_present")),
        "open_graph_present": bool(dom.get("open_graph_present") or dom_seo.get("open_graph_present")),
        "twitter_card_present": bool(
            dom_seo.get("twitter_card_present")
            or (tech_crawl.get("twitter_cards") or {}).get("present")
            or (re.search(r"twitter:card|name=[\"']twitter:", html, re.I) if html else False)
        ),
        "hreflang_present": bool(
            dom_seo.get("hreflang_present") or (tech_crawl.get("hreflang") or {}).get("present")
        ),
        "mobile_friendly": bool(dom_seo.get("mobile_friendly") or re.search(r"viewport", html, re.I) if html else True),
        "robots_txt_found": bool((tech_crawl.get("robots_txt") or {}).get("found")),
        "sitemap_found": bool((tech_crawl.get("sitemap") or {}).get("found")),
        "redirect_count": (tech_crawl.get("redirects") or {}).get("count", 0),
        "technical_issues": tech_crawl.get("issues", []),
        "lighthouse": lighthouse.get("categories") if lighthouse.get("available") else None,
        "core_web_vitals": cwv if lighthouse.get("available") else None,
        "core_web_vitals_risk": cwv_risk,
        "page_speed_signals": {
            "large_images_detected": large_images,
            "render_blocking_scripts": render_blocking,
            "lazy_loading_used": lazy_loading,
            "estimated_lcp_risk": lcp_rating if lcp_rating != "unknown" else ("high" if large_images else "medium"),
            "estimated_cls_risk": cls_rating if cls_rating != "unknown" else ("low" if lazy_loading else "medium"),
        },
        "pagination_signals": bool(re.search(r'rel=["\']next["\']|page=\d+', html, re.I)) if html else False,
        "score": tech_score,
        "confidence": tech_crawl.get("confidence") or (0.75 if lighthouse.get("available") else 0.5),
    }
