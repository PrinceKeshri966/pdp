"""
Parse application/ld+json Product / Offer / AggregateRating blocks.
"""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any


def _iter_ld_nodes(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            return [n for n in data["@graph"] if isinstance(n, dict)]
        return [data]
    if isinstance(data, list):
        out: list[dict[str, Any]] = []
        for item in data:
            out.extend(_iter_ld_nodes(item))
        return out
    return []


def _type_matches(node: dict[str, Any], *types: str) -> bool:
    t = node.get("@type")
    if isinstance(t, str):
        return t.lower() in types
    if isinstance(t, list):
        return any(str(x).lower() in types for x in t)
    return False


def _first_str(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s or None
    if isinstance(val, dict):
        return _first_str(val.get("name") or val.get("@value"))
    if isinstance(val, list) and val:
        return _first_str(val[0])
    return None


def _price_from_offer(offer: Any) -> tuple[str | None, str | None]:
    if not isinstance(offer, dict):
        return None, None
    price = offer.get("price") or offer.get("lowPrice")
    currency = offer.get("priceCurrency")
    if price is not None:
        return str(price).strip(), (str(currency).strip() if currency else None)
    return None, None


def extract_json_ld_product(html: str) -> dict[str, Any]:
    """Extract product fields from JSON-LD; empty dict if none."""
    if not html:
        return {}
    _ld_close = "</script>"
    pattern = (
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)'
        + re.escape(_ld_close)
    )
    best: dict[str, Any] = {}
    best_score = 0

    for m in re.finditer(pattern, html, re.I):
        raw = unescape(m.group(1)).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _iter_ld_nodes(data):
            if not _type_matches(node, "product"):
                continue
            score = 1
            out: dict[str, Any] = {}
            name = _first_str(node.get("name"))
            if name:
                out["product_name"] = name
                score += 2
            brand = node.get("brand")
            if isinstance(brand, dict):
                out["brand"] = _first_str(brand.get("name"))
            elif brand:
                out["brand"] = _first_str(brand)
            if out.get("brand"):
                score += 1
            desc = _first_str(node.get("description"))
            if desc:
                out["description"] = desc[:4000]
                score += 1
            sku = _first_str(node.get("sku"))
            if sku:
                out["sku"] = sku
            gtin = node.get("gtin") or node.get("gtin13") or node.get("gtin8")
            if gtin:
                out["gtin"] = str(gtin)
            offers = node.get("offers")
            if isinstance(offers, list) and offers:
                offer = offers[0]
            else:
                offer = offers
            price, currency = _price_from_offer(offer)
            if price:
                out["price"] = price
                out["currency"] = currency or out.get("currency") or "INR"
                score += 3
            avail = None
            if isinstance(offer, dict):
                avail = offer.get("availability") or offer.get("itemCondition")
            if avail:
                if "instock" in str(avail).lower():
                    out["availability"] = "InStock"
                elif "outofstock" in str(avail).lower():
                    out["availability"] = "OutOfStock"
            images = node.get("image")
            urls: list[str] = []
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict) and img.get("url"):
                        urls.append(str(img["url"]))
            elif isinstance(images, dict) and images.get("url"):
                urls.append(str(images["url"]))
            if urls:
                out["image_urls"] = urls[:12]
                out["images_count"] = len(urls)
                score += 1
            agg = node.get("aggregateRating")
            if isinstance(agg, dict):
                rc = agg.get("reviewCount") or agg.get("ratingCount")
                rv = agg.get("ratingValue")
                if rc:
                    try:
                        out["review_count"] = int(str(rc).replace(",", ""))
                        out["has_reviews"] = True
                        score += 2
                    except ValueError:
                        pass
                if rv:
                    try:
                        out["avg_rating"] = float(rv)
                        out["has_reviews"] = True
                    except ValueError:
                        pass
            if score > best_score:
                best_score = score
                best = out
    return best
