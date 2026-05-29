#!/usr/bin/env python3
"""Validate UI ↔ PDF parity using buildFullPdfReportData (via Node runner)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.evidence.audit_findings import build_audit_evidence
from app.core.evidence.check_registry import build_check_values, sync_structured_data_reports


def build_sample_audit() -> dict:
    """Representative mode1 result covering all five export tabs."""
    html = """
    <html><head>
    <title>Sample Wireless Earbuds | Brand Store</title>
    <meta name="description" content="Buy premium earbuds with free shipping. Add to cart today.">
    <script type="application/ld+json">
    {"@type":"Product","name":"Sample Earbuds","offers":{"price":"999"},"aggregateRating":{"ratingValue":"4.5","reviewCount":"120"}}
    </script>
    <script type="application/ld+json">
    {"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Home"}]}
    </script>
    <script type="application/ld+json">
    {"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"What is battery life?"}]}
    </script>
    </head><body>
    <h1>Sample Wireless Earbuds Pro</h1>
    <button class="btn sticky-cta">Add to Cart</button>
    <div class="product-zoom" data-zoom="true"></div>
    <p>Material: 100% cotton. Regular fit. Specifications table below.</p>
    <table class="specifications"><tr><td>Weight</td><td>200g</td></tr></table>
    <details class="faq"><summary>What is this?</summary><p>Great earbuds.</p></details>
    <p>4.5 stars · 120 reviews · Only 3 left in stock</p>
    <footer>Free returns · 30 day return policy · Secure checkout</footer>
    </body></html>
    """
    state: dict = {
        "source_url": "https://example.com/products/sample-earbuds",
        "scrape_html": html,
        "dom_technical_seo": {
            "title_tag": "Sample Wireless Earbuds | Brand Store",
            "meta_description": "Buy premium earbuds with free shipping. Add to cart today.",
            "canonical_present": True,
            "open_graph_present": True,
        },
        "json_structured_data": {
            "product_name": "Sample Wireless Earbuds Pro",
            "price": "999",
            "original_price": "1299",
            "page_word_count": 850,
            "review_count": 120,
            "images_count": 4,
            "has_reviews": True,
            "avg_rating": 4.5,
            "has_size_guide": True,
        },
        "seo_report": {
            "overall_seo_score": 7.2,
            "title_tag": {"score": 8, "value": "Sample Wireless Earbuds | Brand Store", "length": 42},
            "meta_description": {"score": 7, "value": "Buy premium earbuds with free shipping. Add to cart today.", "length": 58, "has_cta": True},
            "h1": {"score": 9, "value": "Sample Wireless Earbuds Pro"},
            "headings_structure": {"score": 7, "h2_count": 3, "h3_count": 2, "logical_hierarchy": True, "keyword_in_headings": True},
            "keyword_analysis": {
                "score": 6, "primary_keyword": "wireless earbuds", "density_pct": 1.2,
                "in_title": True, "in_h1": True, "in_meta_description": True, "in_first_100_words": True,
            },
            "content_quality": {"score": 7, "word_count": 850, "readability": "good", "thin_content": False, "duplicate_content_risk": False},
            "image_seo": {"total_images": 6, "missing_alt": 1},
            "links": {"internal_count": 12, "external_count": 2},
            "structured_data": {"has_product_schema": True},
            "technical_seo": {
                "score": 8, "canonical_present": True, "open_graph_present": True, "mobile_friendly": True,
                "twitter_card_present": True, "hreflang_present": False,
                "core_web_vitals_risk": "low",
                "page_speed_signals": {"large_images_detected": False, "lazy_loading_used": True, "estimated_lcp_risk": "low"},
                "pagination_signals": False,
            },
            "top_issues": ["Missing hreflang for international SEO"],
            "quick_wins": ["Add FAQ schema for rich results"],
            "recommendations": ["Improve keyword density in H2 headings"],
        },
        "aeo_report": {
            "ai_visibility_score": 6.8,
            "eeat_score": {"overall": 7, "experience": 6, "expertise": 7, "authoritativeness": 6, "trustworthiness": 8, "signals_missing": ["Author bio"]},
            "geo_score": 6,
            "geo_signals": {"perplexity_citable": True, "sge_snippet_ready": True, "direct_answer_format": False},
            "rag_readiness": {"score": 7, "is_citable": True, "unique_value_proposition": True, "factual_claims_present": True, "issues": ["Add more citable statistics"]},
            "faq_quality": {"score": 6, "conversational_format": True},
            "structured_data": {"score": 8, "product_schema": True, "faq_schema": True, "breadcrumb_schema": True, "review_schema": True, "speakable_schema": False},
            "content_quality": {"score": 7, "content_depth": "adequate", "conversational_readiness": True, "llm_snippet_ready": True, "commodity_content": False, "has_unique_perspective": True},
            "gaps": ["Missing speakable schema for voice assistants"],
            "top_ai_queries_missed": ["best wireless earbuds under 1000", "earbuds battery life comparison"],
            "quick_wins_for_ai": ["Add FAQ with conversational answers"],
            "recommendations": ["Include expert review quotes"],
        },
        "ux_report": {
            "conversion_score": 7.5,
            "cta_analysis": {"score": 8, "found": True, "above_fold": True, "sticky_on_scroll": True, "text_quality": "good", "color_contrast": "adequate"},
            "product_imagery": {"score": 7, "multiple_angles": True, "zoom_capability": True, "lifestyle_images": True, "video_present": False},
            "trust_signals": {"score": 8, "reviews_present": True, "rating_visible": True, "return_policy_visible": True, "security_badges": True, "money_back_guarantee": False},
            "product_information": {"score": 7, "size_guide_present": True, "material_composition": True, "fit_description": True, "specifications_table": True},
            "urgency_scarcity": {"score": 6, "stock_counter": True, "limited_time_offer": False, "social_proof_counter": True},
            "mobile_ux": {"score": 7, "issues": ["CTA slightly small on mobile"]},
            "page_layout": {"score": 8, "above_fold_content": "excellent", "visual_hierarchy": "good", "whitespace_usage": "adequate"},
            "checkout_friction": {"cart_abandonment_risk": "medium", "guest_checkout_implied": True, "one_click_buy": False},
            "friction_points": ["No one-click buy option"],
            "recommendations": ["Add product video", "Enable express checkout"],
        },
        "psychology_report": {
            "overall_psychology_score": 6.9,
            "fogg_model": {"motivation_score": 7, "ability_score": 8, "prompt_score": 6, "behavior_likelihood": "medium"},
            "cialdini_principles": {
                "reciprocity": {"present": True, "score": 6},
                "commitment": {"present": False, "score": 3},
                "social_proof": {"present": True, "score": 8},
                "authority": {"present": False, "score": 4},
                "liking": {"present": True, "score": 7},
                "scarcity": {"present": True, "score": 6},
                "unity": {"present": False, "score": 3},
            },
            "current_triggers_found": ["Social proof", "Scarcity", "Reviews"],
            "missing_triggers": ["Authority badge", "Community identity"],
            "recommended_triggers": [
                {"trigger": "Expert endorsement", "expected_cvr_lift": "+8-12%", "implementation": "Add press logos above fold", "psychology_principle": "Authority"},
            ],
            "pricing_psychology": {
                "current_price_display": "₹999",
                "charm_pricing_used": True,
                "anchor_price_present": True,
                "decoy_pricing_detected": False,
                "peak_end_rule_applied": True,
                "suggestion": "Show was-price more prominently",
            },
            "emotional_appeal": {"current_level": "moderate", "identity_alignment": True, "aspirational_language": False, "suggestions": ["Use lifestyle imagery copy"]},
            "trust_building": {"current_level": "good", "suggestions": ["Add money-back guarantee badge"]},
        },
        "competitor_report": {
            "data_source": "live_scrape",
            "market_positioning": {
                "price_tier": "mid-range",
                "market_maturity": "growth",
                "target_segment": "Young professionals",
                "differentiation": "Long battery life",
                "price_positioning_index": 0.95,
            },
            "benchmark_scores": {
                "avg_seo_score": 6.5,
                "avg_ai_visibility_score": 5.8,
                "avg_conversion_score": 7.0,
                "avg_content_depth_score": 6.2,
            },
            "feature_comparison": {
                "product_images_avg": "4.2",
                "has_video_pct": 45,
                "has_size_guide_pct": 60,
                "has_reviews_pct": 85,
                "description_word_count_avg": 720,
                "avg_review_count": 95,
            },
            "live_compare": {
                "compare_page_type": "product",
                "metrics_note": "Live HTML per URL at audit time.",
                "sites": [
                    {"role": "you", "name": "You", "url": "https://example.com/products/sample-earbuds", "scrape_ok": True, "features": {"product_name": "Sample Earbuds", "price": "₹999"}},
                    {"role": "competitor", "name": "Competitor A", "url": "https://comp-a.com/p/1", "scrape_ok": True, "features": {"product_name": "Comp A Buds", "price": "₹1099"}},
                    {"role": "competitor", "name": "Competitor B", "url": "https://comp-b.com/p/2", "scrape_ok": True, "features": {"product_name": "Comp B Pods", "price": "₹899"}},
                ],
                "rows": [
                    {"key": "page_word_count", "label": "Words on this page", "values": [850, 720, 910], "you_win": False, "best_index": 2},
                    {"key": "has_reviews", "label": "Customer reviews", "values": [True, True, False], "you_win": True, "best_index": 0},
                    {"key": "has_video", "label": "Product video", "values": [False, True, True], "you_win": False, "best_index": 1},
                ],
            },
            "your_gaps_vs_competitors": ["Missing product video", "Lower word count than leader"],
            "winning_patterns": ["Strong review count", "Clear CTA above fold"],
            "opportunities": ["Add comparison table", "Highlight battery life vs competitors"],
            "first_mover_opportunities": ["Interactive 360° product view"],
            "category_best_practices": ["Show trust badges near CTA", "Include size/fit guide for wearables"],
            "share_of_voice": {"estimated_keyword_overlap_pct": 42, "top_shared_keywords": ["wireless earbuds", "bluetooth earbuds"]},
            "traffic_estimate": {"your_tier": "medium", "competitor_avg_tier": "high", "gap_assessment": "Competitors have stronger domain authority"},
            "backlink_gap": {"your_authority_estimate": "medium", "competitor_avg_authority": "high", "recommendation": "Build category backlinks via reviews"},
        },
        "final_diagnosis": {
            "overall_health_score": 7.1,
            "score_breakdown": {"competitor_position": 6.8},
        },
        "autofix_report": {
            "priority_action_plan": [{"action": "Add FAQ schema"}],
            "suggested_h2s": ["Battery Life & Performance"],
        },
        "audit_reliability": {
            "report_reliability": "high",
            "scrape_quality": "good",
            "extraction_confidence": 0.88,
            "extraction_confidence_pct": 88,
            "platform": "shopify",
            "page_type": "product",
        },
        "visual_ux_facts": {},
        "ux_preprocessor_facts": {"cta_candidates": ["Add to Cart"], "cta_count": 1},
    }
    sync_structured_data_reports(state)
    check_values = build_check_values(state)
    audit_evidence = build_audit_evidence(state)
    state["audit_reliability"] = {
        **state["audit_reliability"],
        "check_values": check_values,
        "audit_evidence": audit_evidence,
    }
    return state


def main() -> int:
    sample = build_sample_audit()
    sample_path = ROOT / "exports" / "pdf_parity_sample.json"
    report_path = ROOT / "exports" / "pdf_parity_report.json"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_path.write_text(json.dumps(sample, indent=2), encoding="utf-8")

    runner = ROOT / "scripts" / "run_pdf_parity.node.cjs"
    try:
        proc = subprocess.run(
            ["node", str(runner), str(sample_path), str(report_path)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
    except FileNotFoundError:
        print("ERROR: Node.js required for PDF parity validation. Install Node or run in browser.", file=sys.stderr)
        return 2

    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    if proc.returncode != 0 and not report_path.exists():
        print("PDF parity validation failed.", file=sys.stderr)
        return proc.returncode or 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    s = report["summary"]
    print("\n=== UI ↔ PDF Parity Report ===")
    print(f"UI field count:   {s['uiFieldCount']}")
    print(f"PDF field count:  {s['pdfFieldCount']}")
    print(f"Coverage:         {s['coveragePct']}% (target > {s['targetCoverage']}%)")
    print(f"Value matches:    {s['valueMatches']}/{s['pdfFieldCount']} ({s['valueMatchPct']}%)")
    print(f"Target met:       {'YES' if s['targetMet'] else 'NO'}")
    print("\nBy tab:")
    for tab, stats in report.get("byTab", {}).items():
        if tab == "OVERVIEW":
            continue
        print(f"  {tab}: {stats['pdfFieldCount']}/{stats['uiFieldCount']} ({stats['coveragePct']}%)")
    if report.get("valueMismatches"):
        print(f"\nValue mismatches: {len(report['valueMismatches'])}")
        for m in report["valueMismatches"][:5]:
            print(f"  - {m['id']}: UI={m['uiValue']!r} PDF={m['pdfValue']!r}")
    return 0 if s["targetMet"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
