"""
Cross-check agent outputs for contradictions and hallucination risk.
"""
from __future__ import annotations

import time
from typing import Any

from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_agent_reports(state: AgentState) -> dict[str, Any]:
    """Deterministic cross-validation (no LLM)."""
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

    contradictions: list[str] = []
    warnings: list[str] = list(scrape_val.get("warnings") or [])

    seo_faq_schema = bool(
        (seo.get("structured_data") or {}).get("has_faq_schema")
        or (seo_facts.get("structured_data") or {}).get("has_faq_schema")
    )
    aeo_faq_schema = bool((aeo.get("structured_data") or {}).get("faq_schema"))
    if seo_faq_schema != aeo_faq_schema and (seo_faq_schema or aeo_faq_schema):
        contradictions.append("SEO and AEO disagree on FAQ schema presence")

    ux_reviews = bool((ux.get("trust_signals") or {}).get("reviews_present"))
    ext_reviews = bool(structured.get("has_reviews"))
    psych_reviews = bool(psych_facts.get("has_reviews"))
    if ux_reviews and not ext_reviews and not psych_reviews:
        contradictions.append("UX reports reviews visible but extractor found none")

    psych_scarcity = bool(psych_facts.get("scarcity_language"))
    psych_urgency = bool(psych_facts.get("urgency_language"))
    cialdini_scarcity = bool((psych.get("cialdini_principles") or {}).get("scarcity", {}).get("present"))
    if cialdini_scarcity and not psych_scarcity and not psych_urgency:
        contradictions.append("Psychology score claims scarcity without detected urgency phrases")

    seo_score = float(seo.get("overall_seo_score") or 0)
    if seo_score >= 8 and scrape_val.get("scrape_quality") == "low":
        contradictions.append(f"SEO score ({seo_score}) high despite low scrape quality")

    if float(ext_conf.get("overall_extraction_confidence") or 1) < 0.45:
        warnings.append("Low extraction confidence — product fields may be inaccurate")

    if scrape_val.get("possible_bot_block"):
        warnings.append("Bot protection may have affected analysis accuracy")

    n_contra = len(contradictions)
    if n_contra >= 3:
        hallucination_risk = "high"
    elif n_contra >= 1:
        hallucination_risk = "medium"
    else:
        hallucination_risk = "low"

    scrape_conf = float(scrape_val.get("confidence") or 0.7)
    ext_c = float(ext_conf.get("overall_extraction_confidence") or 0.7)
    validation_score = round(max(0.0, 10.0 - n_contra * 2.0) * min(scrape_conf, ext_c) * 1.2, 1)
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
    }


async def validator_agent(state: AgentState) -> AgentState:
    t0 = time.monotonic()
    report = validate_agent_reports(state)
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "validator_agent.done",
        reliability=report.get("report_reliability"),
        contradictions=len(report.get("contradictions_found", [])),
    )
    audit_reliability = build_audit_reliability(state, report)
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
    sv = state_dict(state, "scrape_validation")
    ec = state_dict(state, "extraction_confidence")
    det = state_dict(state, "deterministic_scores")
    visual = state_dict(state, "visual_ux_facts")
    return {
        "scrape_quality": sv.get("scrape_quality", "unknown"),
        "scrape_confidence": sv.get("confidence"),
        "extraction_confidence": ec.get("overall_extraction_confidence"),
        "extraction_confidence_pct": int((ec.get("overall_extraction_confidence") or 0) * 100),
        "report_reliability": validation_report.get("report_reliability", "medium"),
        "validation_score": validation_report.get("validation_score"),
        "hallucination_risk": validation_report.get("hallucination_risk", "medium"),
        "partial_analysis": bool(state.get("partial_analysis")),
        "warnings": validation_report.get("warnings", []),
        "contradictions": validation_report.get("contradictions_found", []),
        "missing_critical_fields": ec.get("missing_critical_fields", []),
        "scrape_retry_methods": state.get("scrape_retry_methods") or [],
        "deterministic_scores": det.get("deterministic_scores", {}),
        "visual_ux_facts": visual,
        "detected_page_type": sv.get("detected_page_type"),
        "is_js_heavy": sv.get("is_js_heavy"),
    }
