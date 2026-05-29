"""
Validate all Mode 1 outputs shown on the frontend — scores, recs, claims, trust UI.
"""
from __future__ import annotations

import re
from typing import Any

from app.rulesets.base import PDP_LEAKAGE_TERMS, filter_pdp_leakage, get_ruleset
from app.validators.autofix_validator import validate_autofix_report

_PRICE_RE = re.compile(r"\b(price|pricing|₹|\$|€|discount|sale)\b", re.I)
_REVIEW_RE = re.compile(r"\b(\d+\s*reviews?|verified buyer|star rating)\b", re.I)


def _cap_score(score: float | None, cap: float) -> float | None:
    if score is None:
        return None
    return round(min(float(score), cap), 1)


def _page_type(state: dict) -> str:
    pt = (
        (state.get("page_type_info") or {}).get("page_type")
        or (state.get("scrape_validation") or {}).get("page_type")
        or (state.get("audit_reliability") or {}).get("page_type")
        or "unknown"
    )
    return "pdp" if pt == "product" else pt


def _reliability_context(state: dict) -> dict[str, Any]:
    ar = state.get("audit_reliability") or {}
    sv = state.get("scrape_validation") or {}
    ec = state.get("extraction_confidence") or {}
    vr = state.get("validation_report") or {}
    visual = state.get("visual_ux_facts") or {}
    ec = state.get("extraction_confidence") or {}
    return {
        "scrape_quality": sv.get("scrape_quality", "medium"),
        "ext_conf": float(ec.get("overall_extraction_confidence") or 1.0),
        "price_conf": float((ec.get("field_confidence") or {}).get("price", ec.get("price_confidence", 1)) or 0),
        "partial": bool(state.get("partial_analysis")),
        "visual_ok": bool(visual.get("capture_ok") or ar.get("visual_verified")),
        "contradictions": vr.get("contradictions_found") or ar.get("contradictions") or [],
        "hallucination_flags": vr.get("hallucination_flags") or ar.get("hallucination_flags") or [],
        "report_reliability": ar.get("report_reliability") or vr.get("report_reliability"),
    }


def _score_caps(ctx: dict) -> float:
    cap = 10.0
    if ctx["scrape_quality"] == "low":
        cap = min(cap, 6.0)
    elif ctx["scrape_quality"] == "medium":
        cap = min(cap, 7.5)
    if ctx["ext_conf"] < 0.45:
        cap = min(cap, 5.0)
    elif ctx["ext_conf"] < 0.6:
        cap = min(cap, 6.5)
    if not ctx["visual_ok"]:
        cap = min(cap, 7.0)
    if ctx["partial"]:
        cap = min(cap, 6.5)
    if len(ctx["contradictions"]) >= 2:
        cap = min(cap, 5.5)
    if len(ctx["hallucination_flags"]) >= 2:
        cap = min(cap, 5.5)
    return cap


def _sanitize_recommendation(
    rec: Any,
    *,
    page_type: str,
    ctx: dict,
    min_confidence: float = 0.5,
) -> tuple[Any | None, str | None]:
    """Return (rec, suppress_reason)."""
    if isinstance(rec, dict):
        text = rec.get("action") or rec.get("text") or ""
        conf = float((rec.get("confidence_meta") or {}).get("confidence", rec.get("confidence", 0.65)))
        det = (rec.get("confidence_meta") or {}).get("deterministic", False)
        pt_ok = (rec.get("confidence_meta") or {}).get("page_type_validated", True)
    else:
        text = str(rec)
        conf = 0.6
        det = False
        pt_ok = True

    if not text.strip():
        return None, "empty"

    filtered, flagged = filter_pdp_leakage([text], page_type)
    if flagged:
        return None, "pdp_leakage"

    forbidden = get_ruleset(page_type).get("forbidden_topics") or []
    for term in forbidden:
        if term.lower() in text.lower():
            return None, f"forbidden_topic:{term}"

    if ctx.get("price_conf", 1) == 0 and _PRICE_RE.search(text):
        return None, "pricing_without_evidence"

    if not pt_ok and page_type not in ("pdp", "product"):
        return None, "page_type_mismatch"

    if conf < min_confidence and not det:
        return None, "low_confidence"

    if isinstance(rec, dict):
        meta = dict(rec.get("confidence_meta") or {})
        meta.setdefault("evidence_exists", det or bool(meta.get("evidence")))
        meta.setdefault("page_type_validated", pt_ok)
        meta.setdefault("source", meta.get("source", "llm"))
        out = dict(rec)
        out["confidence_meta"] = meta
        return out, None
    return {
        "text": text,
        "confidence_meta": {
            "text": text,
            "confidence": conf,
            "deterministic": det,
            "evidence_exists": det,
            "source": "llm",
            "page_type_validated": True,
        },
    }, None


def _sanitize_score_reports(state: dict, cap: float, issues: list) -> dict:
    state = dict(state)
    for key, score_field in (
        ("seo_report", "overall_seo_score"),
        ("aeo_report", "ai_visibility_score"),
        ("ux_report", "conversion_score"),
        ("psychology_report", "overall_psychology_score"),
    ):
        rep = state.get(key)
        if isinstance(rep, dict) and rep.get(score_field) is not None:
            old = float(rep[score_field])
            new = _cap_score(old, cap)
            if new != old:
                issues.append(f"score_capped:{key}:{old}->{new}")
            rep = dict(rep)
            rep[score_field] = new
            state[key] = rep

    fd = state.get("final_diagnosis")
    if isinstance(fd, dict):
        fd = dict(fd)
        if fd.get("overall_health_score") is not None:
            old = float(fd["overall_health_score"])
            new = _cap_score(old, cap)
            if new != old:
                issues.append(f"health_score_capped:{old}->{new}")
            fd["overall_health_score"] = new
        sb = dict(fd.get("score_breakdown") or {})
        for k in list(sb.keys()):
            if isinstance(sb[k], (int, float)):
                sb[k] = _cap_score(sb[k], cap)
        fd["score_breakdown"] = sb
        state["final_diagnosis"] = fd
    return state


def _validate_schema_claims(state: dict, issues: list) -> None:
    seo = state.get("seo_report") or {}
    dom = state.get("dom_technical_seo") or {}
    sd = seo.get("structured_data") or {}
    if sd.get("has_product_schema") and not dom.get("product_schema_present"):
        issues.append("schema_claim_without_dom:product")
        seo = dict(seo)
        sd = dict(sd)
        sd["has_product_schema"] = False
        seo["structured_data"] = sd
        state["seo_report"] = seo
    if sd.get("has_faq_schema") and not dom.get("faq_schema_present"):
        issues.append("schema_claim_without_dom:faq")


def _validate_review_claims(state: dict, issues: list) -> None:
    ux = state.get("ux_report") or {}
    structured = state.get("json_structured_data") or {}
    ux_rev = bool((ux.get("trust_signals") or {}).get("reviews_present"))
    ext_rev = bool(structured.get("has_reviews"))
    if ux_rev and not ext_rev and not (structured.get("review_count") or 0):
        issues.append("review_claim_without_extraction")
        ux = dict(ux)
        ts = dict(ux.get("trust_signals") or {})
        ts["reviews_present"] = False
        ux["trust_signals"] = ts
        state["ux_report"] = ux


def validate_frontend_report(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Full frontend validation. Returns (sanitized_state, frontend_validation_report).
    """
    state = dict(state)
    issues: list[str] = []
    warnings: list[str] = []
    page_type = _page_type(state)
    ctx = _reliability_context(state)
    ctx["page_type"] = page_type

    cap = _score_caps(ctx)
    state = _sanitize_score_reports(state, cap, issues)

    _validate_schema_claims(state, issues)
    _validate_review_claims(state, issues)

    # UX recommendations
    ux = state.get("ux_report") or {}
    if isinstance(ux, dict):
        ux = dict(ux)
        for key in ("recommendations", "friction_points", "conversion_blockers"):
            items = ux.get(key) or []
            kept, suppressed = [], []
            for item in items:
                out, reason = _sanitize_recommendation(item, page_type=page_type, ctx=ctx)
                if out is not None:
                    if isinstance(out, dict) and "action" in out:
                        kept.append(out)
                    elif isinstance(out, dict) and out.get("text"):
                        kept.append(out["text"])
                    else:
                        kept.append(str(out))
                elif reason:
                    suppressed.append({"item": str(item)[:120], "reason": reason})
            ux[key] = kept if isinstance(items, list) else items
            if suppressed:
                ux[f"_{key}_suppressed"] = suppressed
        state["ux_report"] = ux

    # Final diagnosis recommendations
    fd = state.get("final_diagnosis") or {}
    if isinstance(fd, dict):
        fd = dict(fd)
        recs = fd.get("prioritized_recommendations") or []
        kept_recs = []
        for rec in recs:
            out, reason = _sanitize_recommendation(rec, page_type=page_type, ctx=ctx, min_confidence=0.45)
            if out is not None:
                kept_recs.append(out)
            elif reason:
                issues.append(f"rec_suppressed:{reason}")
        fd["prioritized_recommendations"] = kept_recs
        state["final_diagnosis"] = fd

    # Autofix
    autofix = validate_autofix_report(
        state.get("autofix_report") or {},
        seo_report=state.get("seo_report") or {},
        dom_facts=state.get("dom_technical_seo") or {},
        structured=state.get("json_structured_data") or {},
        page_type=page_type,
        url=state.get("url") or "",
    )
    if not autofix.get("_autofix_validation", {}).get("has_meaningful_change"):
        warnings.append("No meaningful AutoFix changes — before/after may look identical")
    state["autofix_report"] = autofix

    # Trust banner fields
    ar = dict(state.get("audit_reliability") or {})
    if ctx["report_reliability"] == "high" and (ctx["ext_conf"] < 0.5 or ctx["scrape_quality"] == "low"):
        ar["report_reliability"] = "medium"
        issues.append("reliability_downgraded:false_high")
    if not ctx["visual_ok"]:
        warnings.append("Visual verification unavailable — UX findings are text-inferred only")
        ar["visual_verified"] = False
    ar["frontend_safe"] = len([i for i in issues if "suppressed" in i or "false" in i]) < 5
    state["audit_reliability"] = ar

    report = {
        "page_type": page_type,
        "score_cap_applied": cap,
        "issues": issues,
        "warnings": warnings,
        "suppressed_autofix": autofix.get("_suppressed_fixes", []),
        "autofix_valid_count": autofix.get("_autofix_validation", {}).get("valid_count", 0),
        "trust_ok": ar.get("frontend_safe", True),
    }
    return state, report
