"""
Confidence scoring for extractor output (deterministic).
"""
from __future__ import annotations

import re
from typing import Any


def score_extraction_confidence(
    structured: dict[str, Any],
    *,
    scrape_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score how trustworthy extracted product fields are."""
    sv = scrape_validation or {}
    scrape_conf = float(sv.get("confidence") or 0.7)
    missing: list[str] = []

    def field_conf(value: Any, min_len: int = 1) -> float:
        if value is None or value == "" or value == []:
            return 0.0
        if isinstance(value, str) and len(value.strip()) < min_len:
            return 0.3
        if isinstance(value, (int, float)) and value <= 0:
            return 0.2
        return 0.85

    name = structured.get("product_name") or ""
    if not name or name.lower() in ("unknown", "product", "your product", "n/a"):
        missing.append("product_name")
    product_name_conf = field_conf(name, 3) * scrape_conf

    price = structured.get("price") or ""
    if not price or not re.search(r"\d", str(price)):
        missing.append("price")
    price_conf = field_conf(price, 2) * scrape_conf

    reviews_conf = 0.0
    if structured.get("has_reviews"):
        reviews_conf = 0.7
        if structured.get("review_count") or structured.get("avg_rating"):
            reviews_conf = 0.9
    else:
        missing.append("reviews")

    brand = structured.get("brand") or ""
    if not brand:
        missing.append("brand")
    brand_conf = field_conf(brand, 2) * scrape_conf

    desc = structured.get("description") or ""
    if len(desc) < 40:
        missing.append("description")

    scores = [product_name_conf, price_conf, brand_conf, reviews_conf]
    overall = round(sum(scores) / len(scores), 2)

    if sv.get("scrape_quality") == "low":
        overall = round(overall * 0.65, 2)
    if missing:
        overall = round(overall * max(0.5, 1 - 0.08 * len(missing)), 2)

    return {
        "product_name_confidence": round(product_name_conf, 2),
        "price_confidence": round(price_conf, 2),
        "reviews_confidence": round(reviews_conf, 2),
        "brand_confidence": round(brand_conf, 2),
        "overall_extraction_confidence": overall,
        "missing_critical_fields": missing,
    }
