"""Tests for check registry parity."""
from app.core.evidence.audit_findings import build_audit_evidence
from app.core.evidence.check_registry import build_check_values, resolve_check_value, sync_structured_data_reports


def test_sync_structured_data_reports_null_reports():
    """LangGraph state may hold seo_report/aeo_report keys with None values."""
    state = {
        "seo_report": None,
        "aeo_report": None,
        "json_structured_data": {},
        "scrape_html": "",
    }
    sync_structured_data_reports(state)
    assert isinstance(state["seo_report"], dict)
    assert isinstance(state["aeo_report"], dict)
    assert "structured_data" in state["seo_report"]
    assert "structured_data" in state["aeo_report"]


def test_schema_product_breadcrumb_unified():
    state = {
        "scrape_html": '<script type="application/ld+json">{"@type":"Product","name":"X"}</script>'
        '<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[]}</script>',
        "seo_report": {"structured_data": {"has_product_schema": False, "has_breadcrumb_schema": False}},
        "aeo_report": {"structured_data": {"product_schema": False, "breadcrumb_schema": False}},
        "ux_report": {},
        "psychology_report": {},
        "json_structured_data": {},
    }
    sync_structured_data_reports(state)
    cv = build_check_values(state)
    assert cv["schema_product"] is True
    assert cv["schema_breadcrumb"] is True
    assert state["seo_report"]["structured_data"]["has_product_schema"] is True
    assert state["aeo_report"]["structured_data"]["breadcrumb_schema"] is True


def test_check_evidence_status_matches_check_values():
    state = {
        "scrape_html": "",
        "seo_report": {
            "meta_description": {"has_cta": True},
            "structured_data": {"has_product_schema": True},
            "technical_seo": {"canonical_present": True},
            "keyword_analysis": {},
            "content_quality": {},
            "headings_structure": {},
        },
        "aeo_report": {"structured_data": {}, "faq_quality": {}, "geo_signals": {}, "rag_readiness": {}, "content_quality": {}},
        "ux_report": {
            "cta_analysis": {"found": True, "above_fold": True, "sticky_on_scroll": False},
            "product_imagery": {"multiple_angles": True, "zoom_capability": True, "lifestyle_images": False, "video_present": False},
            "trust_signals": {"reviews_present": True, "rating_visible": True, "return_policy_visible": True, "security_badges": False, "money_back_guarantee": False},
            "product_information": {"size_guide_present": True, "material_composition": True, "fit_description": False, "specifications_table": True},
            "urgency_scarcity": {},
            "checkout_friction": {},
        },
        "psychology_report": {
            "pricing_psychology": {"charm_pricing_used": True, "anchor_price_present": False, "decoy_pricing_detected": True, "peak_end_rule_applied": False},
            "emotional_appeal": {"identity_alignment": True, "aspirational_language": False},
        },
        "json_structured_data": {"avg_rating": 4.2, "review_count": 10},
        "visual_ux_facts": {},
        "ux_preprocessor_facts": {"cta_candidates": ["Buy Now"], "cta_count": 1},
    }
    sync_structured_data_reports(state)
    check_values = build_check_values(state)
    evidence = build_audit_evidence(state)
    for check_id, backend_val in check_values.items():
        ev = evidence.get(check_id)
        if not ev:
            continue
        assert ev["status"] == ("pass" if backend_val else "fail"), check_id
        ctx = __import__("app.core.evidence.check_registry", fromlist=["_ctx_from_state"])._ctx_from_state(state)
        assert resolve_check_value(check_id, ctx) == backend_val
