"""
Deterministic scoring engine — base scores from facts, LLM provides modifiers only.
"""
from __future__ import annotations

from typing import Any


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, round(v, 1)))


def compute_deterministic_scores(
    *,
    seo_facts: dict[str, Any] | None = None,
    seo_report: dict[str, Any] | None = None,
    ux_facts: dict[str, Any] | None = None,
    aeo_facts: dict[str, Any] | None = None,
    aeo_report: dict[str, Any] | None = None,
    psych_facts: dict[str, Any] | None = None,
    scrape_validation: dict[str, Any] | None = None,
    extraction_confidence: dict[str, Any] | None = None,
    page_type: str | None = None,
    visual_ux_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute SEO/AEO/UX/Psychology base scores from preprocessors and validation."""
    seo_facts = seo_facts or {}
    seo_report = seo_report or {}
    ux_facts = ux_facts or {}
    aeo_facts = aeo_facts or {}
    psych_facts = psych_facts or {}
    sv = scrape_validation or {}
    ec = extraction_confidence or {}

    title_s = (seo_facts.get("title_tag") or seo_report.get("title_tag") or {}).get("score", 5)
    meta_s = (seo_facts.get("meta_description") or seo_report.get("meta_description") or {}).get("score", 5)
    h1_s = (seo_facts.get("h1") or seo_report.get("h1") or {}).get("score", 5)
    head_s = (seo_facts.get("headings_structure") or seo_report.get("headings_structure") or {}).get("score", 5)
    schema_s = (seo_facts.get("structured_data") or seo_report.get("structured_data") or {}).get("score", 5)
    img_s = (seo_facts.get("image_seo") or seo_report.get("image_seo") or {}).get("score", 5)
    link_s = (seo_facts.get("links") or seo_report.get("links") or {}).get("score", 5)
    content_s = (seo_facts.get("content_quality") or seo_report.get("content_quality") or {}).get("score", 5)
    tech_s = (seo_facts.get("technical_seo") or seo_report.get("technical_seo") or {}).get("score", 5)

    seo_det = _clamp(
        (title_s + meta_s + h1_s + head_s + schema_s + img_s + link_s + content_s + tech_s) / 9
    )

    trust_n = len(ux_facts.get("trust_badges") or [])
    cta_n = ux_facts.get("cta_count") or 0
    ux_det = 5.0
    ux_det += min(2.0, trust_n * 0.35)
    ux_det += min(2.0, cta_n * 0.5)
    if ux_facts.get("shipping_visible"):
        ux_det += 0.5
    if ux_facts.get("return_policy_visible"):
        ux_det += 0.5
    if ux_facts.get("reviews_visible"):
        ux_det += 1.0

    visual = visual_ux_facts or {}
    vision = visual.get("vision_analysis") or {}
    if vision.get("available"):
        # Blend vision subscores into deterministic UX (0-10 scale)
        vision_overall = float(vision.get("overall_ux_score") or 0)
        if vision_overall > 0:
            ux_det = ux_det * 0.55 + vision_overall * 0.45
        cta_vis = float(vision.get("cta_visibility") or 0)
        if cta_vis >= 7:
            ux_det += 0.4
        elif cta_vis <= 4:
            ux_det -= 0.5
        trust_vis = float(vision.get("trust_signals_visible") or 0)
        if trust_vis >= 7:
            ux_det += 0.3
        hierarchy = float(vision.get("visual_hierarchy") or 0)
        if hierarchy >= 7:
            ux_det += 0.3
        elif hierarchy <= 4:
            ux_det -= 0.4
        mobile_est = float(vision.get("mobile_readiness_estimate") or 0)
        if mobile_est >= 7:
            ux_det += 0.2
        elif mobile_est <= 4:
            ux_det -= 0.3
    ux_det = _clamp(ux_det)

    aeo_det = float(aeo_facts.get("deterministic_aeo_score") or 0)
    if aeo_det <= 0:
        aeo_det = 5.0
        if schema_s >= 7:
            aeo_det += 1.5
        if (seo_facts.get("structured_data") or {}).get("has_faq_schema"):
            aeo_det += 1.5
        aeo = aeo_report or {}
        if aeo.get("faq_quality", {}).get("found"):
            aeo_det += 1.0
    aeo_det = _clamp(aeo_det)

    psych_det = _compute_psychology_deterministic(psych_facts)

    quality_mult = 1.0
    if sv.get("scrape_quality") == "low":
        quality_mult = 0.75
    elif sv.get("scrape_quality") == "medium":
        quality_mult = 0.9
    ext_conf = float(ec.get("overall_extraction_confidence") or 1.0)
    quality_mult *= max(0.6, ext_conf)

    caps_applied: list[str] = []
    seo_out = _clamp(seo_det * quality_mult)
    aeo_out = _clamp(aeo_det * quality_mult)
    ux_out = _clamp(ux_det * quality_mult)
    psych_out = _clamp(psych_det * quality_mult)

    pt = (page_type or sv.get("page_type") or sv.get("detected_page_type") or "").lower()
    if pt == "product":
        pt = "pdp"
    price_conf = float(
        (ec.get("field_confidence") or {}).get("price", ec.get("price_confidence", 1)) or 0
    )
    if pt == "pdp" and price_conf == 0:
        seo_out = min(seo_out, 5.5)
        ux_out = min(ux_out, 5.5)
        caps_applied.append("pdp_missing_price")

    if not (seo_facts.get("structured_data") or {}).get("has_faq_schema"):
        aeo_out = min(aeo_out, 6.5)
        caps_applied.append("faq_schema_missing_aeo_cap")

    visual = visual_ux_facts or {}
    if not visual.get("capture_ok"):
        ux_out = min(ux_out, 6.0)
        caps_applied.append("no_visual_verification")

    return {
        "deterministic_scores": {
            "seo": seo_out,
            "aeo": aeo_out,
            "ux": ux_out,
            "psychology": psych_out,
        },
        "quality_multiplier": round(quality_mult, 2),
        "score_caps_applied": caps_applied,
    }


def _compute_psychology_deterministic(facts: dict[str, Any]) -> float:
    """Deterministic psychology score from Cialdini-style signals."""
    score = 4.0

    # Social proof
    rc = facts.get("review_count") or 0
    try:
        rc = int(rc)
    except (TypeError, ValueError):
        rc = 0
    if rc >= 100:
        score += 1.5
    elif rc >= 10:
        score += 1.0
    elif rc > 0:
        score += 0.5
    if facts.get("testimonials"):
        score += 0.8
    if facts.get("ugc_image_count", 0) > 0 or facts.get("has_ugc_images"):
        score += 0.5

    # Authority
    if facts.get("authority_claims"):
        score += min(1.5, len(facts["authority_claims"]) * 0.4)
    if facts.get("certification_badges"):
        score += 0.8

    # Scarcity
    if facts.get("scarcity_language"):
        score += min(1.2, len(facts["scarcity_language"]) * 0.4)
    if facts.get("low_stock_detected"):
        score += 0.6

    # Urgency
    if facts.get("urgency_language"):
        score += min(1.0, len(facts["urgency_language"]) * 0.35)
    if facts.get("countdown_timer_detected"):
        score += 0.5

    # Risk reversal
    if facts.get("free_returns_detected"):
        score += 0.7
    if facts.get("guarantee_detected"):
        score += 0.6

    return _clamp(score)


def blend_score(deterministic: float, llm_score: float | None, *, max_delta: float = 2.0) -> float:
    """Combine deterministic base with bounded LLM modifier."""
    if llm_score is None:
        return deterministic
    delta = max(-max_delta, min(max_delta, llm_score - deterministic))
    return _clamp(deterministic + delta * 0.5)


def apply_reliability_caps(score: float, state: dict) -> float:
    """Prevent overconfident scores when scrape/extraction is weak."""
    s = score
    if state.get("partial_analysis"):
        s = min(s, 6.5)
    sv = state.get("scrape_validation") or {}
    if sv.get("scrape_quality") == "low":
        s = min(s, 6.0)
    elif sv.get("scrape_quality") == "medium":
        s = min(s, 7.5)
    ec = state.get("extraction_confidence") or {}
    conf = float(ec.get("overall_extraction_confidence") or 1.0)
    if conf < 0.45:
        s = min(s, 5.0)
    elif conf < 0.6:
        s = min(s, 6.5)
    vr = state.get("validation_report") or {}
    penalty = float(vr.get("confidence_penalty") or 0)
    if penalty >= 0.2:
        s = min(s, 5.5)
    elif penalty >= 0.1:
        s = min(s, 6.5)
    if vr.get("hallucination_risk") == "high":
        s = min(s, 5.5)
    visual = state.get("visual_ux_facts") or {}
    if not visual.get("capture_ok") and (state.get("audit_depth") or "") != "lightweight":
        s = min(s, 7.0)
    page = (state.get("page_type_info") or {}).get("page_type") or sv.get("page_type")
    if page == "pdp" and conf < 0.5:
        s = min(s, 5.5)
    return _clamp(s)
