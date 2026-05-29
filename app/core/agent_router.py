"""
Agent cascading — which agents run and at what depth (no LLM).
"""
from __future__ import annotations

from typing import Any

from app.core.demo_mode import is_demo_mode
from app.core.page_type_router import is_pdp


def build_agent_plan(state: dict[str, Any]) -> dict[str, Any]:
    """
    Return execution plan: which agents run, audit depth, skipped reasons.
    """
    sv = state.get("scrape_validation") or {}
    ec = state.get("extraction_confidence") or {}
    page = state.get("page_type_info") or {}
    page_type = page.get("page_type") or sv.get("detected_page_type") or "unknown"
    if page_type == "product":
        page_type = "pdp"

    scrape_q = sv.get("scrape_quality", "medium")
    ext_conf = float(ec.get("overall_extraction_confidence") or 0.7)
    partial = bool(state.get("partial_analysis"))

    skipped: dict[str, str] = {}
    run_competitor = True
    run_autofix_llm = True
    run_content_gen = False  # already lazy
    run_psychology = True
    run_aeo_deep = True

    if scrape_q == "low" or partial:
        audit_depth = "lightweight"
        run_competitor = False
        run_autofix_llm = False
        run_aeo_deep = False
        skipped["competitor"] = "low scrape quality — lightweight audit"
        skipped["autofix_llm"] = "low scrape quality — template fixes only"
        skipped["aeo_deep"] = "low scrape — capped AEO reasoning"
    elif ext_conf < 0.4:
        audit_depth = "lightweight"
        run_competitor = False
        run_autofix_llm = False
        skipped["competitor"] = "extraction confidence < 0.4"
        skipped["autofix_llm"] = "extraction confidence < 0.4"
    elif ext_conf < 0.55:
        audit_depth = "standard"
        run_competitor = ext_conf >= 0.45
        if not run_competitor:
            skipped["competitor"] = "moderate extraction confidence"
    else:
        audit_depth = "deep" if scrape_q == "high" and ext_conf >= 0.65 else "standard"

    if is_demo_mode():
        audit_depth = "standard"
        run_autofix_llm = False
        run_aeo_deep = False
        skipped["demo_mode"] = "CTO demo — standard depth, template-first fixes"
        if ext_conf < 0.5:
            run_competitor = False
            skipped["competitor"] = "demo mode + moderate extraction — skip live competitor scrape"

    if page_type in ("homepage", "saas_landing", "blog", "docs", "local_business"):
        skipped.setdefault("pdp_checks", "non-PDP page — PDP-only UX checks disabled")

    if page_type == "unknown" and ext_conf < 0.5:
        audit_depth = "lightweight"
        run_psychology = False
        skipped["psychology"] = "unknown page type + low extraction"

    return {
        "page_type": page_type,
        "audit_depth": audit_depth,
        "run_seo": True,
        "run_aeo": True,
        "run_ux": True,
        "run_competitor": run_competitor,
        "run_psychology": run_psychology,
        "run_autofix_llm": run_autofix_llm,
        "run_content_gen": run_content_gen,
        "run_aeo_deep": run_aeo_deep,
        "skip_pdp_only_checks": not is_pdp(page_type),
        "skipped_reasons": skipped,
        "target_duration_hint_sec": 45 if audit_depth == "standard" else (30 if audit_depth == "lightweight" else 90),
    }


async def agent_router_agent(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node — set agent_plan after extractor."""
    plan = build_agent_plan(state)
    return {"agent_plan": plan, "audit_depth": plan["audit_depth"]}
