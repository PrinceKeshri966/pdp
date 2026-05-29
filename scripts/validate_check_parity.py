#!/usr/bin/env python3
"""Validate CheckBadge parity: backend check_values == evidence.status == frontend resolver."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.evidence.audit_findings import build_audit_evidence
from app.core.evidence.check_registry import ALL_CHECK_IDS, build_check_values, sync_structured_data_reports


def _frontend_resolve(check_id: str, check_values: dict[str, bool]) -> bool | None:
    """Simulates frontend resolveCheckValue(checkId, result)."""
    if check_id in check_values:
        return check_values[check_id]
    return None


def validate_state(state: dict) -> list[dict]:
    sync_structured_data_reports(state)
    check_values = build_check_values(state)
    evidence = build_audit_evidence(state)
    rows: list[dict] = []
    for check_id in ALL_CHECK_IDS:
        backend = check_values.get(check_id)
        if backend is None:
            continue
        ev = evidence.get(check_id) or {}
        ev_status = ev.get("status")
        ev_bool = ev_status == "pass" if ev_status else None
        frontend = _frontend_resolve(check_id, check_values)
        ok = backend == frontend == ev_bool
        rows.append({
            "checkId": check_id,
            "backend_value": backend,
            "frontend_value": frontend,
            "evidence_value": ev_bool,
            "status": "PASS" if ok else "FAIL",
        })
    return rows


def _sample_state() -> dict:
    """Representative state covering schema, UX, psych checks."""
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Test","offers":{"price":"999"}}
    </script>
    <script type="application/ld+json">
    {"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Home"}]}
    </script>
    </head><body>
    <button class="btn">Add to Cart</button>
    <div class="product-zoom" data-zoom="true"></div>
    <p>Material: 100% cotton. Regular fit. Specifications table below.</p>
    <table class="specifications"><tr><td>Weight</td><td>200g</td></tr></table>
    <details class="faq"><summary>What is this?</summary></details>
    <p>4.5 stars · 120 reviews</p>
    <footer>Free returns · 30 day return policy</footer>
    </body></html>
    """
    return {
        "scrape_html": html,
        "source_url": "https://example.com/products/test",
        "json_structured_data": {
            "product_name": "Test Product",
            "price": "999",
            "original_price": "1299",
            "images_count": 4,
            "image_urls": ["/a.jpg", "/b-lifestyle.jpg"],
            "has_reviews": True,
            "review_count": 120,
            "avg_rating": 4.5,
            "has_size_guide": True,
            "_pdp_signals": {},
        },
        "seo_report": {
            "meta_description": {"has_cta": True, "value": "Shop now"},
            "headings_structure": {"logical_hierarchy": True, "keyword_in_headings": True},
            "keyword_analysis": {"in_title": True, "in_h1": True, "in_meta_description": True, "in_first_100_words": True},
            "content_quality": {"thin_content": False, "duplicate_content_risk": False},
            "structured_data": {"has_product_schema": True, "has_breadcrumb_schema": True, "has_faq_schema": False},
            "technical_seo": {
                "canonical_present": True,
                "open_graph_present": True,
                "mobile_friendly": True,
                "twitter_card_present": False,
                "hreflang_present": False,
                "pagination_signals": False,
                "page_speed_signals": {"large_images_detected": False, "lazy_loading_used": True},
            },
        },
        "aeo_report": {
            "structured_data": {"product_schema": True, "breadcrumb_schema": True, "faq_schema": False, "review_schema": True, "speakable_schema": False},
            "faq_quality": {"conversational_format": False},
            "geo_signals": {"perplexity_citable": True, "sge_snippet_ready": False, "direct_answer_format": True},
            "rag_readiness": {"is_citable": True, "unique_value_proposition": True, "factual_claims_present": True},
            "content_quality": {"conversational_readiness": True, "llm_snippet_ready": False, "commodity_content": False, "has_unique_perspective": True},
        },
        "ux_report": {
            "cta_analysis": {"found": True, "above_fold": True, "sticky_on_scroll": True},
            "product_imagery": {"multiple_angles": True, "zoom_capability": True, "lifestyle_images": True, "video_present": False},
            "trust_signals": {"reviews_present": True, "rating_visible": True, "return_policy_visible": True, "security_badges": True, "money_back_guarantee": True},
            "product_information": {"size_guide_present": True, "material_composition": True, "fit_description": True, "specifications_table": True},
            "urgency_scarcity": {"stock_counter": False, "limited_time_offer": False, "social_proof_counter": True},
            "checkout_friction": {"guest_checkout_implied": False, "one_click_buy": False},
        },
        "psychology_report": {
            "pricing_psychology": {"charm_pricing_used": True, "anchor_price_present": True, "decoy_pricing_detected": True, "peak_end_rule_applied": True},
            "emotional_appeal": {"identity_alignment": True, "aspirational_language": True},
        },
        "visual_ux_facts": {"capture_ok": True, "sticky_cta_detected": True, "cta_above_fold": True, "viewport_height": 900, "element_bounds": {"cta": {"x": 100, "y": 200, "width": 180, "height": 44}}},
        "ux_preprocessor_facts": {"cta_candidates": ["Add to Cart"], "cta_count": 1},
    }


def main() -> int:
    state = _sample_state()
    rows = validate_state(state)
    passed = sum(1 for r in rows if r["status"] == "PASS")
    total = len(rows)
    pct = (passed / total * 100) if total else 0

    print("\n## CheckBadge Parity Validation\n")
    print(f"| checkId | backend | frontend | evidence | status |")
    print(f"|---------|---------|----------|----------|--------|")
    for r in rows:
        b = "✓" if r["backend_value"] else "✗"
        f = "✓" if r["frontend_value"] else "✗"
        e = "✓" if r["evidence_value"] else "✗"
        print(f"| `{r['checkId']}` | {b} | {f} | {e} | {r['status']} |")

    print(f"\n**Parity: {passed}/{total} ({pct:.1f}%)**\n")

    out = ROOT / "exports" / "check_parity_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"parity_pct": pct, "rows": rows}, indent=2), encoding="utf-8")
    print(f"Saved: {out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
