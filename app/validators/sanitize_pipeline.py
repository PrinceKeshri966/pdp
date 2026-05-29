"""
Final report validation pipeline — run before frontend render / API response.
"""
from __future__ import annotations

from typing import Any

from app.agents.validator_agent import run_cross_validation
from app.validators.frontend_report_validator import validate_frontend_report


def sanitize_mode1_for_frontend(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    1. Re-run cross-validation (contradictions, page-type leakage)
    2. Frontend report validator (scores, recs, autofix)
    3. Attach unified frontend_validation payload
    """
    state = dict(state)

    # Refresh validation if not present
    if not state.get("validation_report"):
        state["validation_report"] = run_cross_validation(state)

    state, frontend_report = validate_frontend_report(state)

    ar = dict(state.get("audit_reliability") or {})
    vr = state.get("validation_report") or {}
    ar["frontend_validation"] = {
        **frontend_report,
        "contradiction_severity": vr.get("contradiction_severity"),
        "hallucination_flags": vr.get("hallucination_flags", []),
        "contradictions": vr.get("contradictions_found", []),
    }
    if frontend_report.get("warnings"):
        ar["warnings"] = list(dict.fromkeys((ar.get("warnings") or []) + frontend_report["warnings"]))[:15]
    state["audit_reliability"] = ar

    jsd = dict(state.get("json_structured_data") or {})
    jsd["_audit_reliability"] = ar
    jsd["_frontend_validation"] = frontend_report
    state["json_structured_data"] = jsd
    state["frontend_validation"] = frontend_report

    return state, frontend_report
