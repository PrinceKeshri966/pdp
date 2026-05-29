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
    field_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score how trustworthy extracted product fields are."""
    sv = scrape_validation or {}
    scrape_conf = float(sv.get("confidence") or 0.7)
    meta = field_meta or structured.get("_field_sources") or {}
    missing: list[str] = []

    def field_conf(value: Any, min_len: int = 1, meta_key: str | None = None) -> float:
        if value is None or value == "" or value == []:
            return 0.0
        if isinstance(value, str) and len(value.strip()) < min_len:
            return 0.3
        if isinstance(value, (int, float)) and value <= 0:
            return 0.2
        base = 0.85
        effective_scrape = scrape_conf
        if meta_key and meta_key in meta:
            base = float(meta[meta_key].get("confidence") or base)
            src = meta[meta_key].get("source") or ""
            if src == "platform_api":
                effective_scrape = max(scrape_conf, 0.82)
            elif src in ("json_ld", "network_xhr"):
                effective_scrape = max(scrape_conf, 0.72)
            if src in ("platform_api", "json_ld", "network_xhr"):
                base = min(0.98, base + 0.05)
            if meta[meta_key].get("agreement"):
                base = min(0.98, base + 0.1)
                effective_scrape = max(effective_scrape, 0.85)
        return base * effective_scrape

    name = structured.get("product_name") or ""
    if not name or name.lower() in ("unknown", "product", "your product", "n/a"):
        missing.append("product_name")
    if re.match(r"^www\.[a-z0-9.-]+\.[a-z]{2,}$", str(name).strip(), re.I):
        missing.append("product_name")
    product_name_conf = field_conf(name, 3, "product_name")

    price = structured.get("price") or ""
    if not price or not re.search(r"\d", str(price)):
        missing.append("price")
    price_conf = field_conf(price, 2, "price")

    reviews_conf = 0.0
    review_count = structured.get("review_count")
    page_type = (scrape_validation or {}).get("page_type") or (scrape_validation or {}).get("detected_page_type") or ""
    review_suspicious = (
        review_count
        and (
            int(review_count) > 100_000
            or (page_type in ("homepage", "saas_landing") and int(review_count) > 5000)
        )
    )
    if structured.get("has_reviews") and not review_suspicious:
        reviews_conf = field_conf(True, 1, "review_count")
        if structured.get("review_count") or structured.get("avg_rating"):
            reviews_conf = max(reviews_conf, 0.85 * max(scrape_conf, 0.72))
    elif review_suspicious:
        reviews_conf = 0.0
    else:
        if page_type not in ("homepage", "saas_landing", "blog"):
            missing.append("reviews")

    brand = structured.get("brand") or ""
    if not brand:
        missing.append("brand")
    brand_conf = field_conf(brand, 2, "brand")

    images_conf = 0.0
    if structured.get("image_urls") or (structured.get("images_count") or 0) > 0:
        images_conf = field_conf(structured.get("images_count") or 1, 1, "image_urls")

    schema_conf = 0.0
    strategies = structured.get("_extraction_strategies") or {}
    if strategies.get("schema"):
        schema_conf = float((meta.get("schema_confidence") or {}).get("confidence") or 0.9) * scrape_conf
    elif meta.get("schema_confidence"):
        schema_conf = float(meta["schema_confidence"].get("confidence") or 0) * scrape_conf

    cta_conf = 0.5 * scrape_conf if structured.get("above_fold_cta") else 0.0

    desc = structured.get("description") or ""
    if len(desc) < 40:
        missing.append("description")

    scores = [product_name_conf, price_conf, brand_conf, reviews_conf]
    overall = round(sum(scores) / len(scores), 2)

    strategies = structured.get("_extraction_strategies") or {}
    if strategies.get("platform_api") and product_name_conf >= 0.7 and price_conf >= 0.7:
        overall = max(overall, 0.78)
    elif strategies.get("schema") and price_conf >= 0.75 and product_name_conf >= 0.7:
        overall = max(overall, 0.68)

    if sv.get("scrape_quality") == "low":
        overall = round(overall * 0.65, 2)
    if missing:
        overall = round(overall * max(0.5, 1 - 0.08 * len(missing)), 2)

    # Never claim high confidence without price on PDP
    if "price" in missing and overall > 0.55:
        overall = min(overall, 0.45)
    # Reviews optional for PDP — do not over-penalize when price+name are platform-verified
    if strategies.get("platform_api") and "reviews" in missing and overall < 0.65:
        overall = max(overall, 0.62)

    return {
        "product_name_confidence": round(product_name_conf, 2),
        "price_confidence": round(price_conf, 2),
        "reviews_confidence": round(reviews_conf, 2),
        "brand_confidence": round(brand_conf, 2),
        "image_confidence": round(images_conf, 2),
        "schema_confidence": round(schema_conf, 2),
        "cta_confidence": round(cta_conf, 2),
        "overall_extraction_confidence": overall,
        "missing_critical_fields": missing,
    }
