#!/usr/bin/env python3
"""
Run Mode 1 benchmarks against sample_urls.json.

Usage:
  python benchmarks/benchmark_runner.py [--limit 5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.extraction_confidence import score_extraction_confidence
from app.agents.scrape_validator import validate_scrape
from app.agents.scraper_agent import scraper_agent
from app.agents.validator_agent import validate_agent_reports


async def run_one(url: str, expect: dict) -> dict:
    state = {
        "url": url,
        "status": "running",
        "agent_reports": [],
        "errors": [],
    }
    t0 = time.monotonic()
    state = await scraper_agent(state)  # type: ignore[assignment]
    if state.get("status") == "failed":
        return {"url": url, "ok": False, "error": state.get("errors"), "latency_ms": int((time.monotonic() - t0) * 1000)}

    validation = validate_scrape(
        markdown=state.get("markdown_content") or "",
        scrape_html=state.get("scrape_html") or "",
        dom_technical_seo=state.get("dom_technical_seo") or {},
        url=url,
    )
    latency = int((time.monotonic() - t0) * 1000)
    checks_passed = 0
    checks_total = 0
    if expect.get("min_words"):
        checks_total += 1
        if validation.get("word_count", 0) >= expect["min_words"]:
            checks_passed += 1
    if expect.get("detected_page_type"):
        checks_total += 1
        if validation.get("detected_page_type") == expect["detected_page_type"]:
            checks_passed += 1
    if expect.get("has_price") is not None:
        checks_total += 1
        if "pricing" not in validation.get("missing_sections", []):
            checks_passed += 1

    return {
        "url": url,
        "ok": validation.get("usable_for_analysis", False),
        "scrape_quality": validation.get("scrape_quality"),
        "confidence": validation.get("confidence"),
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "latency_ms": latency,
        "warnings": validation.get("warnings", []),
    }


async def main(limit: int) -> None:
    sample_path = Path(__file__).parent / "sample_urls.json"
    cases = json.loads(sample_path.read_text(encoding="utf-8"))[:limit]
    results = []
    for case in cases:
        print(f"Benchmarking {case['url']}...")
        results.append(await run_one(case["url"], case.get("expect") or {}))

    ok = sum(1 for r in results if r.get("ok"))
    avg_lat = sum(r.get("latency_ms", 0) for r in results) / max(len(results), 1)
    print("\n=== Benchmark Summary ===")
    print(f"URLs tested: {len(results)}")
    print(f"Usable scrapes: {ok}/{len(results)} ({100*ok/max(len(results),1):.0f}%)")
    print(f"Avg scrape latency: {avg_lat:.0f}ms")
    out = Path(__file__).parent / "last_run.json"
    out.write_text(json.dumps({"results": results, "summary": {"ok": ok, "total": len(results)}}, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.limit))
