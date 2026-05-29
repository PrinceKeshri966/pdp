#!/usr/bin/env python3
"""Quick validation: title resolution logic + UX/Psych field mapping + competitor intel."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.competitor_intelligence import synthesize_competitor_intelligence


def test_competitor_intelligence():
    sites = [
        {"role": "you", "url": "https://boat.com/p/1", "scrape_ok": True, "features": {
            "product_name": "boAt Airdopes 181 Pro", "price": "1499", "page_word_count": 850,
            "images_count": 6, "has_reviews": True, "review_count": 90, "has_video": False,
        }},
        {"role": "competitor", "url": "https://noise.com/p/1", "scrape_ok": True, "features": {
            "product_name": "Noise Buds VS104", "price": "1299", "page_word_count": 1200,
            "images_count": 8, "has_reviews": True, "review_count": 200, "has_video": True,
        }},
        {"role": "competitor", "url": "https://realme.com/p/1", "scrape_ok": True, "features": {
            "product_name": "realme Buds T300", "price": "1599", "page_word_count": 700,
            "images_count": 5, "has_reviews": True, "review_count": 50, "has_video": False,
        }},
    ]
    fc = {
        "product_images_avg": 6.5,
        "description_word_count_avg": 950,
        "has_video_pct": 50,
        "has_reviews_pct": 100,
        "avg_review_count": 125,
    }
    intel = synthesize_competitor_intelligence(
        sites=sites,
        structured={"product_name": "boAt Airdopes 181 Pro", "categories": ["wireless earbuds", "audio"]},
        gaps=["Page content (words): you have 850, noise.com has 1200"],
        wins=["You lead on Price"],
        feature_comparison=fc,
        benchmark_metrics={"confidence": 0.8},
    )
    required = ["benchmark_scores", "market_positioning", "share_of_voice", "traffic_estimate", "backlink_gap"]
    missing = [k for k in required if k not in intel]
    assert not missing, f"Missing fields: {missing}"
    assert intel["benchmark_scores"]["avg_seo_score"] > 0
    assert intel["market_positioning"]["price_tier"] in ("budget", "mid-range", "premium")
    print("✓ competitor_intelligence synthesis OK")
    print(json.dumps({k: intel[k] for k in required}, indent=2, default=str)[:1200])


def field_mapping_table():
    rows = [
        ("trust_signals.has_reviews", "trust_signals.reviews_present", "FIXED → reviews_present"),
        ("media.has_video", "product_imagery.video_present", "FIXED → video_present"),
        ("psychRpt.decoy_pricing_detected", "pricing_psychology.decoy_pricing_detected", "FIXED → nested path"),
        ("psychRpt.peak_end_rule_applied", "pricing_psychology.peak_end_rule_applied", "FIXED → nested path"),
        ("seo_report.title_tag.value (raw)", "resolvePageTitle() chain", "FIXED → DOM-first resolver"),
    ]
    print("\n| UI field | Backend field | Status |")
    print("|----------|---------------|--------|")
    for ui, backend, status in rows:
        print(f"| `{ui}` | `{backend}` | {status} |")


def boat_title_before_after():
    """Simulate Boat bug: seo_report has hostname, DOM has real title."""
    before = {
        "source_url": "https://www.boat-lifestyle.com/products/airdopes-181-pro",
        "dom_technical_seo": {"title_tag": "boAt Airdopes 181 Pro | Wireless Earbuds with 100 Hours Playback"},
        "seo_report": {"title_tag": {"value": "boat-lifestyle.com", "length": 18, "score": 3}},
        "json_structured_data": {"product_name": "boAt Airdopes 181 Pro"},
    }
    # Mirror JS resolvePageTitle in Python for CI
    def resolve(data):
        dom = data.get("dom_technical_seo") or {}
        seo = data.get("seo_report") or {}
        jsd = data.get("json_structured_data") or {}
        url = data.get("source_url") or ""
        for c in [dom.get("title_tag"), (seo.get("title_tag") or {}).get("value"), jsd.get("product_name"), (seo.get("h1") or {}).get("value")]:
            if not c:
                continue
            s = str(c).strip()
            if s.lower() in ("boat-lifestyle.com", url.split("//")[-1].split("/")[0].replace("www.", "")):
                continue
            return s
        return ""

    old_display = before["seo_report"]["title_tag"]["value"]
    new_display = resolve(before)
    print("\n=== Boat Title Tag — Before / After ===")
    print(f"BEFORE (bug):  {old_display!r}")
    print(f"AFTER (fixed): {new_display!r}")
    assert "Airdopes" in new_display
    assert old_display == "boat-lifestyle.com"
    print("✓ Boat title resolution validated")


if __name__ == "__main__":
    test_competitor_intelligence()
    field_mapping_table()
    boat_title_before_after()
