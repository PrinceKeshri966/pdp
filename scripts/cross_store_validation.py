#!/usr/bin/env python3
"""
Cross-Store Validation Suite — compare Playwright GT vs pipeline across stores.

Baseline (reference only): Boat, Mamaearth
Focus: Allbirds, Huel, Gymshark

Fields: price, variants, reviews, faq, schema, trust, shipping, returns
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "exports" / "cross_store"
TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000002"

try:
    import langchain
    if not hasattr(langchain, "debug"):
        langchain.debug = False
except Exception:
    pass

from scripts.ground_truth_validation import (  # noqa: E402
    _match_status,
    _pipeline_fields,
    extract_ground_truth,
    run_pipeline,
)

# Suite field map: suite_name -> (gt_key, pipeline_key)
SUITE_FIELDS: dict[str, tuple[str, str]] = {
    "price": ("price", "price"),
    "variants": ("variant_count", "variant_count"),
    "reviews": ("review_count", "review_count"),
    "faq": ("faq_count", "faq_count"),
    "schema": ("product_schema", "product_schema"),
    "trust_signals": ("trust_badges", "trust_badges"),
    "shipping": ("shipping_visible", "shipping_visible"),
    "returns": ("return_policy_visible", "return_policy_visible"),
}

STORES: list[dict[str, Any]] = [
    {"name": "Boat Lifestyle", "url": "https://www.boat-lifestyle.com/", "platform": "shopify", "role": "baseline"},
    {"name": "Mamaearth", "url": "https://mamaearth.in/", "platform": "shopify", "role": "baseline"},
    {"name": "Allbirds", "url": "https://www.allbirds.com/", "platform": "shopify", "role": "focus"},
    {"name": "Huel", "url": "https://huel.com/", "platform": "shopify", "role": "focus"},
    {"name": "Gymshark", "url": "https://www.gymshark.com/", "platform": "headless", "role": "focus"},
]

# Huel fallback registered in ground_truth_validation if extended


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def _gt_blocked(gt: dict[str, Any]) -> bool:
    title = (gt.get("product_title") or "").lower()
    return "verify" in title or "connection needs" in title or "captcha" in title


def _compare_suite(gt: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for label, (gk, pk) in SUITE_FIELDS.items():
        actual = gt.get(gk)
        pipe = pipeline.get(pk)
        status = _match_status(actual, pipe)
        rows.append({
            "field": label,
            "status": status,
            "actual": actual,
            "pipeline": pipe,
            "pass": status == "MATCH",
            "partial": status == "PARTIAL MATCH",
            "fail": status == "MISMATCH",
        })
    n = len(rows)
    match = sum(1 for r in rows if r["status"] == "MATCH")
    partial = sum(1 for r in rows if r["status"] == "PARTIAL MATCH")
    mismatch = sum(1 for r in rows if r["status"] == "MISMATCH")
    pass_pct = round((match + partial * 0.5) / n * 100, 1)
    fail_pct = round(mismatch / n * 100, 1)
    conf = pipeline.get("extraction_confidence")
    return {
        "rows": rows,
        "pass_pct": pass_pct,
        "fail_pct": fail_pct,
        "partial_pct": round(100 - pass_pct - fail_pct, 1),
        "confidence": conf,
        "counts": {"MATCH": match, "PARTIAL": partial, "MISMATCH": mismatch},
    }


def _load_cached(name: str) -> dict[str, Any] | None:
    for base in (OUT, ROOT / "exports" / "ground_truth"):
        p = base / f"{_slug(name)}_cross_store.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        p2 = base / f"{_slug(name)}_ground_truth.json"
        if p2.exists():
            return json.loads(p2.read_text(encoding="utf-8"))
    return None


def _baseline_failures(baseline_results: list[dict[str, Any]]) -> set[str]:
    failed: set[str] = set()
    for site in baseline_results:
        for row in site.get("suite", {}).get("rows", []):
            if row.get("fail") or row.get("partial"):
                failed.add(row["field"])
    return failed


def _aggregate_failures(results: list[dict[str, Any]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for site in results:
        for row in site.get("suite", {}).get("rows", []):
            if row.get("fail"):
                c[row["field"]] += 1
            elif row.get("partial"):
                c[row["field"]] += 0.5
    return c


def render_report(results: list[dict[str, Any]], baseline_failures: set[str]) -> str:
    lines = [
        "# Cross-Store Validation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        "| Store | Platform | Role | Pass % | Fail % | Confidence |",
        "|-------|----------|------|--------|--------|------------|",
    ]
    for r in results:
        s = r["suite"]
        lines.append(
            f"| {r['name']} | {r['platform']} | {r['role']} | {s['pass_pct']}% | {s['fail_pct']}% | {s.get('confidence', 'N/A')} |"
        )

    focus = [r for r in results if r["role"] == "focus"]
    agg = _aggregate_failures(focus)
    lines += ["", "## Common Failures (Focus Stores)", ""]
    for field, count in agg.most_common():
        lines.append(f"- **{field}**: {count} store(s)")

    lines += ["", "## Novel Failures (not in Boat/Mamaearth baseline)", ""]
    novel: list[str] = []
    for r in focus:
        for row in r["suite"]["rows"]:
            if (row.get("fail") or row.get("partial")) and row["field"] not in baseline_failures:
                novel.append(f"- **{r['name']}** / {row['field']}: actual=`{row['actual']}` pipeline=`{row['pipeline']}`")
    lines.extend(novel or ["- None detected"])

    lines += ["", "## Per-Site Detail", ""]
    for r in results:
        lines += [f"### {r['name']} ({r['platform']})", ""]
        lines += ["| Field | Status | Actual | Pipeline |", "|-------|--------|--------|----------|"]
        for row in r["suite"]["rows"]:
            st = "PASS" if row["pass"] else ("PARTIAL" if row["partial"] else "FAIL")
            lines.append(f"| {row['field']} | {st} | `{str(row['actual'])[:50]}` | `{str(row['pipeline'])[:50]}` |")
        lines.append("")

    return "\n".join(lines)


async def validate_site(site: dict[str, Any], *, use_cache: bool = False) -> dict[str, Any]:
    cached = _load_cached(site["name"]) if use_cache else None
    if cached and cached.get("ground_truth") and cached.get("pipeline"):
        gt, pf = cached["ground_truth"], cached["pipeline"]
        if not _gt_blocked(gt):
            suite = _compare_suite(gt, pf)
            return {**site, "pdp_url": gt.get("pdp_url"), "ground_truth": gt, "pipeline": pf, "suite": suite, "cached": True}

    gt = await extract_ground_truth(site["url"])
    if _gt_blocked(gt):
        raise RuntimeError(f"GT blocked for {site['name']}: {gt.get('product_title')}")

    pdp_url = gt.get("pdp_url") or site["url"]
    t0 = time.monotonic()
    state = await run_pipeline(pdp_url)
    ms = int((time.monotonic() - t0) * 1000)
    pf = _pipeline_fields(state)
    suite = _compare_suite(gt, pf)

    payload = {
        **site,
        "pdp_url": gt.get("pdp_url"),
        "ground_truth": gt,
        "pipeline": pf,
        "suite": suite,
        "duration_ms": ms,
        "cached": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{_slug(site['name'])}_cross_store.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


async def main(sites: list[dict[str, Any]], *, use_cache: bool = False) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for site in sites:
        print(f"\n=== {site['name']} ({site['platform']}) ===")
        try:
            r = await validate_site(site, use_cache=use_cache)
            results.append(r)
            print(f"  Pass={r['suite']['pass_pct']}% Fail={r['suite']['fail_pct']}% Conf={r['suite'].get('confidence')}")
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({**site, "error": str(exc), "suite": {"pass_pct": 0, "fail_pct": 100, "rows": []}})

    baseline = [r for r in results if r.get("role") == "baseline" and r.get("suite", {}).get("rows")]
    baseline_failures = _baseline_failures(baseline)
    report = render_report([r for r in results if r.get("suite")], baseline_failures)
    (OUT / "cross_store_validation_report.md").write_text(report, encoding="utf-8")
    (OUT / "cross_store_results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nReport: {OUT / 'cross_store_validation_report.md'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--focus-only", action="store_true", help="Allbirds, Huel, Gymshark only")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--use-cache", action="store_true", help="Use cached GT/pipeline JSON")
    args = parser.parse_args()

    selected = STORES
    if args.focus_only:
        selected = [s for s in STORES if s["role"] == "focus"]
    elif args.baseline_only:
        selected = [s for s in STORES if s["role"] == "baseline"]

    os.environ.setdefault("DEMO_MODE", "true")
    os.environ.setdefault("SKIP_PLAYWRIGHT", "false")
    print(asyncio.run(main(selected, use_cache=args.use_cache)))
