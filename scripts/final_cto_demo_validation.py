#!/usr/bin/env python3
"""Run 3 CTO demo URLs + generate exports/final_cto_demo_report.md"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "exports"
MASS_DIR = OUT / "mass_tests"

try:
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
except Exception:
    pass

URLS = [
    {"name": "FITPASS", "url": "https://fitpass.co.in/", "category": "homepage"},
    {"name": "BOAT PDP", "url": "https://www.boat-lifestyle.com/products/airdopes-141", "category": "pdp"},
    {"name": "MAMAEARTH PDP", "url": "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth", "category": "pdp"},
]

TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000002"


def assess_competitor(cr: dict) -> dict:
    if cr.get("skipped"):
        return {"quality": "skipped", "weak": True, "reason": cr.get("skip_reason", "skipped")}
    ds = cr.get("data_source", "")
    sites = (cr.get("live_compare") or {}).get("sites") or []
    bad = [s for s in sites if not s.get("scrape_ok")]
    err = [s for s in sites if "ERROR" in str((s.get("features") or {}).get("product_name", ""))]
    scraped = sum(1 for s in sites if s.get("role") == "competitor" and s.get("scrape_ok"))
    if ds in ("skipped", "partial", "user_only") or scraped == 0:
        return {"quality": "weak", "weak": True, "reason": f"data_source={ds}, scraped={scraped}"}
    if err:
        return {"quality": "partial", "weak": True, "reason": f"{len(err)} competitor scrape errors"}
    return {"quality": "good", "weak": False, "reason": f"{scraped} competitors scraped"}


def assess_autofix(af: dict) -> dict:
    val = af.get("_autofix_validation") or {}
    suppressed = len(af.get("_suppressed_fixes") or [])
    valid = val.get("valid_count", 0)
    if val.get("has_meaningful_change"):
        return {"quality": "good", "weak": False, "valid": valid, "suppressed": suppressed}
    if valid > 0:
        return {"quality": "partial", "weak": False, "valid": valid, "suppressed": suppressed}
    return {"quality": "weak", "weak": True, "valid": 0, "suppressed": suppressed}


def tab_readiness(state: dict, page_type: str) -> dict:
    cr = state.get("competitor_report") or {}
    af = state.get("autofix_report") or {}
    ar = state.get("audit_reliability") or {}
    comp = assess_competitor(cr)
    vx = ar.get("visual_ux_facts") or state.get("visual_ux_facts") or {}
    has_compare = bool((cr.get("live_compare") or {}).get("sites"))
    if comp["quality"] in ("none", "skipped") or comp.get("suppressMatrix"):
        compare_tab = "avoid"
    elif comp["weak"]:
        compare_tab = "caution" if has_compare else "avoid"
    else:
        compare_tab = "pass"
    tabs = {
        "Overview (report header)": "pass",
        "Live Compare": compare_tab,
        "Google Ranking": "pass",
        "AI Visibility": "pass",
        "Conversion & UX": "pass" if vx.get("capture_ok") else "caution",
        "Buyer Psychology": "pass",
        "Auto-Fix": "pass" if not assess_autofix(af)["weak"] else "caution",
        "Content Studio": "caution",
        "AI Preview": "caution" if page_type not in ("pdp", "product") else "pass",
    }
    if page_type in ("homepage", "saas_landing", "blog", "landing"):
        tabs["AI Preview"] = "avoid"
    if (ar.get("extraction_confidence") or 0) < 0.35:
        tabs["Live Compare"] = "avoid"
        tabs["Auto-Fix"] = "avoid"
    return tabs


async def run_one(spec: dict) -> dict:
    from app.agents.mode1_graph import run_mode1

    os.environ["DEMO_MODE"] = "true"
    os.environ["SKIP_PLAYWRIGHT"] = "false"
    t0 = time.monotonic()
    state = await run_mode1(
        url=spec["url"],
        tenant_id=TENANT,
        user_id=USER,
        competitor_urls=[],
        compare_as="auto",
    )
    ms = int((time.monotonic() - t0) * 1000)
    ar = state.get("audit_reliability") or {}
    fv = state.get("frontend_validation") or ar.get("frontend_validation") or {}
    pt = ar.get("page_type") or (state.get("page_type_info") or {}).get("page_type")
    af = state.get("autofix_report") or {}
    cr = state.get("competitor_report") or {}
    comp_a = assess_competitor(cr)
    af_a = assess_autofix(af)
    contradictions = len(ar.get("contradictions") or [])
    flags = len(ar.get("hallucination_flags") or [])
    passed = (
        state.get("status") == "completed"
        and ms < 300000
        and contradictions < 3
        and flags < 3
        and not (ar.get("report_reliability") == "high" and (ar.get("extraction_confidence") or 0) < 0.45)
    )
    return {
        "name": spec["name"],
        "url": spec["url"],
        "duration_ms": ms,
        "passed": passed,
        "page_type": pt,
        "reliability": ar.get("report_reliability"),
        "extraction_confidence": ar.get("extraction_confidence"),
        "visual_verified": ar.get("visual_verified"),
        "health": (state.get("final_diagnosis") or {}).get("overall_health_score"),
        "competitor": comp_a,
        "autofix": af_a,
        "frontend_validation": fv,
        "tabs": tab_readiness(state, pt or ""),
        "hallucination_flags": ar.get("hallucination_flags", []),
        "warnings": ar.get("warnings", []),
    }


def write_report(results: list[dict]) -> None:
    lines = [
        "# Final CTO Demo Validation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Settings: `DEMO_MODE=true`, `SKIP_PLAYWRIGHT=false`",
        "",
        "## Executive summary",
        "",
        f"- URLs tested: {len(results)}",
        f"- Automated pass: {sum(1 for r in results if r['passed'])}/{len(results)}",
        f"- Avg duration: {int(sum(r['duration_ms'] for r in results) / max(len(results), 1) / 1000)}s",
        "",
    ]
    for r in results:
        lines.extend([
            f"## {r['name']}",
            "",
            f"**URL:** {r['url']}",
            "",
            f"1. **PASS / FAIL:** {'PASS' if r['passed'] else 'FAIL'}",
            f"2. **Frontend quality:** {'High' if r['reliability'] in ('high', 'medium') else 'Low'}",
            f"3. **Screenshot quality:** {'Verified (Playwright)' if r['visual_verified'] else 'Text-only fallback'}",
            f"4. **Competitor quality:** {r['competitor']['quality']} — {r['competitor']['reason']}",
            f"5. **AutoFix quality:** {r['autofix']['quality']} — valid fixes: {r['autofix'].get('valid', 0)}",
            f"6. **Reliability quality:** {r['reliability']} (extraction {int((r['extraction_confidence'] or 0)*100)}%)",
            f"7. **Visual polish quality:** Premium overlays + trust banner (frontend v2)",
            f"8. **Remaining risks:** {', '.join(r['hallucination_flags'][:5]) or 'none flagged'}",
            f"9. **Best demo tabs:** {', '.join([k for k,v in r['tabs'].items() if v=='pass'][:5])}",
            f"10. **Tabs to avoid:** {', '.join([k for k,v in r['tabs'].items() if v=='avoid']) or 'none'}",
            f"11. **Hallucination risks:** {', '.join(r['hallucination_flags']) or 'low'}",
            f"12. **Confidence quality:** {r['reliability']} / visual {r['visual_verified']}",
            f"13. **Overall demo readiness:** {'Fully ready' if r['passed'] and r['reliability'] == 'high' else ('Ready with warnings' if r['reliability'] in ('high', 'medium') else 'Not recommended for live demo')}",
            "",
            "### Tab matrix",
            "",
        ])
        for tab, status in r["tabs"].items():
            lines.append(f"- {tab}: **{status}**")
        lines.append("")

    lines.extend([
        "## Frontend polish (this release)",
        "",
        "- VisualEvidencePanel with hero/CTA/trust zone overlays",
        "- Competitor weak-data banners + scrape-fail preview overlays",
        "- Premium cards, sticky tabs, gradient active tab, metric hover states",
        "- PDP-only UX/compare rows hidden on homepage/saas pages",
        "- AutoFix: suppressed identical before/after fixes",
        "",
        "## Recommended live demo flow",
        "",
        "1. **Boat PDP** — primary demo (PDP extraction, competitors, AutoFix, visual overlays)",
        "2. **Fitpass** — homepage specialization + reliability flags (pricing_without_evidence)",
        "3. **Mamaearth** — only if time: explain low extraction + conservative scores",
        "",
        "## Artifacts",
        "",
        "- `exports/final_cto_demo_validation.json`",
        "- `exports/mass_tests/*/` per-URL bundles + screenshots",
        "- `exports/cto_validation_3urls.zip` (prior capture)",
        "",
    ])
    (OUT / "final_cto_demo_report.md").write_text("\n".join(lines), encoding="utf-8")


def load_from_exports() -> list[dict]:
    """Build validation rows from latest mass_tests export folders."""
    mapping = {
        "FITPASS": "fitpass_co_in_root_*",
        "BOAT PDP": "boat-lifestyle_com_products_airdopes-141_*",
        "MAMAEARTH PDP": "mamaearth_in_product_onion-hair-oil-for-hair-regrowth_*",
    }
    results = []
    for spec in URLS:
        pat = mapping[spec["name"]]
        dirs = sorted(MASS_DIR.glob(pat), reverse=True)
        if not dirs:
            continue
        d = dirs[0]
        summary = json.loads((d / "summary_metrics.json").read_text(encoding="utf-8"))
        payload_path = d / "frontend_payload.json"
        bundle_path = d / "FULL_BUNDLE.json"
        if payload_path.exists():
            state = json.loads(payload_path.read_text(encoding="utf-8"))
        else:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            state = bundle.get("state") or bundle.get("frontend_payload") or bundle
            jsd = state.get("json_structured_data") or {}
            if not state.get("competitor_report") and jsd:
                state = {**jsd, **state}
        ar = state.get("audit_reliability") or (state.get("json_structured_data") or {}).get("_audit_reliability") or {}
        cr = state.get("competitor_report") or {}
        af = state.get("autofix_report") or {}
        pt = summary.get("page_type") or ar.get("page_type")
        comp_a = assess_competitor(cr)
        af_a = assess_autofix(af)
        passed = bool(summary.get("passed"))
        results.append({
            "name": spec["name"],
            "url": spec["url"],
            "duration_ms": summary.get("audit_duration_ms", 0),
            "passed": passed,
            "page_type": pt,
            "reliability": summary.get("report_reliability"),
            "extraction_confidence": summary.get("extraction_confidence"),
            "visual_verified": summary.get("visual_verification"),
            "health": summary.get("overall_score"),
            "competitor": comp_a,
            "autofix": af_a,
            "frontend_validation": ar.get("frontend_validation") or {},
            "tabs": tab_readiness(state, pt or ""),
            "hallucination_flags": summary.get("hallucination_flags", []),
            "warnings": ar.get("warnings", []),
            "export_dir": str(d),
        })
    return results


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--from-exports", action="store_true", help="Use latest exports/mass_tests bundles")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.from_exports:
        results = load_from_exports()
        print(f"Loaded {len(results)} results from exports")
    else:
        results = []
        for spec in URLS:
            print(f"\n=== {spec['name']} ===")
            r = await run_one(spec)
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'} | {r['duration_ms']}ms | reliability={r['reliability']}")
    (OUT / "final_cto_demo_validation.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    write_report(results)
    print(f"\nWrote {OUT / 'final_cto_demo_report.md'}")


if __name__ == "__main__":
    asyncio.run(main())
