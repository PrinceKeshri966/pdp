"""
E-commerce platform detection from HTML/headers/URL (no LLM).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def detect_platform(
    *,
    url: str = "",
    html: str = "",
    headers: dict[str, str] | None = None,
    network_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Return platform id, confidence, and extraction hints."""
    html_l = (html or "")[:80000].lower()
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}
    net = " ".join(network_urls or [])[:20000].lower()
    combined = f"{html_l}\n{net}"
    signals: list[str] = []
    scores: dict[str, float] = {}

    def bump(name: str, w: float, reason: str) -> None:
        scores[name] = scores.get(name, 0) + w
        signals.append(reason)

    if "cdn.shopify.com" in combined or "shopify.theme" in combined or "shopify-section" in html_l:
        bump("shopify", 3.0, "Shopify CDN/theme markers")
    if re.search(r"window\.shopify|shopifyanalytics|shopify\.shop", html_l):
        bump("shopify", 2.0, "Shopify JS globals")
    if "/products/" in (url or "").lower() and "shopify" in scores:
        bump("shopify", 1.0, "Shopify product URL")

    if "woocommerce" in combined or "wc-block" in html_l or "wp-content" in html_l:
        bump("woocommerce", 2.5, "WooCommerce markers")
    if "/wp-json/wc/" in net:
        bump("woocommerce", 2.0, "WooCommerce REST API traffic")

    if "magento" in combined or "mage/cookies" in html_l or "data-mage-init" in html_l:
        bump("magento", 2.5, "Magento markers")
    if "graphql" in net and ("product" in net or "magento" in net):
        bump("magento", 1.5, "Magento GraphQL traffic")

    if "bigcommerce" in combined or "stencil" in html_l:
        bump("bigcommerce", 2.0, "BigCommerce markers")

    if "__next_data__" in html_l or "_next/static" in html_l:
        bump("nextjs_commerce", 2.0, "Next.js hydration")
    if "reactroot" in html_l or "data-reactroot" in html_l:
        bump("react_spa", 1.5, "React SPA")

    host = (urlparse(url).netloc or "").lower()
    if "mamaearth" in host:
        bump("custom_react", 1.0, "Known React-heavy Indian D2C")
    if "boat-lifestyle" in host or "boat-lifestyle.com" in host:
        bump("shopify", 0.5, "Boat lifestyle (often Shopify-like)")

    if not scores:
        platform = "generic"
        confidence = 0.35
    else:
        platform = max(scores, key=scores.get)
        top = scores[platform]
        second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
        confidence = min(0.98, round(0.5 + (top - second) * 0.12, 2))

    return {
        "platform": platform,
        "confidence": confidence,
        "signals": list(dict.fromkeys(signals))[:10],
        "scores": {k: round(v, 2) for k, v in scores.items()},
        "preferred_strategy": _strategy_for_platform(platform),
    }


def _strategy_for_platform(platform: str) -> str:
    return {
        "shopify": "playwright_first+shopify_api+json_ld",
        "woocommerce": "playwright_first+wc_api+json_ld",
        "magento": "playwright_first+graphql+json_ld",
        "nextjs_commerce": "playwright_first+network+json_ld",
        "bigcommerce": "playwright_first+json_ld",
        "react_spa": "playwright_first+network",
        "custom_react": "playwright_first+network+json_ld",
    }.get(platform, "playwright_first+json_ld+dom")
