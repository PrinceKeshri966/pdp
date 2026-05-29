"""
Parse and validate schema.org JSON-LD markup (Product, FAQ, Review, Breadcrumb, Organization).

Delegates graph parsing to schema_graph.py for enterprise-grade JSON-LD inventory.
"""
from __future__ import annotations

from typing import Any

from app.core.extraction.schema_graph import INVENTORY_TYPES, parse_schema_graph


def validate_schema_markup(html: str) -> dict[str, Any]:
    """Parse all JSON-LD blocks and validate target schema types."""
    graph = parse_schema_graph(html)

    # Map graph inventory to legacy validator shape
    results: dict[str, Any] = {}
    for schema_type, entry in (graph.get("schemas") or {}).items():
        results[schema_type] = {
            "type": schema_type,
            "valid": entry.get("schema_valid", False),
            "score": entry.get("score", 0),
            "confidence": entry.get("confidence", 0),
            "missing_required": entry.get("missing_required", []),
            "missing_recommended": entry.get("missing_recommended", []),
            "fields_found": entry.get("fields_found", []),
            "raw_type": entry.get("raw_type"),
            "schema_present": entry.get("schema_present", True),
            "schema_valid": entry.get("schema_valid", False),
        }

    detected = graph.get("detected_types") or []
    overall_score = (
        round(sum(r["score"] for r in results.values()) / len(results), 1)
        if results
        else 0.0
    )

    return {
        "detected_types": detected,
        "inventory_types": list(INVENTORY_TYPES),
        "schemas": results,
        "overall_score": overall_score,
        "overall_confidence": graph.get("overall_confidence") or round(min(1.0, overall_score / 100), 2),
        "blocks_parsed": graph.get("blocks_parsed", 0),
        "nodes_found": graph.get("nodes_found", 0),
        "faq_count_schema": graph.get("faq_count_schema", 0),
        "offer_availability": graph.get("offer_availability"),
        "has_product_schema": graph.get("has_product_schema", False),
        "has_faq_schema": graph.get("has_faq_schema", False),
        "has_review_schema": graph.get("has_review_schema", False),
        "has_breadcrumb_schema": graph.get("has_breadcrumb_schema", False),
        "has_offer_schema": graph.get("has_offer_schema", False),
        "has_return_policy_schema": graph.get("has_return_policy_schema", False),
        "has_shipping_schema": graph.get("has_shipping_schema", False),
    }
