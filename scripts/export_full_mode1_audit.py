#!/usr/bin/env python3
"""Run Mode 1 and export full debug JSON bundle."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "exports"

# LangGraph/LangChain compat on some installs
try:
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False  # type: ignore[attr-defined]
except Exception:
    pass


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def build_frontend_payload(state: dict[str, Any], url: str) -> dict[str, Any]:
    jsd = dict(state.get("json_structured_data") or {})
    dom = state.get("dom_technical_seo") or jsd.get("_dom_technical_seo") or {}
    if dom:
        jsd["_dom_technical_seo"] = dom
    ar = state.get("audit_reliability") or {}
    if ar:
        jsd["_audit_reliability"] = ar
    ra = state.get("run_analytics") or {}
    if ra:
        jsd["_run_analytics"] = ra
    return {
        "report_id": "local-export",
        "status": state.get("status", "completed"),
        "source_url": url,
        "overall_health_score": (state.get("final_diagnosis") or {}).get("overall_health_score"),
        "seo_score": (state.get("seo_report") or {}).get("overall_seo_score"),
        "json_structured_data": jsd,
        "dom_technical_seo": dom,
        "seo_report": state.get("seo_report") or {},
        "aeo_report": state.get("aeo_report") or {},
        "ux_report": state.get("ux_report") or {},
        "competitor_report": state.get("competitor_report") or {},
        "psychology_report": state.get("psychology_report") or {},
        "final_diagnosis": state.get("final_diagnosis") or {},
        "autofix_report": state.get("autofix_report") or {},
        "generated_content": state.get("generated_content") or {},
        "audit_reliability": ar,
        "run_analytics": ra,
        "agent_reports": state.get("agent_reports") or [],
        "errors": state.get("errors") or [],
    }


def tab_visible_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Data each frontend tab would consume (no PNG screenshots)."""
    return {
        "COMPARE": {"live_compare": (payload.get("competitor_report") or {}).get("live_compare")},
        "SEO": payload.get("seo_report"),
        "AEO": payload.get("aeo_report"),
        "UX": payload.get("ux_report"),
        "COMPETITOR": payload.get("competitor_report"),
        "PSYCHOLOGY": payload.get("psychology_report"),
        "AUTOFIX": payload.get("autofix_report"),
        "CONTENT": payload.get("generated_content"),
        "RELIABILITY": payload.get("audit_reliability"),
        "DIAGNOSIS": payload.get("final_diagnosis"),
    }


async def main(url: str) -> None:
    from app.agents.mode1_graph import run_mode1
    from app.agents.scoring_engine import compute_deterministic_scores

    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "fitpass_co_in"

    print(f"Running Mode 1 on {url} ...")
    state = await run_mode1(
        url=url,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        competitor_urls=[],
        compare_as="auto",
    )

    det_scores = compute_deterministic_scores(
        seo_facts=state.get("seo_preprocessor_facts"),
        seo_report=state.get("seo_report"),
        ux_facts=state.get("ux_preprocessor_facts"),
        aeo_report=state.get("aeo_report"),
        scrape_validation=state.get("scrape_validation"),
        extraction_confidence=state.get("extraction_confidence"),
    )

    bundle = {
        "meta": {
            "url": url,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "status": state.get("status"),
            "partial_analysis": state.get("partial_analysis"),
            "scraper_method": state.get("scraper_method"),
            "errors": state.get("errors"),
        },
        "scrape_validation": state.get("scrape_validation"),
        "extraction_confidence": state.get("extraction_confidence"),
        "validation_report": state.get("validation_report"),
        "audit_reliability": state.get("audit_reliability"),
        "deterministic_scores": state.get("deterministic_scores") or det_scores,
        "scoring_engine_recompute": det_scores,
        "visual_ux_facts": state.get("visual_ux_facts"),
        "run_analytics": state.get("run_analytics"),
        "seo_preprocessor_facts": state.get("seo_preprocessor_facts"),
        "ux_preprocessor_facts": state.get("ux_preprocessor_facts"),
        "psychology_preprocessor_facts": state.get("psychology_preprocessor_facts"),
        "page_contexts": state.get("page_contexts"),
        "agent_context_packages": state.get("agent_context_packages"),
        "json_structured_data": state.get("json_structured_data"),
        "dom_technical_seo": state.get("dom_technical_seo"),
        "seo_report": state.get("seo_report"),
        "aeo_report": state.get("aeo_report"),
        "ux_report": state.get("ux_report"),
        "competitor_report": state.get("competitor_report"),
        "psychology_report": state.get("psychology_report"),
        "final_diagnosis": state.get("final_diagnosis"),
        "autofix_report": state.get("autofix_report"),
        "generated_content": state.get("generated_content"),
        "agent_reports": state.get("agent_reports"),
    }

    frontend = build_frontend_payload(state, url)
    bundle["frontend_api_payload"] = frontend
    bundle["frontend_tab_data"] = tab_visible_data(frontend)

    files = {
        f"{slug}_{ts}_FULL_BUNDLE.json": bundle,
        f"{slug}_{ts}_scrape_validation.json": state.get("scrape_validation"),
        f"{slug}_{ts}_extraction_confidence.json": state.get("extraction_confidence"),
        f"{slug}_{ts}_validation_report.json": state.get("validation_report"),
        f"{slug}_{ts}_audit_reliability.json": state.get("audit_reliability"),
        f"{slug}_{ts}_deterministic_scores.json": state.get("deterministic_scores") or det_scores,
        f"{slug}_{ts}_run_analytics.json": state.get("run_analytics"),
        f"{slug}_{ts}_frontend_payload.json": frontend,
        f"{slug}_{ts}_frontend_tabs.json": tab_visible_data(frontend),
        f"{slug}_{ts}_agent_reports.json": state.get("agent_reports"),
    }
    for name, data in files.items():
        path = OUT / name
        path.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
        print(f"Wrote {path}")

    print("\nDone. Full bundle:", OUT / f"{slug}_{ts}_FULL_BUNDLE.json")


if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else "https://fitpass.co.in/"
    asyncio.run(main(u))
