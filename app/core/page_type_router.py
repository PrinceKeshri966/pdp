"""
Page-type detection for specialized audits (no LLM).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

PAGE_TYPES = [
    "homepage",
    "pdp",
    "category_page",
    "collection",
    "blog",
    "about_page",
    "search_page",
    "saas_landing",
    "marketplace",
    "local_business",
    "docs",
    "comparison_page",
    "unknown",
]

_PDP_PATH = re.compile(
    r"/(product|products|p|item|sku|dp|pd|buy|shop/[^/]+/[^/]+)(/|$)",
    re.I,
)
_CATEGORY_PATH = re.compile(
    r"/(category|categories|collection|collections|c/|cat/|shop/[^/]+/?$)(/|$)",
    re.I,
)
_ABOUT_PATH = re.compile(r"/(about|our-story|company|who-we-are|about-us)(/|$)", re.I)
_SEARCH_PATH = re.compile(r"/(search|find)(/|\?|$)", re.I)
_BLOG_PATH = re.compile(r"/(blog|article|post|news|insights|resources)(/|$)", re.I)
_DOCS_PATH = re.compile(r"/(docs|documentation|api|guide|help|support)(/|$)", re.I)
_COMPARE_PATH = re.compile(r"/(compare|vs|versus|alternatives)(/|$)", re.I)
_MARKETPLACE = re.compile(r"\b(seller|marketplace|fulfilled by|ships from)\b", re.I)
_SAAS = re.compile(
    r"\b(free trial|sign up|get started|pricing plans|integrations|api docs|"
    r"enterprise plan|book a demo|schedule demo|saas)\b",
    re.I,
)
_LOCAL = re.compile(
    r"\b(hours|directions|visit us|call now|near me|local business|"
    r"google maps|store locator)\b",
    re.I,
)
_ADD_CART = re.compile(r"\b(add to cart|add to bag|buy now|order now)\b", re.I)
_PRICING = re.compile(r"(?:₹|rs\.?|inr|\$|€|£)\s*[\d,]+|\b(pricing|plans|per month|/mo)\b", re.I)
_PRODUCT_SCHEMA = re.compile(r'"@type"\s*:\s*["\']Product["\']', re.I)
_ORG_SCHEMA = re.compile(r'"@type"\s*:\s*["\'](?:Organization|WebSite)["\']', re.I)
_FAQ_SCHEMA = re.compile(r'"@type"\s*:\s*["\']FAQPage["\']', re.I)
_BREADCRUMB = re.compile(r'"@type"\s*:\s*["\']BreadcrumbList["\']', re.I)
_REVIEW = re.compile(r"\b(\d+\s*reviews?|verified buyer|star rating|★)\b", re.I)
_HERO = re.compile(r"\b(welcome|hero|featured|shop all|discover|our mission)\b", re.I)
_VARIANT = re.compile(r"\b(select size|choose color|variant|sku)\b", re.I)


def detect_page_type(
    *,
    url: str = "",
    markdown: str = "",
    scrape_html: str = "",
    dom_technical_seo: dict[str, Any] | None = None,
    structured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return { page_type, confidence, reasons }.
    """
    dom = dom_technical_seo or {}
    structured = structured or {}
    text = (markdown or "")[:12000]
    html = (scrape_html or "")[:50000].lower()
    combined = f"{text}\n{html}".lower()
    path = urlparse(url or "").path.lower().strip("/") or ""
    reasons: list[str] = []
    scores: dict[str, float] = {t: 0.0 for t in PAGE_TYPES}

    if not path or path in ("", "index", "index.html", "home"):
        scores["homepage"] += 2.5
        reasons.append("URL path is root/home")
    if _PDP_PATH.search(f"/{path}"):
        scores["pdp"] += 3.0
        reasons.append("URL matches product path pattern")
    if _CATEGORY_PATH.search(f"/{path}"):
        scores["category_page"] += 2.5
        scores["collection"] += 2.5
        reasons.append("URL matches category/collection path")
    if _ABOUT_PATH.search(f"/{path}"):
        scores["about_page"] += 2.8
        reasons.append("URL matches about page path")
    if _SEARCH_PATH.search(f"/{path}") or "?" in (url or "") and re.search(r"[?&]q=", url or "", re.I):
        scores["search_page"] += 2.8
        reasons.append("URL matches search page")
    if _BLOG_PATH.search(f"/{path}"):
        scores["blog"] += 2.5
        reasons.append("URL matches blog/article path")
    if _DOCS_PATH.search(f"/{path}"):
        scores["docs"] += 2.5
        reasons.append("URL matches documentation path")
    if _COMPARE_PATH.search(f"/{path}"):
        scores["comparison_page"] += 2.5
        reasons.append("URL matches comparison path")

    if dom.get("product_schema_present") or _PRODUCT_SCHEMA.search(html):
        scores["pdp"] += 2.5
        reasons.append("Product schema detected")
    if _ORG_SCHEMA.search(html) and not _PRODUCT_SCHEMA.search(html):
        scores["homepage"] += 1.0
        scores["saas_landing"] += 0.8
    if _FAQ_SCHEMA.search(html):
        scores["blog"] += 0.3
        scores["pdp"] += 0.3
    if _BREADCRUMB.search(html):
        scores["pdp"] += 0.8
        scores["category_page"] += 0.5

    if _ADD_CART.search(combined):
        scores["pdp"] += 2.0
        reasons.append("Add-to-cart / buy CTA present")
    if _PRICING.search(combined):
        scores["pdp"] += 1.0
        scores["saas_landing"] += 1.2
        scores["marketplace"] += 0.5
    if _SAAS.search(combined):
        scores["saas_landing"] += 2.5
        reasons.append("SaaS signup/pricing language detected")
    if _LOCAL.search(combined):
        scores["local_business"] += 2.0
    if _MARKETPLACE.search(combined):
        scores["marketplace"] += 1.5
    if _REVIEW.search(combined):
        scores["pdp"] += 1.2
    if _VARIANT.search(combined):
        scores["pdp"] += 1.5
    if _HERO.search(combined[:4000]) and not _ADD_CART.search(combined[:2000]):
        scores["homepage"] += 1.5

    if structured.get("price") or structured.get("sku"):
        scores["pdp"] += 1.5
    if structured.get("categories") and not structured.get("price"):
        scores["category_page"] += 0.8

    # Legacy scrape_validator alias
    legacy = (dom.get("detected_page_type") or "").lower()
    if legacy == "product":
        scores["pdp"] += 1.0
    elif legacy == "homepage":
        scores["homepage"] += 1.0

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]
    total = sum(scores.values()) or 1.0
    confidence = round(min(0.98, max(0.35, best_score / max(total * 0.45, 1.0))), 2)

    if best_score < 1.5:
        best_type = "unknown"
        confidence = 0.4
        reasons.append("Weak signals — classified as unknown")

    return {
        "page_type": best_type,
        "confidence": confidence,
        "reasons": list(dict.fromkeys(reasons))[:8],
        "signal_scores": {k: round(v, 2) for k, v in scores.items() if v > 0},
    }


def is_pdp(page_type: str | None) -> bool:
    return (page_type or "").lower() in ("pdp", "product")


def is_homepage(page_type: str | None) -> bool:
    return (page_type or "").lower() in ("homepage", "saas_landing")
