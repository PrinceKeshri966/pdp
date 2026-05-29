#!/usr/bin/env python3
"""Re-validate Boat + Mamaearth extraction after HIGH-priority fixes."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ground_truth_validation import (
    OUT,
    compare_site,
    extract_ground_truth,
    run_pipeline,
    _pipeline_fields,
)

BEFORE = {
    "Boat Lifestyle": {"field_accuracy_pct": 47.1, "extraction_accuracy_pct": 44.4, "MATCH": 6, "MISMATCH": 7},
    "Mamaearth": {"field_accuracy_pct": 61.8, "extraction_accuracy_pct": 72.2, "MATCH": 10, "MISMATCH": 6},
}

SITES = [
    {"name": "Boat Lifestyle", "url": "https://www.boat-lifestyle.com/products/airdopes-181-pro-bluetooth-earbuds"},
    {"name": "Mamaearth", "url": "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth-hair-fall-control-with-redensyl-200ml"},
]


async def main():
    results = []
    for site in SITES:
        print(f"\n=== {site['name']} ===")
        gt = await extract_ground_truth(site["url"])
        state = await run_pipeline(gt.get("pdp_url") or site["url"])
        pf = _pipeline_fields(state)
        comp = compare_site(site["name"], site["url"], gt, pf)
        results.append(comp)
        slug = site["name"].lower().replace(" ", "_")
        (OUT / f"{slug}_post_fix.json").write_text(
            json.dumps({"ground_truth": gt, "pipeline": pf, "comparison": comp}, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  MATCH={comp['counts']['MATCH']} MISMATCH={comp['counts']['MISMATCH']} accuracy={comp['field_accuracy_pct']}%")

    print("\n=== Before vs After ===")
    print("| Site | Field Accuracy Before | After | Extraction Before | After |")
    print("|------|----------------------|-------|-------------------|-------|")
    for comp in results:
        b = BEFORE[comp["name"]]
        print(
            f"| {comp['name']} | {b['field_accuracy_pct']}% | {comp['field_accuracy_pct']}% | "
            f"{b['extraction_accuracy_pct']}% | {comp['extraction_accuracy_pct']}% |"
        )
    return results


if __name__ == "__main__":
    try:
        import langchain
        if not hasattr(langchain, "debug"):
            langchain.debug = False
    except Exception:
        pass
    asyncio.run(main())
