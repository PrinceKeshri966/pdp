"""
Cross-check agent outputs for contradictions and hallucination risk.
"""
from __future__ import annotations

import re
import time
from typing import Any

from app.agents.state import AgentState, state_dict
from app.core.browser_capture.confidence import compute_section_confidence
from app.core.demo_mode import is_demo_mode
from app.core.logging import get_logger
from app.rulesets.base import PDP_LEAKAGE_TERMS

logger = get_logger(__name__)


def _text_blob(report: dict, keys: list[str]) -> str:
    parts: list[str] = []
    for k in keys:
        v = report.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            parts.append(str(v))
    return " ".join(parts).lower()


def run_cross_validation(state: AgentState) -> dict[str, Any]:
    """Extended contradiction engine — deterministic."""
    seo = state_dict(state, "seo_report")
    aeo = state_dict(state, "aeo_report")
    ux = state_dict(state, "ux_report")
    psych = state_dict(state, "psychology_report")
    structured = state_dict(state, "json_structured_data")
    seo_facts = state_dict(state, "seo_preprocessor_facts")
    ux_facts = state_dict(state, "ux_preprocessor_facts")
    psych_facts = state_dict(state, "psychology_preprocessor_facts")
    scrape_val = state_dict(state, "scrape_validation")
    ext_conf = state_dict(state, "extraction_confidence")
    visual = state_dict(state, "visual_ux_facts")
    page_info = state_dict(state, "page_type_info")
    page_type = page_info.get("page_type") or scrape_val.get("page_type") or "unknown"

    contradictions: list[str] = []
    cross_agent_conflicts: list[dict[str, Any]] = []
    hallucination_flags: list[str] = []
    warnings: list[str] = list(scrape_val.get("warnings") or [])
    confidence_penalty = 0.0

    seo_faq_schema = bool(
        (seo.get("structured_data") or {}).get("has_faq_schema")
        or (seo_facts.get("structured_data") or {}).get("has_faq_schema")
    )
    aeo_faq_schema = bool((aeo.get("structured_data") or {}).get("faq_schema"))
    if seo_faq_schema != aeo_faq_schema and (seo_faq_schema or aeo_faq_schema):
        contradictions.append("SEO and AEO disagree on FAQ schema presence")
        cross_agent_conflicts.append({"agents": ["seo", "aeo"], "field": "faq_schema", "severity": "medium"})

    ux_reviews = bool((ux.get("trust_signals") or {}).get("reviews_present"))
    ext_reviews = bool(structured.get("has_reviews"))
    psych_reviews = bool(psych_facts.get("has_reviews"))
    if ux_reviews and not ext_reviews and not psych_reviews:
        contradictions.append("UX reports reviews visible but extractor found none")
        cross_agent_conflicts.append({"agents": ["ux", "extractor"], "field": "reviews", "severity": "medium"})

    psych_scarcity = bool(psych_facts.get("scarcity_language"))
    psych_urgency = bool(psych_facts.get("urgency_language"))
    cialdini_scarcity = bool((psych.get("cialdini_principles") or {}).get("scarcity", {}).get("present"))
    if cialdini_scarcity and not psych_scarcity and not psych_urgency:
        contradictions.append("Psychology score claims scarcity without detected urgency phrases")

    seo_score = float(seo.get("overall_seo_score") or 0)
    if seo_score >= 8 and scrape_val.get("scrape_quality") == "low":
        contradictions.append(f"SEO score ({seo_score}) high despite low scrape quality")
        confidence_penalty += 0.15

    # Visual vs text UX
    if visual.get("capture_ok"):
        vis_cta = bool(visual.get("cta_above_fold"))
        text_cta = bool((ux.get("cta_analysis") or {}).get("above_fold"))
        if vis_cta != text_cta:
            contradictions.append("Visual UX and text UX disagree on above-fold CTA")
            cross_agent_conflicts.append(
                {"agents": ["visual_ux", "ux"], "field": "cta_above_fold", "severity": "high"}
            )
            confidence_penalty += 0.2
    elif ux.get("conversion_score") and float(ux.get("conversion_score", 0)) >= 7:
        warnings.append("Visual verification unavailable — UX score is text-inferred only")
        confidence_penalty += 0.1

    # PDP leakage on non-PDP pages
    if page_type not in ("pdp", "product", "marketplace"):
        ux_text = _text_blob(
            ux,
            ["friction_points", "conversion_blockers", "recommendations"],
        )
        for term in PDP_LEAKAGE_TERMS:
            if term in ux_text:
                hallucination_flags.append(f"pdp_leakage:{term}")
        if hallucination_flags:
            contradictions.append(
                f"Homepage/non-PDP audit mentions PDP-only concepts ({page_type})"
            )
            confidence_penalty += 0.25

    # Pricing recommendations without price confidence
    price_conf = float(ext_conf.get("field_confidence", {}).get("price", ext_conf.get("price_confidence", 1)) or 0)
    if price_conf == 0:
        rec_blob = _text_blob(
            {**ux, **state_dict(state, "final_diagnosis")},
            ["recommendations", "prioritized_recommendations", "quick_wins"],
        )
        if re.search(r"\b(price|pricing|₹|\$|discount|sale)\b", rec_blob, re.I):
            hallucination_flags.append("pricing_without_evidence")
            warnings.append("Pricing specifics mentioned but price extraction confidence is zero")
            confidence_penalty += 0.15

    if float(ext_conf.get("overall_extraction_confidence") or 1) < 0.45:
        warnings.append("Low extraction confidence — product fields may be inaccurate")

    if scrape_val.get("possible_bot_block"):
        warnings.append("Bot protection may have affected analysis accuracy")

    n_contra = len(contradictions)
    if n_contra >= 3 or len(hallucination_flags) >= 3:
        hallucination_risk = "high"
        contradiction_severity = "high"
    elif n_contra >= 1 or hallucination_flags:
        hallucination_risk = "medium"
        contradiction_severity = "medium"
    else:
        hallucination_risk = "low"
        contradiction_severity = "low"

    scrape_conf = float(scrape_val.get("confidence") or 0.7)
    ext_c = float(ext_conf.get("overall_extraction_confidence") or 0.7)
    validation_score = round(max(0.0, 10.0 - n_contra * 2.0 - confidence_penalty * 10) * min(scrape_conf, ext_c) * 1.2, 1)
    validation_score = min(10.0, validation_score)

    if validation_score >= 7.5 and hallucination_risk == "low":
        report_reliability = "high"
    elif validation_score >= 5.0:
        report_reliability = "medium"
    else:
        report_reliability = "low"

    if state.get("partial_analysis"):
        report_reliability = "low" if report_reliability == "high" else report_reliability
        warnings.append("Analysis ran in partial mode due to scrape limitations")

    return {
        "validation_score": validation_score,
        "contradictions_found": contradictions,
        "hallucination_risk": hallucination_risk,
        "report_reliability": report_reliability,
        "warnings": list(dict.fromkeys(warnings))[:12],
        "contradiction_severity": contradiction_severity,
        "confidence_penalty": round(confidence_penalty, 2),
        "hallucination_flags": hallucination_flags,
        "cross_agent_conflicts": cross_agent_conflicts,
    }


def validate_agent_reports(state: AgentState) -> dict[str, Any]:
    """Deterministic cross-validation (no LLM)."""
    return run_cross_validation(state)


async def validator_agent(state: AgentState) -> AgentState:
    t0 = time.monotonic()
    report = validate_agent_reports(state)
    audit_reliability = build_audit_reliability(state, report)
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "validator_agent.done",
        reliability=report.get("report_reliability"),
        contradictions=len(report.get("contradictions_found", [])),
        flags=len(report.get("hallucination_flags", [])),
    )
    return {
        "validation_report": report,
        "audit_reliability": audit_reliability,
        "agent_reports": [
            {
                "agent": "validator_agent",
                "model": "heuristic",
                "output": report,
                "duration_ms": duration_ms,
            }
        ],
    }


def build_audit_reliability(state: AgentState, validation_report: dict[str, Any]) -> dict[str, Any]:
    """Unified payload for API + frontend."""
    from app.core.evidence.audit_findings import build_audit_evidence
    from app.core.evidence.check_registry import build_check_values, sync_structured_data_reports

    state_dict_copy = dict(state)
    sync_structured_data_reports(state_dict_copy)
    # Persist synced structured_data back to live state
    if state_dict_copy.get("seo_report"):
        state["seo_report"] = state_dict_copy["seo_report"]
    if state_dict_copy.get("aeo_report"):
        state["aeo_report"] = state_dict_copy["aeo_report"]
    check_values = build_check_values(state_dict_copy)

    sv = state_dict(state, "scrape_validation")
    ec = state_dict(state, "extraction_confidence")
    det = state_dict(state, "deterministic_scores")
    visual = state_dict(state, "visual_ux_facts")
    page_info = state_dict(state, "page_type_info")
    plan = state_dict(state, "agent_plan")
    return {
        "scrape_quality": sv.get("scrape_quality", "unknown"),
        "scrape_confidence": sv.get("confidence"),
        "extraction_confidence": ec.get("overall_extraction_confidence"),
        "extraction_confidence_pct": int((ec.get("overall_extraction_confidence") or 0) * 100),
        "field_confidence": {
            "product_name": ec.get("product_name_confidence"),
            "price": ec.get("price_confidence"),
            "reviews": ec.get("reviews_confidence"),
            "brand": ec.get("brand_confidence"),
            "images": ec.get("image_confidence"),
            "schema": ec.get("schema_confidence"),
        },
        "platform": (state.get("platform_info") or {}).get("platform"),
        "extraction_strategies": (state_dict(state, "json_structured_data").get("_extraction_strategies")),
        "report_reliability": validation_report.get("report_reliability", "medium"),
        "validation_score": validation_report.get("validation_score"),
        "hallucination_risk": validation_report.get("hallucination_risk", "medium"),
        "partial_analysis": bool(state.get("partial_analysis")),
        "warnings": validation_report.get("warnings", []),
        "contradictions": validation_report.get("contradictions_found", []),
        "contradiction_severity": validation_report.get("contradiction_severity"),
        "confidence_penalty": validation_report.get("confidence_penalty"),
        "hallucination_flags": validation_report.get("hallucination_flags", []),
        "cross_agent_conflicts": validation_report.get("cross_agent_conflicts", []),
        "missing_critical_fields": ec.get("missing_critical_fields", []),
        "scrape_retry_methods": state.get("scrape_retry_methods") or [],
        "deterministic_scores": det.get("deterministic_scores", {}),
        "visual_ux_facts": visual,
        "visual_verified": bool(visual.get("capture_ok")),
        "detected_page_type": sv.get("detected_page_type"),
        "page_type": page_info.get("page_type") or sv.get("page_type"),
        "page_type_confidence": page_info.get("confidence"),
        "page_type_reasons": page_info.get("reasons", []),
        "audit_depth": state.get("audit_depth") or plan.get("audit_depth", "standard"),
        "agent_plan_skips": plan.get("skipped_reasons", {}),
        "is_js_heavy": sv.get("is_js_heavy"),
        "demo_mode": is_demo_mode(),
        "browser_first": (state.get("scraper_method") or "").startswith("playwright"),
        "capture_confidence": state.get("capture_confidence"),
        "section_confidence": compute_section_confidence(dict(state)).get("section_confidence", {}),
        "lighthouse": ((state.get("browser_capture") or {}).get("lighthouse")),
        "schema_validation": ((state.get("browser_capture") or {}).get("schema_validation")),
        "technical_crawl": ((state.get("browser_capture") or {}).get("technical_crawl")),
        "check_values": check_values,
        "audit_evidence": build_audit_evidence(state_dict_copy),
    }
