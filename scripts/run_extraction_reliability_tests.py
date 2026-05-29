#!/usr/bin/env python3
"""Run extraction reliability audits for priority PDP/homepage URLs."""
from __future__ import annotations

import asyncio
import json
import os
import sys
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

from scripts.run_mass_mode1_tests import run_single_audit  # noqa: E402

OUT = ROOT / "exports" / "extraction_reliability"
MASS_DIR = ROOT / "exports" / "mass_tests"

URLS = [
    {"url": "https://fitpass.co.in/", "category": "homepage"},
    {"url": "https://www.boat-lifestyle.com/products/airdopes-141", "category": "pdp"},
    {"url": "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth", "category": "pdp"},
    {
        "url": "https://www.killerjeans.com/products/killer-men-black-slim-fit-jeans-91134",
        "category": "pdp",
    },
]


async def run_one(spec: dict) -> dict:
    os.environ["DEMO_MODE"] = os.environ.get("DEMO_MODE", "true")
    os.environ["SKIP_PLAYWRIGHT"] = "false"
    bundle, summary_row, error = await run_single_audit(spec, timeout_sec=300.0)
    frontend = bundle.get("frontend_api_payload") or {}
    jsd = frontend.get("json_structured_data") or {}
    ec = bundle.get("extraction_confidence") or jsd.get("_extraction_confidence") or {}
    return {
        "url": spec["url"],
        "category": spec["category"],
        "export_dir": summary_row.get("export_dir"),
        "error": error,
        "product_name": jsd.get("product_name"),
        "price": jsd.get("price"),
        "has_reviews": jsd.get("has_reviews"),
        "review_count": jsd.get("review_count"),
        "overall_confidence": ec.get("overall_extraction_confidence"),
        "price_confidence": ec.get("price_confidence"),
        "missing": ec.get("missing_critical_fields"),
        "scraper_method": bundle.get("scraper_method"),
        "platform": (bundle.get("platform_info") or {}).get("platform"),
        "network_captures": bundle.get("network_payloads_count"),
        "strategies": jsd.get("_extraction_strategies"),
        "passed": summary_row.get("passed"),
    }


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in URLS:
        print(f"\n=== {spec['url']} ===")
        try:
            r = await run_one(spec)
            results.append(r)
            print(
                f"  conf={r['overall_confidence']} price={r['price']} "
                f"name={r['product_name']!r} method={r['scraper_method']} platform={r['platform']}"
            )
        except Exception as exc:
            print(f"  FAILED: {exc}")
            results.append({"url": spec["url"], "error": str(exc)})
    summary_path = OUT / f"summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
