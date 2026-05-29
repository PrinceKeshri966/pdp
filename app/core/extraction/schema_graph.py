"""
Enterprise JSON-LD graph parser — replaces regex-only schema detection.

Parses @graph nodes and nested entities to build a schema inventory with
schema_present, schema_valid, and confidence per type.
"""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

# Canonical schema types we inventory (Google Rich Results parity)
INVENTORY_TYPES = (
    "Product",
    "Review",
    "AggregateRating",
    "BreadcrumbList",
    "FAQPage",
    "Organization",
    "Offer",
    "MerchantReturnPolicy",
    "OfferShippingDetails",
)

_TYPE_ALIASES: dict[str, str] = {
    "product": "Product",
    "productgroup": "Product",
    "review": "Review",
    "aggregaterating": "AggregateRating",
    "breadcrumblist": "BreadcrumbList",
    "faqpage": "FAQPage",
    "organization": "Organization",
    "localbusiness": "Organization",
    "brand": "Organization",
    "offer": "Offer",
    "aggregateoffer": "Offer",
    "merchantreturnpolicy": "MerchantReturnPolicy",
    "offershippingdetails": "OfferShippingDetails",
}

_REQUIRED: dict[str, list[str]] = {
    "Product": ["name"],
    "Review": ["reviewRating"],
    "AggregateRating": ["ratingValue"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Organization": ["name"],
    "Offer": ["price"],
    "MerchantReturnPolicy": ["returnPolicyCategory"],
    "OfferShippingDetails": ["shippingRate"],
}

_RECOMMENDED: dict[str, list[str]] = {
    "Product": ["description", "image", "offers", "brand", "sku", "aggregateRating"],
    "Review": ["author", "reviewBody", "datePublished"],
    "AggregateRating": ["reviewCount", "ratingCount"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Organization": ["url", "logo"],
    "Offer": ["priceCurrency", "availability"],
    "MerchantReturnPolicy": ["merchantReturnDays"],
    "OfferShippingDetails": ["deliveryTime", "shippingDestination"],
}


def _normalize_type(raw: Any) -> str | None:
    if isinstance(raw, str):
        key = raw.lower().replace("schema.org/", "").strip()
        return _TYPE_ALIASES.get(key)
    if isinstance(raw, list):
        for item in raw:
            t = _normalize_type(item)
            if t:
                return t
    return None


def _field_present(node: dict[str, Any], field: str) -> bool:
    val = node.get(field)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return bool(val)
    return True


def _extract_json_ld_blocks(html: str) -> list[Any]:
    if not html:
        return []
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        re.I,
    )
    blocks: list[Any] = []
    for match in pattern.finditer(html):
        raw = unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return blocks


def _flatten_graph(data: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    """Walk @graph and nested entity references into flat node list."""
    if depth > 12:
        return []
    nodes: list[dict[str, Any]] = []
    if isinstance(data, dict):
        nodes.append(data)
        for key in (
            "@graph", "mainEntity", "hasPart", "itemListElement",
            "offers", "aggregateRating", "review", "brand", "seller",
            "shippingDetails", "hasMerchantReturnPolicy", "acceptedAnswer",
        ):
            val = data.get(key)
            if isinstance(val, list):
                for item in val:
                    nodes.extend(_flatten_graph(item, depth=depth + 1))
            elif isinstance(val, dict):
                nodes.extend(_flatten_graph(val, depth=depth + 1))
    elif isinstance(data, list):
        for item in data:
            nodes.extend(_flatten_graph(item, depth=depth + 1))
    return nodes


def _validate_node(node: dict[str, Any], schema_type: str) -> dict[str, Any]:
    required = _REQUIRED.get(schema_type, [])
    recommended = _RECOMMENDED.get(schema_type, [])
    missing_required = [f for f in required if not _field_present(node, f)]
    missing_recommended = [f for f in recommended if not _field_present(node, f)]
    present_required = len(required) - len(missing_required)
    present_recommended = len(recommended) - len(missing_recommended)
    total = len(required) + len(recommended)
    score = (
        round(((present_required * 2 + present_recommended) / max(total * 2, 1)) * 100, 1)
        if total
        else (100.0 if not missing_required else 50.0)
    )
    return {
        "schema_present": True,
        "schema_valid": len(missing_required) == 0,
        "confidence": round(min(0.98, 0.75 + score / 400), 2),
        "score": score,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "fields_found": [f for f in (required + recommended) if _field_present(node, f)],
        "raw_type": node.get("@type"),
    }


def _count_faq_questions(node: dict[str, Any]) -> int:
    """Count Question entities inside FAQPage mainEntity."""
    entities = node.get("mainEntity") or []
    if isinstance(entities, dict):
        entities = [entities]
    count = 0
    for ent in entities if isinstance(entities, list) else []:
        if not isinstance(ent, dict):
            continue
        raw_type = ent.get("@type")
        types: list[str] = []
        if isinstance(raw_type, str):
            types = [raw_type.lower()]
        elif isinstance(raw_type, list):
            types = [str(x).lower() for x in raw_type]
        if "question" in types:
            count += 1
        elif not types and (ent.get("name") or ent.get("acceptedAnswer")):
            count += 1
    return count


def _offer_availability(nodes: list[dict[str, Any]]) -> str | None:
    for node in nodes:
        t = _normalize_type(node.get("@type"))
        if t != "Offer":
            continue
        avail = node.get("availability") or ""
        avail_l = str(avail).lower()
        if "outofstock" in avail_l or "soldout" in avail_l:
            return "OutOfStock"
        if "instock" in avail_l or "preorder" in avail_l:
            return "InStock"
    # Also check Product.offers
    for node in nodes:
        if _normalize_type(node.get("@type")) != "Product":
            continue
        offers = node.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    avail = str(offer.get("availability") or "").lower()
                    if "outofstock" in avail:
                        return "OutOfStock"
                    if "instock" in avail:
                        return "InStock"
    return None


def parse_schema_graph(html: str) -> dict[str, Any]:
    """
    Parse all JSON-LD blocks into a schema inventory.

    Returns:
        detected_types: list of canonical type names
        schemas: per-type {schema_present, schema_valid, confidence, ...}
        faq_count_schema: count from FAQPage mainEntity
        offer_availability: from Offer.availability
        blocks_parsed, nodes_found
    """
    blocks = _extract_json_ld_blocks(html)
    all_nodes: list[dict[str, Any]] = []
    for block in blocks:
        all_nodes.extend(_flatten_graph(block))

    inventory: dict[str, Any] = {}
    detected: list[str] = []

    for node in all_nodes:
        schema_type = _normalize_type(node.get("@type"))
        if not schema_type or schema_type not in INVENTORY_TYPES:
            continue
        validation = _validate_node(node, schema_type)
        if schema_type not in inventory or validation["score"] > inventory[schema_type].get("score", 0):
            inventory[schema_type] = validation
        if schema_type not in detected:
            detected.append(schema_type)

    # Derive FAQ count from best FAQPage node
    faq_count_schema = 0
    for node in all_nodes:
        if _normalize_type(node.get("@type")) == "FAQPage":
            faq_count_schema = max(faq_count_schema, _count_faq_questions(node))

    offer_availability = _offer_availability(all_nodes)

    # Aggregate booleans for downstream preprocessors
    flags = {
        "has_product_schema": "Product" in detected,
        "has_faq_schema": "FAQPage" in detected,
        "has_review_schema": "Review" in detected or "AggregateRating" in detected,
        "has_breadcrumb_schema": "BreadcrumbList" in detected,
        "has_organization_schema": "Organization" in detected,
        "has_offer_schema": "Offer" in detected,
        "has_return_policy_schema": "MerchantReturnPolicy" in detected,
        "has_shipping_schema": "OfferShippingDetails" in detected,
    }

    overall = (
        round(sum(v["confidence"] for v in inventory.values()) / len(inventory), 2)
        if inventory
        else 0.0
    )

    return {
        "detected_types": detected,
        "schemas": inventory,
        "overall_confidence": overall,
        "blocks_parsed": len(blocks),
        "nodes_found": len(all_nodes),
        "faq_count_schema": faq_count_schema,
        "offer_availability": offer_availability,
        **flags,
    }


def schema_flags_for_seo(html: str) -> dict[str, Any]:
    """Lightweight schema flags for seo_preprocessor (graph-based, not regex)."""
    graph = parse_schema_graph(html)
    return {
        "detected": bool(graph["detected_types"]),
        "types": graph["detected_types"],
        "has_product_schema": graph["has_product_schema"],
        "has_faq_schema": graph["has_faq_schema"],
        "has_review_schema": graph["has_review_schema"],
        "has_breadcrumb_schema": graph["has_breadcrumb_schema"],
        "schema_inventory": graph["schemas"],
        "schema_confidence": graph["overall_confidence"],
    }
