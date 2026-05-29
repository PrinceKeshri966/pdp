"""
Unified extraction confidence scoring — Schema > API > DOM > Regex.

Every field returns {value, source, confidence}.
Used by voter, preprocessors, and extraction_confidence.
"""
from __future__ import annotations

from typing import Any

# Source tier base confidence (SEMrush/Ahrefs-style hierarchy)
SOURCE_TIERS: dict[str, float] = {
    "FAQPage.schema": 0.98,
    "json_ld": 0.92,
    "Offer.schema.availability": 0.95,
    "platform_api": 0.95,
    "platform_api.variants": 0.95,
    "platform_api.inventory_quantity": 0.93,
    "shopify_json.variants": 0.90,
    "shopify_api": 0.95,
    "network_xhr": 0.92,
    "schema_graph": 0.92,
    "faq_section.accordion": 0.85,
    "dom.question_answer": 0.78,
    "faq_section.headings": 0.75,
    "dom.variant_picker": 0.78,
    "dom.image_alt": 0.88,
    "dom.svg_label": 0.86,
    "dom.text": 0.75,
    "dom.visible_text": 0.82,
    "dom_selectors": 0.70,
    "next_data": 0.82,
    "open_graph": 0.75,
    "regex_fallback": 0.55,
    "llm": 0.65,
    "none": 0.0,
}

# Map voter source names to tiers
_VOTER_SOURCE_MAP = {
    "json_ld": "json_ld",
    "platform_api": "platform_api",
    "network_xhr": "network_xhr",
    "dom_selectors": "dom_selectors",
    "next_data": "next_data",
    "open_graph": "open_graph",
    "llm": "llm",
}


def tier_confidence(source: str, *, agreement: bool = False, has_value: bool = True) -> float:
    """Resolve confidence from source tier with optional cross-source agreement boost."""
    if not has_value:
        return 0.0
    base = SOURCE_TIERS.get(source)
    if base is None:
        # Partial match on dotted sources (e.g. dom.visible_text)
        for key, val in SOURCE_TIERS.items():
            if source.startswith(key.split(".")[0]):
                base = val
                break
        if base is None:
            base = SOURCE_TIERS["regex_fallback"]
    conf = base
    if agreement:
        conf = min(0.99, conf + 0.08)
    return round(conf, 2)


def wrap_field(value: Any, source: str, *, agreement: bool = False) -> dict[str, Any]:
    """Standard field envelope: {value, source, confidence}."""
    has_value = value is not None and value != "" and value != [] and value is not False
    return {
        "value": value,
        "source": source,
        "confidence": tier_confidence(source, agreement=agreement, has_value=has_value),
    }


def merge_field_results(*results: dict[str, Any]) -> dict[str, Any]:
    """Pick highest-confidence non-empty field result."""
    best: dict[str, Any] = {"value": None, "source": "none", "confidence": 0.0}
    for r in results:
        if not r:
            continue
        conf = float(r.get("confidence") or 0)
        val = r.get("value")
        has_val = val is not None and val != "" and val != [] and val is not False
        if has_val and conf >= best["confidence"]:
            best = {"value": val, "source": r.get("source") or "none", "confidence": conf}
    return best


def build_field_confidence_map(
    structured: dict[str, Any],
    field_meta: dict[str, Any] | None = None,
    pdp_signals: dict[str, Any] | None = None,
    schema_graph: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Build complete per-field confidence map for all extraction fields.

    Returns dict like:
        {"title": {"value": "...", "source": "document.title", "confidence": 0.98}, ...}
    """
    meta = field_meta or structured.get("_field_sources") or {}
    signals = pdp_signals or {}
    graph = schema_graph or signals.get("schema_graph") or {}

    fields: dict[str, dict[str, Any]] = {}

    # Core commerce fields from voter meta
    for key, voter_key in (
        ("title", "product_name"),
        ("price", "price"),
        ("brand", "brand"),
        ("review_count", "review_count"),
        ("avg_rating", "avg_rating"),
        ("compare_at_price", "compare_at_price"),
        ("inventory_quantity", "inventory_quantity"),
    ):
        val = structured.get(voter_key)
        m = meta.get(voter_key) or {}
        src = m.get("source") or "none"
        agreement = bool(m.get("agreement"))
        fields[key] = wrap_field(val, _VOTER_SOURCE_MAP.get(src, src), agreement=agreement)

    # PDP signal fields
    signal_map = (
        ("faq_count", "faq_count_confidence"),
        ("trust_badges", "trust_badges_confidence"),
        ("shipping_visible", "shipping_visible_confidence"),
        ("return_policy_visible", "return_policy_visible_confidence"),
        ("variant_count", "variant_count_confidence"),
        ("inventory", "inventory_confidence"),
    )
    for field_key, conf_key in signal_map:
        conf_data = signals.get(conf_key) or {}
        if conf_data:
            fields[field_key] = conf_data
        else:
            val = signals.get(field_key) if field_key in signals else structured.get(field_key)
            fields[field_key] = wrap_field(val, "none")

    # Schema inventory flags
    for schema_type in ("Product", "FAQPage", "Review", "AggregateRating", "BreadcrumbList", "Organization", "Offer"):
        schemas = graph.get("schemas") or {}
        entry = schemas.get(schema_type) or {}
        flag_key = f"schema_{schema_type.lower()}"
        fields[flag_key] = {
            "value": entry.get("schema_present", False),
            "source": "schema_graph",
            "confidence": entry.get("confidence", 0.0) if entry.get("schema_present") else 0.0,
            "schema_valid": entry.get("schema_valid", False),
        }

    return fields


def overall_signal_confidence(field_map: dict[str, dict[str, Any]], keys: list[str]) -> float:
    """Average confidence for a subset of fields."""
    scores = [float(field_map[k]["confidence"]) for k in keys if k in field_map and field_map[k].get("confidence")]
    return round(sum(scores) / len(scores), 2) if scores else 0.0
