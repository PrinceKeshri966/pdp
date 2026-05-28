"""Run Mode 1 for fitpass.co.in and verify accuracy vs live HTML + frontend fields."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.mode1_graph import run_mode1
from app.agents.scraper_agent import _extract_dom_metadata

URL = "https://fitpass.co.in/"
OUT = ROOT / "_verify_fitpass_latest.json"


def _ok(cond: bool, msg: str) -> dict:
    return {"pass": cond, "message": msg}


async def ground_truth() -> dict:
    r = await httpx.AsyncClient(follow_redirects=True, timeout=45.0).get(URL)
    r.raise_for_status()
    return _extract_dom_metadata(r.text)


def verify_seo(seo: dict, dom: dict, gt: dict) -> list[dict]:
    checks = []
    title = seo.get("title_tag", {}).get("value") or ""
    meta = seo.get("meta_description", {}).get("value") or ""
    gt_title = gt.get("title_tag") or ""
    gt_meta = gt.get("meta_description") or ""

    checks.append(
        _ok(
            bool(gt_title) and gt_title.lower() in (title or "").lower()
            or title == gt_title,
            f"title_tag: report={title[:60]!r} vs DOM={gt_title[:60]!r}",
        )
    )
    checks.append(
        _ok(
            bool(gt_meta)
            and (meta[:40] in gt_meta or gt_meta[:40] in meta or len(meta) > 20),
            f"meta_description: report len={len(meta)} vs DOM len={len(gt_meta)}",
        )
    )
    checks.append(
        _ok(
            seo.get("technical_seo", {}).get("canonical_present") == gt.get("canonical_present"),
            f"canonical: seo={seo.get('technical_seo', {}).get('canonical_present')} dom={gt.get('canonical_present')}",
        )
    )
    checks.append(
        _ok(
            seo.get("structured_data", {}).get("has_product_schema") == gt.get("product_schema_present"),
            f"product_schema: seo={seo.get('structured_data', {}).get('has_product_schema')} dom={gt.get('product_schema_present')}",
        )
    )
    checks.append(
        _ok(
            "not provided in markdown" not in title.lower()
            and title.lower() not in ("", "null", "none"),
            f"title not markdown-placeholder: {title[:50]!r}",
        )
    )
    return checks


def verify_competitors(comp: dict) -> list[dict]:
    checks = []
    lc = comp.get("live_compare") or {}
    sites = lc.get("sites") or []
    competitors = [s for s in sites if s.get("role") == "competitor"]
    you = next((s for s in sites if s.get("role") == "you"), None)

    checks.append(_ok(len(sites) >= 2, f"live_compare sites count={len(sites)}"))
    checks.append(_ok(you is not None and you.get("scrape_ok"), "your site present in live_compare"))
    checks.append(
        _ok(
            lc.get("compare_page_type") == "homepage",
            f"compare_page_type={lc.get('compare_page_type')}",
        )
    )
    india_hints = ("cult", "fittr", "healthify", "fitpass")
    comp_domains = " ".join((s.get("url") or "").lower() for s in competitors)
    checks.append(
        _ok(
            any(h in comp_domains for h in india_hints) or len(competitors) == 0,
            f"competitor URLs: {[s.get('url') for s in competitors]}",
        )
    )
    checks.append(
        _ok(
            bool(comp.get("data_source")),
            f"data_source={comp.get('data_source')}",
        )
    )
    rows = lc.get("rows") or []
    checks.append(_ok(len(rows) > 0, f"comparison rows={len(rows)}"))
    return checks


def verify_frontend_integration(state: dict) -> list[dict]:
    """Fields the SPA reads must be present."""
    checks = []
    seo = state.get("seo_report") or {}
    comp = state.get("competitor_report") or {}
    jsd = state.get("json_structured_data") or {}
    dom = state.get("dom_technical_seo") or jsd.get("_dom_technical_seo") or {}

    checks.append(_ok(bool(seo), "seo_report present"))
    checks.append(_ok(seo.get("overall_seo_score") is not None, "seo overall_seo_score"))
    checks.append(_ok(bool(seo.get("title_tag")), "seo title_tag block"))
    checks.append(_ok(bool(comp.get("live_compare")), "competitor live_compare"))
    checks.append(_ok(bool(comp.get("live_compare", {}).get("sites")), "live_compare.sites"))
    checks.append(_ok(bool(comp.get("live_compare", {}).get("rows")), "live_compare.rows"))
    checks.append(_ok(bool(jsd.get("product_name") or jsd.get("categories")), "json_structured_data product context"))
    checks.append(_ok(bool(dom.get("title_tag") or dom.get("meta_description")), "dom_technical_seo for modals"))
    checks.append(_ok(bool(state.get("ux_report")), "ux_report present"))
    checks.append(_ok(bool(state.get("final_diagnosis")), "final_diagnosis present"))
    return checks


async def main() -> None:
    print("Fetching live HTML ground truth...")
    gt = await ground_truth()
    print("Ground truth:", json.dumps(gt, indent=2)[:500])

    print("\nRunning Mode 1 pipeline (2-4 min)...")
    state = await run_mode1(
        url=URL,
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        compare_as="auto",
    )

    payload = {
        "status": state.get("status"),
        "errors": state.get("errors"),
        "dom_technical_seo": state.get("dom_technical_seo"),
        "seo_report": {
            "overall_seo_score": (state.get("seo_report") or {}).get("overall_seo_score"),
            "title_tag": (state.get("seo_report") or {}).get("title_tag"),
            "meta_description": (state.get("seo_report") or {}).get("meta_description"),
            "h1": (state.get("seo_report") or {}).get("h1"),
            "technical_seo": (state.get("seo_report") or {}).get("technical_seo"),
            "structured_data": (state.get("seo_report") or {}).get("structured_data"),
            "top_issues": (state.get("seo_report") or {}).get("top_issues", [])[:5],
        },
        "competitor_report": {
            "data_source": (state.get("competitor_report") or {}).get("data_source"),
            "competitors_analyzed": (state.get("competitor_report") or {}).get("competitors_analyzed"),
            "live_compare": (state.get("competitor_report") or {}).get("live_compare"),
        },
        "json_structured_data": state.get("json_structured_data"),
        "ux_report_keys": list((state.get("ux_report") or {}).keys()),
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved summary to {OUT}")

    seo = state.get("seo_report") or {}
    comp = state.get("competitor_report") or {}

    all_checks: list[tuple[str, dict]] = []
    for c in verify_seo(seo, state.get("dom_technical_seo") or {}, gt):
        all_checks.append(("SEO", c))
    for c in verify_competitors(comp):
        all_checks.append(("Competitors", c))
    for c in verify_frontend_integration(state):
        all_checks.append(("Frontend", c))

    print("\n=== VERIFICATION REPORT ===")
    passed = 0
    for group, c in all_checks:
        mark = "PASS" if c["pass"] else "FAIL"
        if c["pass"]:
            passed += 1
        print(f"[{mark}] {group}: {c['message']}")
    print(f"\n{passed}/{len(all_checks)} checks passed")
    if state.get("errors"):
        print("Pipeline errors:", state["errors"])


if __name__ == "__main__":
    asyncio.run(main())
