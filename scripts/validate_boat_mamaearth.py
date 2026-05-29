#!/usr/bin/env python3
"""Validate Boat + Mamaearth only."""
import asyncio, json, sys
from pathlib import Path
try:
    import langchain
    if not hasattr(langchain, "debug"):
        langchain.debug = False
except Exception:
    pass
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ground_truth_validation import (
    SITES, extract_ground_truth, run_pipeline, compare_site, _pipeline_fields, OUT, TENANT, USER
)

TARGETS = {"Boat Lifestyle", "Mamaearth"}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for site in SITES:
        if site["name"] not in TARGETS:
            continue
        print(f"=== {site['name']} ===")
        gt = await extract_ground_truth(site["url"])
        pdp = gt.get("pdp_url") or site["url"]
        state = await run_pipeline(pdp)
        pf = _pipeline_fields(state)
        cmp = compare_site(site["name"], site["url"], gt, pf)
        slug = site["name"].lower().replace(" ", "_")
        path = OUT / f"{slug}_ground_truth.json"
        path.write_text(json.dumps({"ground_truth": gt, "pipeline": pf, "comparison": cmp}, indent=2), encoding="utf-8")
        print(f"field={cmp['field_accuracy_pct']}% extraction={cmp['extraction_accuracy_pct']}%")
        print(f"M={cmp['counts']['MATCH']} P={cmp['counts']['PARTIAL MATCH']} X={cmp['counts']['MISMATCH']}")


if __name__ == "__main__":
    asyncio.run(main())
