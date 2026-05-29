"""
Deterministic AEO (Answer Engine Optimization) signal extraction — no LLM.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any

from app.core.extraction.pdp_signals import extract_faq
from app.core.extraction.schema_graph import parse_schema_graph

_DISCOUNT_RE = re.compile(r"(\d{1,2})\s*%\s*off", re.I)
_SPEAKABLE_RE = re.compile(r'["\']@type["\']\s*:\s*["\']SpeakableSpecification["\']', re.I)
_ENTITY_RE = re.compile(
    r"\b(brand|manufacturer|model|sku|gtin|mpn|material|dimensions?|weight|"
    r"ingredients?|warranty|certification|made in|origin)\b",
    re.I,
)
_ANSWERABILITY_RE = re.compile(
    r"\b(how to|what is|why|when|where|which|can i|does it|is it|"
    r"benefits?|features?|specifications?|faq|frequently asked)\b",
    re.I,
)


def _visible_text(html: str, markdown: str) -> str:
    if html:
        t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
        t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        return unescape(re.sub(r"\s+", " ", t)).strip()
    return (markdown or "")[:8000]


def extract_aeo_facts(
    *,
    html: str = "",
    markdown: str = "",
    structured: dict[str, Any] | None = None,
    seo_facts: dict[str, Any] | None = None,
    browser_capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract deterministic AEO signals for scoring."""
    structured = structured or {}
    seo_facts = seo_facts or {}
    browser = browser_capture or {}
    text = _visible_text(html, markdown)
    text_l = text.lower()
    html_l = (html or "").lower()

    schema_val = browser.get("schema_validation") or {}
    detected_types = schema_val.get("detected_types") or []
    seo_schema = (seo_facts.get("structured_data") or {})

    # JSON-LD graph parsing (replaces regex-only schema detection)
    pdp_signals = structured.get("_pdp_signals") or {}
    schema_graph = pdp_signals.get("schema_graph") or parse_schema_graph(html or "")

    faq_schema = bool(
        seo_schema.get("has_faq_schema")
        or schema_graph.get("has_faq_schema")
        or "FAQPage" in detected_types
    )
    product_schema = bool(
        seo_schema.get("has_product_schema")
        or schema_graph.get("has_product_schema")
        or "Product" in detected_types
    )
    review_schema = bool(
        seo_schema.get("has_review_schema")
        or schema_graph.get("has_review_schema")
        or "Review" in detected_types
        or "AggregateRating" in detected_types
    )
    breadcrumb_schema = bool(
        seo_schema.get("has_breadcrumb_schema")
        or schema_graph.get("has_breadcrumb_schema")
        or "BreadcrumbList" in detected_types
    )
    speakable_schema = bool(_SPEAKABLE_RE.search(html_l))

    # Enterprise FAQ extraction: schema > accordion > Q/A pairs
    faq_result = extract_faq(html or "", schema_graph=schema_graph)
    faq_count = int(faq_result.value or 0)
    faq_confidence = faq_result.to_dict()

    entities = list(dict.fromkeys(_ENTITY_RE.findall(text_l)))[:12]
    entity_hits = sum(1 for e in entities if e in text_l)
    answerability_hits = len(_ANSWERABILITY_RE.findall(text_l))
    word_count = len(text.split())

    # Coverage ratios (0-1)
    entity_coverage = min(1.0, entity_hits / 6) if entities else 0.2
    answerability_coverage = min(1.0, answerability_hits / 8) if word_count > 50 else 0.1

    structured_data_score = 3.0
    if product_schema:
        structured_data_score += 2.5
    if faq_schema:
        structured_data_score += 2.0
    if review_schema:
        structured_data_score += 1.5
    if speakable_schema:
        structured_data_score += 1.0
    structured_data_score = min(10.0, structured_data_score)

    faq_score = 2.0
    if faq_count >= 5:
        faq_score = 9.0
    elif faq_count >= 3:
        faq_score = 7.5
    elif faq_count >= 1:
        faq_score = 6.0
    if faq_schema:
        faq_score = min(10.0, faq_score + 1.0)

    deterministic_aeo_score = min(10.0, (
        structured_data_score * 0.35
        + faq_score * 0.25
        + entity_coverage * 10 * 0.2
        + answerability_coverage * 10 * 0.2
    ))

    return {
        "faq_count": faq_count,
        "faq_count_confidence": faq_confidence,
        "faq_schema": faq_schema,
        "product_schema": product_schema,
        "breadcrumb_schema": breadcrumb_schema,
        "review_schema": review_schema,
        "speakable_schema": speakable_schema,
        "schema_graph": {
            "detected_types": schema_graph.get("detected_types") or [],
            "overall_confidence": schema_graph.get("overall_confidence") or 0.0,
        },
        "entity_coverage": round(entity_coverage, 2),
        "answerability_coverage": round(answerability_coverage, 2),
        "entities_detected": entities[:8],
        "structured_data_score": round(structured_data_score, 1),
        "faq_score": round(faq_score, 1),
        "deterministic_aeo_score": round(deterministic_aeo_score, 1),
        "content_word_count": word_count,
        "has_brand_in_content": bool(structured.get("brand") or structured.get("vendor")),
        "_deterministic": True,
    }
