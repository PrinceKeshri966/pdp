"""Tests for audit evidence builders."""
from app.core.evidence.audit_findings import (
    _classify_gallery_images,
    build_audit_evidence,
    build_check_evidence,
)


def test_classify_gallery_images_lifestyle():
    html = '''
    <img src="/a.jpg" alt="Model wearing blue jeans lifestyle shot" />
    <img src="/b.jpg" alt="Front view product on white background" />
    '''
    result = _classify_gallery_images(html, {"image_urls": ["/a.jpg", "/b.jpg"]})
    assert result["lifestyle"] >= 1
    assert result["packshot"] >= 1
    assert result["total"] == 2


def test_build_cta_above_fold_evidence():
    state = {
        "seo_report": {},
        "aeo_report": {},
        "ux_report": {"cta_analysis": {"above_fold": False, "found": True}},
        "psychology_report": {},
        "visual_ux_facts": {
            "capture_ok": True,
            "viewport_height": 900,
            "viewport_width": 1366,
            "cta_above_fold": False,
            "element_bounds": {"cta": {"x": 100, "y": 1100, "width": 200, "height": 48}},
        },
        "scrape_html": "",
        "json_structured_data": {},
    }
    payload = build_check_evidence("cta_above_fold", state)
    assert payload is not None
    assert payload["has_evidence"] is True
    assert payload["status"] == "fail"
    assert payload["evidence"]["type"] == "visual"
    assert payload["evidence"]["visual_metrics"]["distance_from_viewport_px"] == 200


def test_build_audit_evidence_includes_competitor():
    state = {
        "seo_report": {"cta_analysis": {}},
        "aeo_report": {},
        "ux_report": {"cta_analysis": {"found": True, "above_fold": True}},
        "psychology_report": {},
        "visual_ux_facts": {},
        "competitor_report": {
            "live_compare": {
                "sites": [
                    {"name": "You", "role": "you", "scrape_ok": True, "url": "https://you.com"},
                    {"name": "Comp", "role": "competitor", "scrape_ok": True, "url": "https://comp.com"},
                ],
                "rows": [
                    {
                        "label": "Reviews on page",
                        "key": "has_reviews",
                        "values": [False, True],
                        "best_index": 1,
                        "you_win": False,
                    }
                ],
            }
        },
        "json_structured_data": {},
    }
    evidence = build_audit_evidence(state)
    assert "competitor_has_reviews" in evidence
    assert evidence["competitor_has_reviews"]["has_evidence"] is True
    assert evidence["competitor_has_reviews"]["status"] == "fail"
