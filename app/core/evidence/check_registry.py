"""
Canonical CheckBadge value registry — single source of truth for UI + evidence parity.

backend check_values[checkId] == frontend CheckBadge == audit_evidence.status
"""
from __future__ import annotations

from typing import Any, Callable

from app.agents.state import state_dict
from app.core.extraction.schema_graph import parse_schema_graph

# checkId -> (resolver, canonical backend path label for validation reports)
CheckResolver = Callable[[dict[str, Any]], bool | None]


def _ctx_from_state(state: dict[str, Any]) -> dict[str, Any]:
    structured = state_dict(state, "json_structured_data")
    pdp = structured.get("_pdp_signals") or {}
    schema_graph = pdp.get("schema_graph") or parse_schema_graph(state.get("scrape_html") or "")
    return {
        "seo": state_dict(state, "seo_report"),
        "aeo": state_dict(state, "aeo_report"),
        "ux": state_dict(state, "ux_report"),
        "psych": state_dict(state, "psychology_report"),
        "dom": state.get("dom_technical_seo") or structured.get("_dom_technical_seo") or {},
        "structured": structured,
        "pdp": pdp,
        "schema_graph": schema_graph,
        "visual": state_dict(state, "visual_ux_facts"),
        "ux_facts": state_dict(state, "ux_preprocessor_facts"),
        "html": state.get("scrape_html") or "",
    }


def _schema_product(ctx: dict[str, Any]) -> bool:
    struct = ctx["seo"].get("structured_data") or {}
    aeo_struct = ctx["aeo"].get("structured_data") or {}
    dom = ctx["dom"]
    graph = ctx["schema_graph"]
    types = graph.get("detected_types") or []
    return bool(
        struct.get("has_product_schema")
        or aeo_struct.get("product_schema")
        or dom.get("product_schema_present")
        or graph.get("has_product_schema")
        or "Product" in types
    )


def _schema_breadcrumb(ctx: dict[str, Any]) -> bool:
    struct = ctx["seo"].get("structured_data") or {}
    aeo_struct = ctx["aeo"].get("structured_data") or {}
    graph = ctx["schema_graph"]
    types = graph.get("detected_types") or []
    return bool(
        struct.get("has_breadcrumb_schema")
        or aeo_struct.get("breadcrumb_schema")
        or "BreadcrumbList" in types
    )


def _schema_faq(ctx: dict[str, Any]) -> bool:
    struct = ctx["seo"].get("structured_data") or {}
    aeo_struct = ctx["aeo"].get("structured_data") or {}
    dom = ctx["dom"]
    graph = ctx["schema_graph"]
    return bool(
        aeo_struct.get("faq_schema")
        or struct.get("has_faq_schema")
        or dom.get("faq_schema_present")
        or graph.get("has_faq_schema")
        or "FAQPage" in (graph.get("detected_types") or [])
    )


def _schema_review(ctx: dict[str, Any]) -> bool:
    struct = ctx["seo"].get("structured_data") or {}
    aeo_struct = ctx["aeo"].get("structured_data") or {}
    graph = ctx["schema_graph"]
    types = graph.get("detected_types") or []
    return bool(
        aeo_struct.get("review_schema")
        or struct.get("has_review_schema")
        or "Review" in types
        or "AggregateRating" in types
    )


def resolve_check_value(check_id: str, ctx: dict[str, Any]) -> bool | None:
    """Return canonical pass/fail for a checkId, or None if not applicable."""
    seo = ctx["seo"]
    aeo = ctx["aeo"]
    ux = ctx["ux"]
    psych = ctx["psych"]
    tech = seo.get("technical_seo") or {}
    struct = seo.get("structured_data") or {}
    aeo_struct = aeo.get("structured_data") or {}
    kw = seo.get("keyword_analysis") or {}
    cq = seo.get("content_quality") or {}
    headings = seo.get("headings_structure") or {}
    meta = seo.get("meta_description") or {}
    cta = ux.get("cta_analysis") or {}
    img = ux.get("product_imagery") or {}
    trust = ux.get("trust_signals") or {}
    info = ux.get("product_information") or {}
    if info.get("applicable") is False:
        info = {}
    urgency = ux.get("urgency_scarcity") or {}
    checkout = ux.get("checkout_friction") or {}
    geo = aeo.get("geo_signals") or {}
    rag = aeo.get("rag_readiness") or {}
    aeo_cq = aeo.get("content_quality") or {}
    faq_q = aeo.get("faq_quality") or {}
    price = psych.get("pricing_psychology") or {}
    emotion = psych.get("emotional_appeal") or {}
    dom = ctx["dom"]

    mapping: dict[str, bool | None] = {
        "meta_has_cta": meta.get("has_cta"),
        "headings_logical_hierarchy": headings.get("logical_hierarchy"),
        "headings_keywords": headings.get("keyword_in_headings"),
        "kw_in_title": kw.get("in_title"),
        "kw_in_h1": kw.get("in_h1"),
        "kw_in_meta": kw.get("in_meta_description"),
        "kw_in_first_100": kw.get("in_first_100_words"),
        "content_adequate": not cq.get("thin_content") if cq.get("thin_content") is not None else None,
        "content_unique": not cq.get("duplicate_content_risk") if cq.get("duplicate_content_risk") is not None else None,
        "schema_product": _schema_product(ctx),
        "tech_canonical": tech.get("canonical_present") if tech.get("canonical_present") is not None else dom.get("canonical_present"),
        "tech_og": tech.get("open_graph_present") if tech.get("open_graph_present") is not None else dom.get("open_graph_present"),
        "tech_mobile": tech.get("mobile_friendly"),
        "tech_twitter": tech.get("twitter_card_present"),
        "tech_hreflang": tech.get("hreflang_present"),
        "tech_images_optimized": not (tech.get("page_speed_signals") or {}).get("large_images_detected") if tech.get("page_speed_signals") else None,
        "tech_lazy_loading": (tech.get("page_speed_signals") or {}).get("lazy_loading_used"),
        "tech_pagination": not tech.get("pagination_signals") if tech.get("pagination_signals") is not None else None,
        "geo_perplexity": geo.get("perplexity_citable"),
        "geo_sge": geo.get("sge_snippet_ready"),
        "geo_direct_answer": geo.get("direct_answer_format"),
        "rag_citable": rag.get("is_citable"),
        "rag_uvp": rag.get("unique_value_proposition"),
        "rag_factual": rag.get("factual_claims_present"),
        "aeo_conversational": aeo_cq.get("conversational_readiness"),
        "aeo_llm_snippet": aeo_cq.get("llm_snippet_ready"),
        "aeo_not_commodity": not aeo_cq.get("commodity_content") if aeo_cq.get("commodity_content") is not None else None,
        "aeo_unique_perspective": aeo_cq.get("has_unique_perspective"),
        "faq_schema": _schema_faq(ctx),
        "schema_breadcrumb": _schema_breadcrumb(ctx),
        "schema_review": _schema_review(ctx),
        "speakable_schema": aeo_struct.get("speakable_schema"),
        "faq_conversational": faq_q.get("conversational_format"),
        "cta_found": cta.get("found"),
        "cta_above_fold": cta.get("above_fold"),
        "cta_sticky": cta.get("sticky_on_scroll"),
        "img_angles": img.get("multiple_angles"),
        "img_zoom": img.get("zoom_capability"),
        "img_lifestyle": img.get("lifestyle_images"),
        "img_video": img.get("video_present"),
        "trust_reviews": trust.get("reviews_present"),
        "trust_rating": trust.get("rating_visible"),
        "trust_return": trust.get("return_policy_visible"),
        "trust_security": trust.get("security_badges"),
        "trust_moneyback": trust.get("money_back_guarantee"),
        "info_size_guide": info.get("size_guide_present"),
        "info_material": info.get("material_composition"),
        "info_fit": info.get("fit_description"),
        "info_specs": info.get("specifications_table"),
        "urgency_stock": urgency.get("stock_counter"),
        "urgency_limited": urgency.get("limited_time_offer"),
        "urgency_social": urgency.get("social_proof_counter"),
        "checkout_guest": checkout.get("guest_checkout_implied"),
        "checkout_one_click": checkout.get("one_click_buy"),
        "price_charm": price.get("charm_pricing_used"),
        "price_anchor": price.get("anchor_price_present"),
        "decoy_pricing": price.get("decoy_pricing_detected"),
        "peak_end_rule": price.get("peak_end_rule_applied"),
        "emotion_identity": emotion.get("identity_alignment"),
        "emotion_aspirational": emotion.get("aspirational_language"),
    }
    val = mapping.get(check_id)
    if val is None:
        return None
    return bool(val)


# Human-readable backend path for validation reports
CHECK_BACKEND_PATHS: dict[str, str] = {
    "schema_product": "canonical: seo.structured_data.has_product_schema | aeo.structured_data.product_schema | schema_graph",
    "schema_breadcrumb": "canonical: seo.structured_data.has_breadcrumb_schema | aeo.structured_data.breadcrumb_schema | schema_graph",
    "faq_schema": "canonical: aeo.structured_data.faq_schema | seo.structured_data.has_faq_schema | schema_graph",
    "schema_review": "canonical: aeo.structured_data.review_schema | seo.structured_data.has_review_schema | schema_graph",
    "cta_sticky": "ux_report.cta_analysis.sticky_on_scroll",
    "img_zoom": "ux_report.product_imagery.zoom_capability",
    "info_material": "ux_report.product_information.material_composition",
    "info_fit": "ux_report.product_information.fit_description",
    "info_specs": "ux_report.product_information.specifications_table",
    "decoy_pricing": "psychology_report.pricing_psychology.decoy_pricing_detected",
    "peak_end_rule": "psychology_report.pricing_psychology.peak_end_rule_applied",
    "emotion_identity": "psychology_report.emotional_appeal.identity_alignment",
}


ALL_CHECK_IDS = [
    "meta_has_cta", "headings_logical_hierarchy", "headings_keywords",
    "kw_in_title", "kw_in_h1", "kw_in_meta", "kw_in_first_100",
    "content_adequate", "content_unique", "schema_product",
    "tech_canonical", "tech_og", "tech_mobile", "tech_twitter", "tech_hreflang",
    "tech_images_optimized", "tech_lazy_loading", "tech_pagination",
    "geo_perplexity", "geo_sge", "geo_direct_answer",
    "rag_citable", "rag_uvp", "rag_factual",
    "aeo_conversational", "aeo_llm_snippet", "aeo_not_commodity", "aeo_unique_perspective",
    "faq_schema", "schema_breadcrumb", "schema_review", "speakable_schema", "faq_conversational",
    "cta_found", "cta_above_fold", "cta_sticky",
    "img_angles", "img_zoom", "img_lifestyle", "img_video",
    "trust_reviews", "trust_rating", "trust_return", "trust_security", "trust_moneyback",
    "info_size_guide", "info_material", "info_fit", "info_specs",
    "urgency_stock", "urgency_limited", "urgency_social",
    "checkout_guest", "checkout_one_click",
    "price_charm", "price_anchor", "decoy_pricing", "peak_end_rule",
    "emotion_identity", "emotion_aspirational",
]


def build_check_values(state: dict[str, Any]) -> dict[str, bool]:
    """Canonical checkId -> pass/fail for API + frontend."""
    ctx = _ctx_from_state(state)
    out: dict[str, bool] = {}
    for check_id in ALL_CHECK_IDS:
        val = resolve_check_value(check_id, ctx)
        if val is not None:
            out[check_id] = val
    return out


def _ensure_report_dict(state: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a mutable report dict; replaces None or non-dict values."""
    val = state.get(key)
    if not isinstance(val, dict):
        val = {}
        state[key] = val
    return val


def sync_structured_data_reports(state: dict[str, Any]) -> None:
    """Align SEO/AEO structured_data booleans so reports agree before check_values."""
    ctx = _ctx_from_state(state)
    product = _schema_product(ctx)
    breadcrumb = _schema_breadcrumb(ctx)
    faq = _schema_faq(ctx)
    review = _schema_review(ctx)

    seo = _ensure_report_dict(state, "seo_report")
    seo_struct = seo.get("structured_data")
    if not isinstance(seo_struct, dict):
        seo_struct = {}
        seo["structured_data"] = seo_struct
    seo_struct["has_product_schema"] = product
    seo_struct["has_breadcrumb_schema"] = breadcrumb
    seo_struct["has_faq_schema"] = faq
    seo_struct["has_review_schema"] = review

    aeo = _ensure_report_dict(state, "aeo_report")
    aeo_struct = aeo.get("structured_data")
    if not isinstance(aeo_struct, dict):
        aeo_struct = {}
        aeo["structured_data"] = aeo_struct
    aeo_struct["product_schema"] = product
    aeo_struct["breadcrumb_schema"] = breadcrumb
    aeo_struct["faq_schema"] = faq
    aeo_struct["review_schema"] = review
