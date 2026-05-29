"""Shopify theme-aware extraction — Dawn, Prestige, Booster + GT parity."""
from __future__ import annotations

import re
from html import unescape
from typing import Any

from app.core.extraction.platform_parity import (
    count_faq_dom_gt,
    count_variants_dom_gt,
    extract_policy_visibility_gt,
    extract_trust_badges_gt,
)

_THEME_MARKERS: dict[str, list[str]] = {
    "dawn": ["product-form__input", "price-item--sale", "shopify-section-template--product"],
    "prestige": ["product-meta", "tabs-nav", "product-form--main"],
    "booster": ["boost-pfs", "bc-sf-filter", "boost-sd__"],
}

_PRICE_SELECTORS = [
    r'class=["\'][^"\']*offer--price[^"\']*["\'][^>]*>([\d,]+)',
    r'class=["\'][^"\']*price-item--sale[^"\']*["\'][^>]*>[^<]*(?:₹|Rs\.?\s*)?\s*([\d,]+)',
    r'data-product-price=["\']([\d,]+)["\']',
    r'class=["\'][^"\']*product__price[^"\']*["\'][^>]*>[^<]*(?:₹|Rs\.?\s*)?\s*([\d,]+)',
    r'itemprop=["\']price["\'][^>]*content=["\']([\d.]+)["\']',
]

_GT_VARIANT_RE = re.compile(
    r'<select[^>]*name=["\'][^"\']*option|'
    r'class=["\'][^"\']*variant[^"\']*["\'][^>]*>\s*<button|'
    r'class=["\'][^"\']*swatch|'
    r'data-variant-id|'
    r'class=["\'][^"\']*product-form__input[^"\']*["\'][^>]*type=["\']radio',
    re.I,
)


def detect_shopify_theme(html: str) -> str:
    if not html:
        return "unknown"
    h = html.lower()
    if "product-meta" in h or "tabs-nav" in h:
        return "prestige"
    if "product-form__input" in h or "price-item--sale" in h:
        return "dawn"
    if "boost-pfs" in h or "bc-sf-filter" in h:
        return "booster"
    for name, markers in _THEME_MARKERS.items():
        if sum(1 for m in markers if m.lower() in h) >= 2:
            return name
    return "custom"


def _pre_footer(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<footer\b", html, re.I)
    return html[: m.start()] if m else html


def _visible(html: str) -> str:
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return unescape(re.sub(r"\s+", " ", t)).strip()


def _product_zone(html: str) -> str:
    pre = _pre_footer(html)
    for pat in (
        r'(<div[^>]*class=["\'][^"\']*shopify-section[^"\']*main-product[^"\']*["\'][^>]*>[\s\S]{500,80000})',
        r'(<div[^>]*class=["\'][^"\']*product-meta[^"\']*["\'][^>]*>[\s\S]{300,40000})',
        r'(<form[^>]*class=["\'][^"\']*product-form[^"\']*["\'][^>]*>[\s\S]{200,30000})',
    ):
        m = re.search(pat, pre, re.I)
        if m:
            return m.group(1)
    return pre


def extract_visible_sale_price(html: str) -> dict[str, Any] | None:
    """GT parity: first visible ₹ price in body (offer callout or sale price)."""
    if not html:
        return None
    zone = _product_zone(html)
    for pat in _PRICE_SELECTORS:
        m = re.search(pat, zone, re.I)
        if m:
            p = m.group(1).replace(",", "")
            if p and float(p) > 0:
                return {"price": p, "source": "shopify_theme.sale_selector", "confidence": 0.90}
    text = _visible(_pre_footer(html))
    prices = re.findall(r"(?:₹|Rs\.?\s*|INR\s*)\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
    if prices:
        p = prices[0].replace(",", "")
        return {"price": p, "source": "shopify_theme.first_visible", "confidence": 0.85}
    return None


def count_variant_pickers_gt(html: str) -> int:
    """Match ground_truth_validation.js selector count."""
    return count_variants_dom_gt(html)


def count_faq_gt(html: str) -> int:
    """Match GT FAQ DOM count."""
    return count_faq_dom_gt(html)


def extract_review_widget_trust(html: str) -> list[str]:
    """Review-widget trust phrases — delegates to platform GT extractor."""
    return extract_trust_badges_gt(html)


def extract_policy_visible(html: str) -> tuple[bool, bool]:
    """Shipping + returns visibility from pre-footer body text."""
    return extract_policy_visibility_gt(html)


def extract_shopify_fields(html: str) -> dict[str, Any]:
    theme = detect_shopify_theme(html)
    price = extract_visible_sale_price(html)
    shipping, returns = extract_policy_visible(html)
    return {
        "theme": theme,
        "visible_price": price,
        "variant_picker_count_gt": count_variant_pickers_gt(html),
        "faq_count_gt": count_faq_gt(html),
        "trust_badges": extract_review_widget_trust(html),
        "shipping_visible": shipping,
        "return_policy_visible": returns,
    }
