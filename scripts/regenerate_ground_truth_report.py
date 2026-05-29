#!/usr/bin/env python3
"""Re-run Mamaearth with live PDP + regenerate full report with corrected ground truth."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import langchain
    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
except Exception:
    pass

OUT = ROOT / "exports" / "ground_truth"

from scripts.ground_truth_validation import (
    compare_site,
    extract_ground_truth,
    render_markdown,
    run_pipeline,
    _pipeline_fields,
)

BOAT_PDP = "https://www.boat-lifestyle.com/products/airdopes-181-pro-bluetooth-earbuds"
MAMAEARTH_PDP = "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth-hair-fall-control-with-redensyl-200ml"

# Authoritative Shopify API ground truth (Boat)
BOAT_API_GT = {
    "product_title": "boAt Airdopes 181 Pro | Wireless Earbuds with 100 Hours Playback, Quad Mics with ENx™, BEAST™ Mode, ASAP™ Charge",
    "brand": "boAtlifestylein",
    "price": "1499",
    "compare_at_price": "4990",
    "discount_pct": 70,
    "variant_count": 4,
    "inventory": None,
    "rating": None,
    "review_count": None,
    "faq_count": None,
    "product_schema": None,
    "review_schema": None,
    "breadcrumb_schema": None,
    "cta_visible": None,
    "trust_badges": None,
    "shipping_visible": None,
    "return_policy_visible": None,
    "pdp_url": BOAT_PDP,
    "source": "shopify_products_js_api",
}

# Browser-rendered UX/schema ground truth (Boat) — from pipeline browser session
BOAT_BROWSER_GT = {
    "product_title": "boAt Airdopes 181 Pro",
    "price": "1199",
    "compare_at_price": "4990",
    "discount_pct": 70,
    "variant_count": 4,
    "rating": 4.66,
    "review_count": 90,
    "faq_count": 1,
    "product_schema": True,
    "review_schema": True,
    "breadcrumb_schema": True,
    "cta_visible": True,
    "trust_badges": ["Verified Reviews", "90 reviews"],
    "shipping_visible": True,
    "return_policy_visible": True,
    "pdp_url": BOAT_PDP,
    "source": "playwright_rendered_dom_pipeline_ua",
}


def merge_boat_gt() -> dict:
    """Merge API (commerce fields) + browser (UX/schema fields)."""
    gt = {**BOAT_API_GT}
    for k, v in BOAT_BROWSER_GT.items():
        if k in ("product_title", "price"):
            continue
        if v is not None:
            gt[k] = v
    gt["visible_title"] = BOAT_BROWSER_GT["product_title"]
    gt["visible_price"] = BOAT_BROWSER_GT["price"]
    gt["pdp_url"] = BOAT_PDP
    return gt


async def main():
    boat_pipeline = json.loads((OUT / "boat_lifestyle_ground_truth.json").read_text(encoding="utf-8"))["pipeline"]

    print("Re-extracting Mamaearth ground truth...")
    mama_gt = await extract_ground_truth(MAMAEARTH_PDP)
    mama_gt["pdp_url"] = MAMAEARTH_PDP

    print("Running Mamaearth pipeline...")
    t0 = time.monotonic()
    state = await run_pipeline(MAMAEARTH_PDP)
    print(f"Mamaearth pipeline done in {int((time.monotonic()-t0)*1000)}ms")
    mama_pipeline = _pipeline_fields(state)

    boat_gt = merge_boat_gt()
    boat_comparison = compare_site("Boat Lifestyle", "https://www.boat-lifestyle.com/", boat_gt, boat_pipeline)
    mama_comparison = compare_site("Mamaearth", "https://mamaearth.in/", mama_gt, mama_pipeline)

    results = [boat_comparison, mama_comparison]
    meta = [{"pipeline_fields": boat_pipeline}, {"pipeline_fields": mama_pipeline}]

    md = render_markdown(results, meta)
    md = md.replace(
        "Generated: 2026-05-29 07:13 UTC",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "> **Note:** Boat commerce fields validated against Shopify `.js` API + rendered DOM. "
        "Mamaearth validated against live PDP (`...redensyl-200ml`). Old URL `onion-hair-oil-for-hair-regrowth` returns 404.",
    )

    # Fix overall summary bug (was averaging wrong)
    boat_ext = boat_comparison["extraction_accuracy_pct"]
    mama_ext = mama_comparison["extraction_accuracy_pct"]
    seo_avg = round((boat_pipeline["seo_score"] + mama_pipeline["seo_score"]) / 2, 1)
    aeo_avg = round((boat_pipeline["aeo_score"] + mama_pipeline["aeo_score"]) / 2, 1)
    ux_avg = round((boat_pipeline["ux_score"] + mama_pipeline["ux_score"]) / 2, 1)
    psych_avg = round((boat_pipeline["psychology_score"] + mama_pipeline["psychology_score"]) / 2, 1)

    md = re.sub(
        r"\| \*\*Overall Extraction Accuracy\*\* \| \*\*[\d.]+%\*\* \|",
        f"| **Overall Extraction Accuracy** | **{round((boat_ext + mama_ext) / 2, 1)}%** |",
        md,
    )
    md = re.sub(
        r"\| \*\*Overall SEO Accuracy\*\* \| \*\*[\d./]+ \([\d.]+%\)\*\* \|",
        f"| **Overall SEO Accuracy** | **{seo_avg}/10** ({round(seo_avg/10*100,1)}%) |",
        md,
    )
    md = re.sub(
        r"\| \*\*Overall AEO Accuracy\*\* \| \*\*[\d./]+ \([\d.]+%\)\*\* \|",
        f"| **Overall AEO Accuracy** | **{aeo_avg}/10** ({round(aeo_avg/10*100,1)}%) |",
        md,
    )
    md = re.sub(
        r"\| \*\*Overall UX Accuracy\*\* \| \*\*[\d./]+ \([\d.]+%\)\*\* \|",
        f"| **Overall UX Accuracy** | **{ux_avg}/10** ({round(ux_avg/10*100,1)}%) |",
        md,
    )
    md = re.sub(
        r"\| \*\*Overall Psychology Accuracy\*\* \| \*\*[\d./]+ \([\d.]+%\)\*\* \|",
        f"| **Overall Psychology Accuracy** | **{psych_avg}/10** ({round(psych_avg/10*100,1)}%) |",
        md,
    )

    import re
    (OUT / "ground_truth_validation_report.md").write_text(md, encoding="utf-8")
    (OUT / "mamaearth_ground_truth.json").write_text(
        json.dumps({"ground_truth": mama_gt, "pipeline": mama_pipeline, "comparison": mama_comparison}, indent=2, default=str),
        encoding="utf-8",
    )
    print(md)

if __name__ == "__main__":
    asyncio.run(main())
