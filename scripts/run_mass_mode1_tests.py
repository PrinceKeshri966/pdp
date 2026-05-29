#!/usr/bin/env python3
"""
Mass Mode 1 validation for CTO demo — runs audits, exports bundles, benchmark reports.

Usage:
  python scripts/run_mass_mode1_tests.py --category homepage
  python scripts/run_mass_mode1_tests.py --url https://fitpass.co.in/
  python scripts/run_mass_mode1_tests.py --demo
  DEMO_MODE=true python scripts/run_mass_mode1_tests.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "exports"
MASS_DIR = OUT / "mass_tests"

# LangGraph/LangChain compat
try:
    import langchain

    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
except Exception:
    pass

TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000002"
MAX_AUDIT_MS = 5 * 60 * 1000

PDP_LEAKAGE_RE = re.compile(
    r"size guide|size chart|shipping policy|return policy|material composition|fit description",
    re.I,
)

# ── Test matrix (exact URLs from CTO validation spec) ─────────────────────────
URL_SPECS: list[dict[str, Any]] = [
    # HOMEPAGES
    {"url": "https://fitpass.co.in/", "category": "homepage", "expected_page_types": ["homepage", "saas_landing"]},
    {"url": "https://www.boat-lifestyle.com/", "category": "homepage", "expected_page_types": ["homepage", "marketplace", "pdp"]},
    {"url": "https://mamaearth.in/", "category": "homepage", "expected_page_types": ["homepage", "marketplace"]},
    {"url": "https://www.cult.fit/", "category": "homepage", "expected_page_types": ["homepage", "saas_landing"]},
    {"url": "https://www.nykaa.com/", "category": "homepage", "expected_page_types": ["homepage", "marketplace"]},
    # PDP
    {"url": "https://www.boat-lifestyle.com/products/airdopes-141", "category": "pdp", "expected_page_types": ["pdp", "product"]},
    {"url": "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth", "category": "pdp", "expected_page_types": ["pdp", "product", "marketplace"]},
    {"url": "https://www.nykaa.com/maybelline-new-york-fit-me-matte-poreless-foundation", "category": "pdp", "expected_page_types": ["pdp", "product", "marketplace"]},
    {"url": "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4", "category": "pdp", "expected_page_types": ["pdp", "product", "marketplace", "unknown"]},
    {"url": "https://www.amazon.in/dp/B0CHX1W1XY", "category": "pdp", "expected_page_types": ["pdp", "product", "marketplace", "unknown"]},
    # SAAS / LANDING
    {"url": "https://www.notion.so/", "category": "saas", "expected_page_types": ["saas_landing", "homepage", "unknown"]},
    {"url": "https://slack.com/intl/en-in/", "category": "saas", "expected_page_types": ["saas_landing", "homepage"]},
    {"url": "https://zapier.com/", "category": "saas", "expected_page_types": ["saas_landing", "homepage"]},
    {"url": "https://www.shopify.com/in", "category": "saas", "expected_page_types": ["saas_landing", "homepage", "marketplace"]},
    {"url": "https://www.canva.com/", "category": "saas", "expected_page_types": ["saas_landing", "homepage"]},
    # BLOG
    {"url": "https://blog.hubspot.com/marketing/seo-tips", "category": "blog", "expected_page_types": ["blog", "unknown"]},
    {"url": "https://neilpatel.com/blog/", "category": "blog", "expected_page_types": ["blog", "homepage"]},
    {"url": "https://backlinko.com/seo-techniques", "category": "blog", "expected_page_types": ["blog", "unknown"]},
    {"url": "https://blog.shopify.com/", "category": "blog", "expected_page_types": ["blog", "homepage"]},
    {"url": "https://ahrefs.com/blog/", "category": "blog", "expected_page_types": ["blog", "homepage"]},
    # EDGE
    {"url": "https://httpstat.us/404", "category": "edge", "expected_page_types": None, "safe_failure": True},
    {"url": "https://example.com/", "category": "edge", "expected_page_types": ["homepage", "unknown"], "safe_failure": True},
    {"url": "https://expired.badssl.com/", "category": "edge", "expected_page_types": None, "safe_failure": True},
    {"url": "https://www.linkedin.com/", "category": "edge", "expected_page_types": ["homepage", "unknown", "saas_landing"], "safe_failure": True},
    {"url": "https://www.instagram.com/", "category": "edge", "expected_page_types": ["homepage", "unknown"], "safe_failure": True},
]

NON_PDP_CATEGORIES = {"homepage", "saas", "blog", "edge"}


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def url_slug(url: str) -> str:
    p = urlparse(url)
    host = (p.netloc or "unknown").replace("www.", "").replace(".", "_")
    path = (p.path or "").strip("/").replace("/", "_")[:40] or "root"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"{host}_{path}")[:60]


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
        "report_id": "mass-test",
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


def agent_timings(agent_reports: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in agent_reports or []:
        name = r.get("agent") or "unknown"
        out[name] = int(r.get("duration_ms") or 0)
    return out


def check_pdp_leakage(state: dict) -> list[str]:
    ux = state.get("ux_report") or {}
    flags: list[str] = []
    blob = " ".join(
        str(x)
        for x in (ux.get("friction_points") or [])
        + (ux.get("conversion_blockers") or [])
        + (ux.get("recommendations") or [])
    )
    for m in PDP_LEAKAGE_RE.finditer(blob):
        flags.append(m.group(0).lower())
    rel = state.get("audit_reliability") or {}
    for hf in rel.get("hallucination_flags") or []:
        if "pdp_leakage" in str(hf):
            flags.append(str(hf))
    return list(dict.fromkeys(flags))


def check_fake_reviews(state: dict) -> bool:
    ux = state.get("ux_report") or {}
    structured = state.get("json_structured_data") or {}
    ux_rev = bool((ux.get("trust_signals") or {}).get("reviews_present"))
    ext_rev = bool(structured.get("has_reviews"))
    psych_facts = state.get("psychology_preprocessor_facts") or {}
    return ux_rev and not ext_rev and not psych_facts.get("has_reviews")


def evaluate_result(spec: dict, state: dict, *, duration_ms: int, error: str | None) -> dict[str, Any]:
    """Return benchmark row + pass/fail reasons."""
    ar = state.get("audit_reliability") or {}
    vr = state.get("validation_report") or {}
    ec = state.get("extraction_confidence") or {}
    page_type = (
        (state.get("page_type_info") or {}).get("page_type")
        or ar.get("page_type")
        or (state.get("scrape_validation") or {}).get("page_type")
        or "unknown"
    )
    if page_type == "product":
        page_type = "pdp"

    contradictions = vr.get("contradictions_found") or ar.get("contradictions") or []
    severity = vr.get("contradiction_severity") or "low"
    hall_flags = vr.get("hallucination_flags") or ar.get("hallucination_flags") or []
    ext_conf = float(ec.get("overall_extraction_confidence") or 0)
    reliability = ar.get("report_reliability") or vr.get("report_reliability") or "medium"
    leakage = check_pdp_leakage(state) if spec["category"] in NON_PDP_CATEGORIES else []
    fake_reviews = check_fake_reviews(state)
    pricing_hallucination = any("pricing_without_evidence" in str(f) for f in hall_flags)

    fail_reasons: list[str] = []
    pass_reasons: list[str] = []

    if error:
        fail_reasons.append(f"crash: {error}")
    if duration_ms > MAX_AUDIT_MS:
        fail_reasons.append(f"timeout: {duration_ms}ms > {MAX_AUDIT_MS}ms")
    if state.get("status") == "failed":
        fail_reasons.append("pipeline status failed")

    expected = spec.get("expected_page_types")
    if expected and page_type not in expected and page_type != "unknown":
        fail_reasons.append(f"page_type mismatch: got {page_type}, expected one of {expected}")
    elif expected and page_type in expected:
        pass_reasons.append(f"page_type OK: {page_type}")

    if severity == "high" or len(contradictions) >= 3:
        fail_reasons.append(f"severe contradictions ({len(contradictions)})")
    elif contradictions:
        pass_reasons.append("contradictions below severe threshold")

    if leakage and spec["category"] in NON_PDP_CATEGORIES:
        fail_reasons.append(f"PDP leakage: {leakage[:3]}")
    else:
        pass_reasons.append("no PDP leakage")

    if pricing_hallucination:
        fail_reasons.append("hallucinated pricing")
    if fake_reviews:
        fail_reasons.append("fake reviews (UX vs extractor)")

    if ext_conf < 0.45 and reliability == "high":
        fail_reasons.append("reliability falsely high vs low extraction")

    safe = spec.get("safe_failure", False)
    if safe and not error and duration_ms <= MAX_AUDIT_MS:
        if reliability in ("low", "medium") or state.get("partial_analysis") or ar.get("scrape_quality") == "low":
            pass_reasons.append("safe failure handled")
        elif state.get("status") != "failed":
            pass_reasons.append("edge URL completed without crash")

    passed = len(fail_reasons) == 0
    if safe and not passed and not error and state.get("status") != "failed":
        # Edge URLs: passing = graceful degradation
        if not fake_reviews and not pricing_hallucination and severity != "high":
            passed = True
            pass_reasons.append("edge case graceful pass")

    plan = state.get("agent_plan") or {}
    return {
        "url": spec["url"],
        "category": spec["category"],
        "page_type": page_type,
        "scrape_quality": ar.get("scrape_quality") or (state.get("scrape_validation") or {}).get("scrape_quality"),
        "report_reliability": reliability,
        "hallucination_risk": ar.get("hallucination_risk") or vr.get("hallucination_risk"),
        "audit_duration_ms": duration_ms,
        "agent_execution_plan": plan.get("audit_depth") or state.get("audit_depth") or "standard",
        "overall_score": (state.get("final_diagnosis") or {}).get("overall_health_score"),
        "contradictions_found": len(contradictions),
        "warnings_count": len(ar.get("warnings") or vr.get("warnings") or []),
        "visual_verification": bool(ar.get("visual_verified") or (state.get("visual_ux_facts") or {}).get("capture_ok")),
        "extraction_confidence": ext_conf,
        "passed": passed,
        "fail_reasons": fail_reasons,
        "pass_reasons": pass_reasons,
        "hallucination_flags": hall_flags,
        "pdp_leakage_detected": leakage,
    }


async def run_single_audit(spec: dict, *, timeout_sec: float) -> tuple[dict, dict, str | None]:
    from app.agents.mode1_graph import run_mode1
    from app.agents.scoring_engine import compute_deterministic_scores

    url = spec["url"]
    slug = url_slug(url)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = MASS_DIR / f"{slug}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AUDIT_EXPORT_DIR"] = str(run_dir)

    t0 = time.monotonic()
    error: str | None = None
    state: dict = {"status": "failed", "errors": ["not started"]}

    try:
        state = await asyncio.wait_for(
            run_mode1(
                url=url,
                tenant_id=TENANT,
                user_id=USER,
                competitor_urls=[],
                compare_as="auto",
            ),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        error = f"timeout after {timeout_sec}s"
    except Exception as exc:
        error = str(exc)
        traceback.print_exc()

    duration_ms = int((time.monotonic() - t0) * 1000)

    det_scores = compute_deterministic_scores(
        seo_facts=state.get("seo_preprocessor_facts"),
        seo_report=state.get("seo_report"),
        ux_facts=state.get("ux_preprocessor_facts"),
        aeo_report=state.get("aeo_report"),
        scrape_validation=state.get("scrape_validation"),
        extraction_confidence=state.get("extraction_confidence"),
        page_type=(state.get("page_type_info") or {}).get("page_type"),
        visual_ux_facts=state.get("visual_ux_facts"),
    )

    frontend = build_frontend_payload(state, url)
    timings = {
        "total_ms": duration_ms,
        "per_agent_ms": agent_timings(state.get("agent_reports") or []),
        "scrape_retry_count": state.get("scrape_retry_count") or 0,
        "scrape_retry_methods": state.get("scrape_retry_methods") or [],
    }

    bundle = {
        "meta": {"url": url, "category": spec["category"], "exported_at": datetime.now(timezone.utc).isoformat(), "duration_ms": duration_ms, "error": error},
        "scraper_method": state.get("scraper_method"),
        "platform_info": state.get("platform_info"),
        "network_payloads_count": len(state.get("network_payloads") or []),
        "json_structured_data": state.get("json_structured_data"),
        "scrape_validation": state.get("scrape_validation"),
        "page_type_info": state.get("page_type_info"),
        "agent_plan": state.get("agent_plan"),
        "extraction_confidence": state.get("extraction_confidence"),
        "validation_report": state.get("validation_report"),
        "audit_reliability": state.get("audit_reliability"),
        "deterministic_scores": state.get("deterministic_scores") or det_scores,
        "visual_ux_facts": state.get("visual_ux_facts"),
        "run_analytics": state.get("run_analytics"),
        "final_diagnosis": state.get("final_diagnosis"),
        "autofix_report": state.get("autofix_report"),
        "agent_reports": state.get("agent_reports"),
        "errors": state.get("errors"),
        "frontend_api_payload": frontend,
    }

    summary_row = evaluate_result(spec, state, duration_ms=duration_ms, error=error)
    summary_row["export_dir"] = str(run_dir)

    (run_dir / "FULL_BUNDLE.json").write_text(json.dumps(bundle, indent=2, default=_json_default), encoding="utf-8")
    (run_dir / "frontend_payload.json").write_text(json.dumps(frontend, indent=2, default=_json_default), encoding="utf-8")
    (run_dir / "summary_metrics.json").write_text(json.dumps(summary_row, indent=2), encoding="utf-8")
    (run_dir / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    (run_dir / "reliability.json").write_text(
        json.dumps(state.get("audit_reliability") or {}, indent=2, default=_json_default),
        encoding="utf-8",
    )

    return bundle, summary_row, error


def aggregate_performance(rows: list[dict], all_timings: list[dict]) -> dict[str, Any]:
    agent_totals: dict[str, list[int]] = {}
    depths = {"lightweight": 0, "standard": 0, "deep": 0}
    cache_hits = 0
    cache_eligible = 0
    competitor_ms: list[int] = []
    retries = 0
    durations: list[int] = []
    tokens_in = tokens_out = 0

    for row in rows:
        depths[row.get("agent_execution_plan") or "standard"] = depths.get(row.get("agent_execution_plan") or "standard", 0) + 1
        durations.append(int(row.get("audit_duration_ms") or 0))
        bpath = Path(row.get("export_dir", "")) / "FULL_BUNDLE.json"
        if bpath.is_file():
            b = json.loads(bpath.read_text(encoding="utf-8"))
            ra = b.get("run_analytics") or {}
            tot = ra.get("totals") or {}
            tokens_in += int(tot.get("input_tokens") or 0)
            tokens_out += int(tot.get("output_tokens") or 0)
            comp = b.get("competitor_report") or {}
            sites = (comp.get("live_compare") or {}).get("sites") or []
            for s in sites:
                if s.get("role") == "competitor":
                    cache_eligible += 1
                    if s.get("from_cache"):
                        cache_hits += 1

    for t in all_timings:
        retries += int(t.get("scrape_retry_count") or 0)
        for agent, ms in (t.get("per_agent_ms") or {}).items():
            agent_totals.setdefault(agent, []).append(ms)
            if agent == "competitor_agent":
                competitor_ms.append(ms)

    slowest = sorted(
        ((a, int(sum(v) / max(len(v), 1))) for a, v in agent_totals.items()),
        key=lambda x: -x[1],
    )[:10]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_count": len(rows),
        "average_audit_time_ms": int(sum(durations) / max(len(durations), 1)),
        "median_audit_time_ms": sorted(durations)[len(durations) // 2] if durations else 0,
        "slowest_agents_avg_ms": [{"agent": a, "avg_ms": m} for a, m in slowest],
        "competitor_avg_ms": int(sum(competitor_ms) / max(len(competitor_ms), 1)) if competitor_ms else 0,
        "competitor_max_ms": max(competitor_ms) if competitor_ms else 0,
        "audit_depth_counts": depths,
        "total_scrape_retries": retries,
        "cache_hit_rate": round(cache_hits / max(cache_eligible, 1), 2),
        "competitor_cache_hits": cache_hits,
        "token_estimates": {"input": tokens_in, "output": tokens_out},
        "demo_mode": os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"),
    }


def write_cto_demo_summary(rows: list[dict], perf: dict) -> None:
    passed = [r for r in rows if r.get("passed")]
    failed = [r for r in rows if not r.get("passed")]
    avg_lat = perf.get("average_audit_time_ms", 0) / 1000
    rel_high = sum(1 for r in rows if r.get("report_reliability") == "high")
    rel_low = sum(1 for r in rows if r.get("report_reliability") == "low")

    lines = [
        "# OptiPDP CTO Demo Summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive metrics",
        "",
        f"- **URLs tested:** {len(rows)}",
        f"- **Success rate:** {len(passed)}/{len(rows)} ({100 * len(passed) / max(len(rows), 1):.0f}%)",
        f"- **Average latency:** {avg_lat:.1f}s",
        f"- **Reliability high / low:** {rel_high} / {rel_low}",
        "",
        "## URLs tested",
        "",
    ]
    for r in rows:
        status = "PASS" if r.get("passed") else "FAIL"
        lines.append(
            f"- [{status}] `{r['url']}` — {r.get('page_type')} — "
            f"reliability {r.get('report_reliability')} — {r.get('audit_duration_ms', 0) / 1000:.0f}s"
        )

    lines.extend(
        [
            "",
            "## Hallucination prevention examples",
            "",
            "- PDP-only terms (size guide, shipping policy) filtered on homepage/SaaS/blog via rulesets + validator flags",
            "- Pricing recommendations flagged when `price_confidence` is zero",
            "- UX vs extractor review mismatch raises contradictions",
            "",
            "## Page-type specialization examples",
            "",
        ]
    )
    for r in [x for x in rows if x.get("category") == "homepage"][:3]:
        lines.append(f"- `{r['url']}` detected as **{r.get('page_type')}** (non-PDP checks only)")
    for r in [x for x in rows if x.get("category") == "pdp"][:3]:
        lines.append(f"- `{r['url']}` detected as **{r.get('page_type')}** (full PDP UX checklist)")

    lines.extend(
        [
            "",
            "## Reliability system examples",
            "",
            "- Scores capped when scrape quality is low or extraction confidence < 0.45",
            "- `contradiction_severity` and `confidence_penalty` downgrade report reliability",
            "- Partial analysis mode avoids overconfident scores on bot-blocked pages",
            "",
            "## Visual UX examples",
            "",
            "- Playwright captures desktop/mobile when `SKIP_PLAYWRIGHT` is not true",
            "- Text-only UX clearly labeled in frontend when visual verification unavailable",
            "",
            "## Competitor benchmarking",
            "",
            f"- Average competitor agent latency: {perf.get('competitor_avg_ms', 0) / 1000:.1f}s",
            "- Parallel scrapes + Redis/memory cache (24h homepage / 12h PDP TTL)",
            "",
            "## Deployable fixes",
            "",
            "- `autofix_report.deployable_fixes`: FAQ schema, OG tags, canonical, breadcrumb JSON-LD",
            "- Template-first prioritization; Haiku only on deep audits",
            "",
            "## Safe failure handling",
            "",
        ]
    )
    for r in [x for x in rows if x.get("category") == "edge"]:
        st = "PASS" if r.get("passed") else "FAIL"
        lines.append(f"- [{st}] `{r['url']}` — {', '.join(r.get('fail_reasons') or ['completed safely'])}")

    if failed:
        lines.extend(["", "## Failed URLs (investigate before demo)", ""])
        for r in failed:
            lines.append(f"- `{r['url']}`: {'; '.join(r.get('fail_reasons') or ['unknown'])}")

    (OUT / "cto_demo_summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_demo_checklist(rows: list[dict]) -> None:
    passed = [r for r in rows if r.get("passed")]

    def best(category: str, key: str, reverse: bool = True) -> list[dict]:
        pool = [r for r in passed if r.get("category") == category]
        return sorted(pool, key=lambda x: x.get(key) or 0, reverse=reverse)[:3]

    lines = [
        "# CTO Demo Checklist",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Best overall performers",
        "",
    ]
    for r in sorted(passed, key=lambda x: x.get("overall_score") or 0, reverse=True)[:5]:
        lines.append(
            f"- `{r['url']}` — score {r.get('overall_score')} — reliability {r.get('report_reliability')}"
        )

    lines.extend(["", "## Showcase by capability", ""])
    sections = [
        ("PDP intelligence", "pdp", "overall_score"),
        ("UX analysis", "homepage", "overall_score"),
        ("AI visibility", "blog", "overall_score"),
        ("Deployable fixes", "pdp", "overall_score"),
        ("Competitor comparison", "homepage", "audit_duration_ms"),
        ("Contradiction handling (reliable low scores)", "edge", "extraction_confidence"),
    ]
    for title, cat, metric in sections:
        lines.append(f"### {title}")
        pool = [r for r in rows if r.get("category") == cat]
        if metric == "audit_duration_ms":
            picks = sorted(pool, key=lambda x: x.get(metric) or 999999)[:3]
        else:
            picks = sorted(pool, key=lambda x: x.get(metric) or 0, reverse=True)[:3]
        for p in picks:
            lines.append(f"- `{p['url']}` ({p.get('page_type')}, reliability {p.get('report_reliability')})")
        lines.append("")

    lines.extend(
        [
            "## Pre-demo setup",
            "",
            "1. Set `DEMO_MODE=true` for faster standard-depth audits",
            "2. Optional: `SKIP_PLAYWRIGHT=false` for visual verification on 1–2 hero URLs",
            "3. Run `python scripts/run_mass_mode1_tests.py --category homepage --demo` to warm cache",
            "4. Open frontend reliability banner — confirm page type + audit depth chips",
            "",
            "## Recommended live demo URLs",
            "",
            "- **Homepage/SaaS:** https://fitpass.co.in/ or https://www.cult.fit/",
            "- **PDP:** https://www.boat-lifestyle.com/products/airdopes-141",
            "- **Avoid live:** linkedin.com, instagram.com (login walls)",
            "",
        ]
    )
    (OUT / "demo_checklist.md").write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    MASS_DIR.mkdir(parents=True, exist_ok=True)

    if args.demo:
        os.environ["DEMO_MODE"] = "true"

    specs = URL_SPECS
    if args.url:
        specs = [s for s in URL_SPECS if s["url"] == args.url]
        if not specs:
            specs = [{"url": args.url, "category": "custom", "expected_page_types": None}]
    elif args.category != "all":
        specs = [s for s in URL_SPECS if s["category"] == args.category]

    if args.limit:
        specs = specs[: args.limit]

    print(f"Mass Mode 1 tests: {len(specs)} URLs (demo_mode={os.getenv('DEMO_MODE', 'false')})")
    rows: list[dict] = []
    all_timings: list[dict] = []

    for i, spec in enumerate(specs, 1):
        print(f"\n[{i}/{len(specs)}] {spec['url']}")
        _bundle, row, err = await run_single_audit(spec, timeout_sec=args.timeout)
        rows.append(row)
        if err:
            print(f"  ERROR: {err}")
        else:
            print(f"  {'PASS' if row['passed'] else 'FAIL'} — {row['page_type']} — {row['audit_duration_ms']}ms")
        tpath = Path(row.get("export_dir", "")) / "timings.json"
        if tpath.is_file():
            all_timings.append(json.loads(tpath.read_text(encoding="utf-8")))

    benchmark = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo_mode": os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"),
        "total": len(rows),
        "passed": sum(1 for r in rows if r.get("passed")),
        "failed": sum(1 for r in rows if not r.get("passed")),
        "results": rows,
    }
    (OUT / "benchmark_summary.json").write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    perf = aggregate_performance(rows, all_timings)
    (OUT / "performance_summary.json").write_text(json.dumps(perf, indent=2), encoding="utf-8")

    write_cto_demo_summary(rows, perf)
    write_demo_checklist(rows)

    print("\n" + "=" * 60)
    print(f"Done: {benchmark['passed']}/{benchmark['total']} passed")
    print(f"  {OUT / 'benchmark_summary.json'}")
    print(f"  {OUT / 'performance_summary.json'}")
    print(f"  {OUT / 'cto_demo_summary.md'}")
    print(f"  {OUT / 'demo_checklist.md'}")
    return 0 if benchmark["failed"] == 0 else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mass Mode 1 CTO validation")
    p.add_argument("--category", default="all", choices=["all", "homepage", "pdp", "saas", "blog", "edge"])
    p.add_argument("--url", default="", help="Run a single URL only")
    p.add_argument("--limit", type=int, default=0, help="Max URLs to run (0 = no limit)")
    p.add_argument("--timeout", type=float, default=300.0, help="Per-URL timeout seconds")
    p.add_argument("--demo", action="store_true", help="Set DEMO_MODE=true")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
