#!/usr/bin/env python3
"""
Offline extraction validation — uses cached GT JSON + platform extractors (no Playwright).

Re-evaluates pipeline field extraction logic against cached ground truth expectations
using direct signal extractors where HTML is not cached.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ground_truth_validation import _match_status, _pipeline_fields  # noqa: E402

OUT = ROOT / "exports" / "cross_store"
GT_DIR = ROOT / "exports" / "ground_truth"

SUITE_FIELDS = [
    "price", "variant_count", "review_count", "faq_count", "product_schema",
    "trust_badges", "shipping_visible", "return_policy_visible",
]


def _load_cached_results() -> list[dict]:
    results: list[dict] = []
    for path in sorted(OUT.glob("*_cross_store.json")):
        results.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted(GT_DIR.glob("*_ground_truth.json")):
        name = path.stem.replace("_ground_truth", "").replace("_", " ").title()
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "ground_truth" in data:
            results.append({
                "name": name,
                "ground_truth": data["ground_truth"],
                "pipeline": data.get("pipeline") or _pipeline_fields(data.get("state") or {}),
            })
    return results


def _suite_pass_pct(gt: dict, pipeline: dict) -> float:
    rows = []
    field_map = {
        "price": ("price", "price"),
        "variant_count": ("variant_count", "variant_count"),
        "review_count": ("review_count", "review_count"),
        "faq_count": ("faq_count", "faq_count"),
        "product_schema": ("product_schema", "product_schema"),
        "trust_badges": ("trust_badges", "trust_badges"),
        "shipping_visible": ("shipping_visible", "shipping_visible"),
        "return_policy_visible": ("return_policy_visible", "return_policy_visible"),
    }
    for label, (gk, pk) in field_map.items():
        status = _match_status(gt.get(gk), pipeline.get(pk))
        rows.append({"field": label, "status": status})
    n = len(rows)
    match = sum(1 for r in rows if r["status"] == "MATCH")
    partial = sum(1 for r in rows if r["status"] == "PARTIAL MATCH")
    return round((match + partial * 0.5) / n * 100, 1), rows


def main() -> int:
    results = _load_cached_results()
    if not results:
        print("No cached results found.")
        return 1

    print("=== Offline Extraction Validation (cached pipeline data) ===\n")
    total_pct = 0.0
    for entry in results:
        gt = entry.get("ground_truth") or {}
        pipeline = entry.get("pipeline") or {}
        pct, rows = _suite_pass_pct(gt, pipeline)
        total_pct += pct
        name = entry.get("name", "?")
        print(f"{name}: {pct}%")
        for r in rows:
            if r["status"] != "MATCH":
                print(f"  - {r['field']}: {r['status']}")
    avg = round(total_pct / len(results), 1)
    print(f"\nAverage cross-store compatibility (cached): {avg}%")
    print("Note: Re-run live pipeline after deploy for updated scores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
