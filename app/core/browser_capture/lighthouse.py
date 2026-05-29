"""
Real Lighthouse audit via Lighthouse CLI.
Falls back to CDP metrics or heuristics when CLI is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


async def _collect_cdp_metrics(page) -> dict[str, Any]:
    """Collect Core Web Vitals via Chrome DevTools Protocol (fallback only)."""
    metrics: dict[str, Any] = {}
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Performance.enable")
        perf = await cdp.send("Performance.getMetrics")
        for m in perf.get("metrics", []):
            metrics[m["name"]] = m["value"]

        nav_timing = await page.evaluate("""() => {
            const t = performance.timing || {};
            const nav = performance.getEntriesByType('navigation')[0] || {};
            return {
                domContentLoaded: t.domContentLoadedEventEnd - t.navigationStart,
                loadComplete: t.loadEventEnd - t.navigationStart,
                ttfb: t.responseStart - t.navigationStart,
                domInteractive: t.domInteractive - t.navigationStart,
                transferSize: nav.transferSize || 0,
            };
        }""")
        metrics["navigation_timing"] = nav_timing

        paint = await page.evaluate("""() => {
            const entries = performance.getEntriesByType('paint');
            const result = {};
            for (const e of entries) result[e.name] = e.startTime;
            return result;
        }""")
        metrics["paint_timing"] = paint

        cls_data = await page.evaluate("""() => new Promise(resolve => {
            let cls = 0;
            try {
                const observer = new PerformanceObserver(list => {
                    for (const entry of list.getEntries()) {
                        if (!entry.hadRecentInput) cls += entry.value;
                    }
                });
                observer.observe({ type: 'layout-shift', buffered: true });
                setTimeout(() => resolve({ cls: cls }), 500);
            } catch(e) { resolve({ cls: null }); }
        })""")
        metrics["cls"] = cls_data.get("cls")

        await cdp.detach()
    except Exception:
        pass
    return metrics


def _score_from_metrics(cdp: dict[str, Any], html: str) -> dict[str, Any]:
    """Convert raw CDP metrics to Lighthouse-style category scores (0-100)."""
    nav = cdp.get("navigation_timing") or {}
    paint = cdp.get("paint_timing") or {}
    ttfb = nav.get("ttfb", 0)
    fcp = paint.get("first-contentful-paint", 0)
    dcl = nav.get("domContentLoaded", 0)
    cls = cdp.get("cls")

    def perf_score(ttfb_ms: float, fcp_ms: float, dcl_ms: float) -> int:
        s = 100
        if ttfb_ms > 800:
            s -= min(30, int((ttfb_ms - 800) / 50))
        if fcp_ms > 1800:
            s -= min(30, int((fcp_ms - 1800) / 100))
        if dcl_ms > 3000:
            s -= min(20, int((dcl_ms - 3000) / 200))
        return max(0, min(100, s))

    def a11y_score(html: str) -> int:
        s = 90
        if 'alt=""' in html or "alt=''" in html:
            s -= 10
        if not html or "<html" not in html.lower():
            return 50
        if 'lang="' not in html.lower() and "lang='" not in html.lower():
            s -= 15
        if 'role="button"' not in html and "<button" not in html.lower():
            s -= 5
        return max(0, min(100, s))

    def seo_score(html: str) -> int:
        s = 70
        low = html.lower()
        if "<title" in low:
            s += 10
        if 'name="description"' in low or "name='description'" in low:
            s += 10
        if "application/ld+json" in low:
            s += 5
        if 'rel="canonical"' in low:
            s += 5
        return max(0, min(100, s))

    def bp_score(html: str) -> int:
        s = 85
        if "http://" in html and "https://" not in html[:200]:
            s -= 20
        if re_search(r'<script[^>]*(?!async|defer)[^>]*src=', html):
            s -= 10
        return max(0, min(100, s))

    perf = perf_score(ttfb, fcp, dcl)
    a11y = a11y_score(html)
    seo = seo_score(html)
    bp = bp_score(html)

    cwv = {
        "LCP": {"value_ms": round(fcp * 1.2 if fcp else dcl, 0), "rating": _rating(fcp * 1.2 if fcp else dcl, 2500, 4000)},
        "FCP": {"value_ms": round(fcp, 0), "rating": _rating(fcp, 1800, 3000)},
        "TTFB": {"value_ms": round(ttfb, 0), "rating": _rating(ttfb, 800, 1800)},
        "CLS": {"value": round(cls, 3) if cls is not None else None, "rating": _cls_rating(cls)},
        "DOM_ContentLoaded": {"value_ms": round(dcl, 0)},
    }

    return {
        "performance": perf,
        "accessibility": a11y,
        "seo": seo,
        "best_practices": bp,
        "core_web_vitals": cwv,
        "source": "cdp",
    }


def _rating(value: float, good: float, poor: float) -> str:
    if value <= 0:
        return "unknown"
    if value <= good:
        return "good"
    if value <= poor:
        return "needs_improvement"
    return "poor"


def _cls_rating(cls: float | None) -> str:
    if cls is None:
        return "unknown"
    if cls <= 0.1:
        return "good"
    if cls <= 0.25:
        return "needs_improvement"
    return "poor"


def re_search(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def _lighthouse_cmd(url: str, out_path: Path) -> list[str] | None:
    """Build Lighthouse CLI command if binary is available."""
    lh = shutil.which("lighthouse")
    if lh:
        return [
            lh, url,
            "--output=json",
            f"--output-path={out_path}",
            "--quiet",
            "--only-categories=performance,accessibility,best-practices,seo",
            "--chrome-flags=--headless --no-sandbox --disable-gpu",
        ]
    npx = shutil.which("npx")
    if npx:
        return [
            npx, "--yes", "lighthouse", url,
            "--output=json",
            f"--output-path={out_path}",
            "--quiet",
            "--only-categories=performance,accessibility,best-practices,seo",
            "--chrome-flags=--headless --no-sandbox --disable-gpu",
        ]
    return None


async def _run_lighthouse_cli(url: str) -> dict[str, Any] | None:
    """Execute real Lighthouse CLI and return parsed report."""
    cmd = None
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "report.json"
        cmd = _lighthouse_cmd(url, out_path)
        if not cmd:
            return None
        try:
            proc = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, timeout=120),
            )
            if proc.returncode != 0 or not out_path.exists():
                return None
            data = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    cats = data.get("categories", {})
    categories = {
        "performance": round((cats.get("performance") or {}).get("score", 0) * 100),
        "accessibility": round((cats.get("accessibility") or {}).get("score", 0) * 100),
        "best_practices": round((cats.get("best-practices") or {}).get("score", 0) * 100),
        "seo": round((cats.get("seo") or {}).get("score", 0) * 100),
    }
    return {
        "available": True,
        "source": "lighthouse_cli",
        "categories": categories,
        "core_web_vitals": _extract_lh_cwv(data),
        "raw_report": data,
        "confidence": 0.95,
    }


def _extract_lh_cwv(data: dict) -> dict[str, Any]:
    audits = data.get("audits", {})
    cwv: dict[str, Any] = {}
    mapping = [
        ("LCP", "largest-contentful-paint", "value_ms"),
        ("FCP", "first-contentful-paint", "value_ms"),
        ("TTFB", "server-response-time", "value_ms"),
        ("CLS", "cumulative-layout-shift", "value"),
        ("INP", "interaction-to-next-paint", "value_ms"),
    ]
    for key, audit_key, val_key in mapping:
        audit = audits.get(audit_key, {})
        val = audit.get("numericValue")
        entry: dict[str, Any] = {
            val_key: round(val, 2) if val is not None else None,
            "rating": _lh_audit_rating(audit.get("score")),
        }
        cwv[key] = entry
    return cwv


def _lh_audit_rating(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.9:
        return "good"
    if score >= 0.5:
        return "needs_improvement"
    return "poor"


async def run_lighthouse_audit(url: str, html: str = "", page=None) -> dict[str, Any]:
    """
    Run real Lighthouse CLI audit (primary).
    Falls back to CDP metrics or HTML heuristics when CLI unavailable.
    """
    audit_url = url
    if page:
        try:
            audit_url = page.url or url
        except Exception:
            pass

    # Primary: real Lighthouse CLI
    cli_result = await _run_lighthouse_cli(audit_url)
    if cli_result:
        return cli_result

    # Fallback: CDP metrics from Playwright page
    if page:
        cdp = await _collect_cdp_metrics(page)
        scores = _score_from_metrics(cdp, html)
        return {
            "available": True,
            "source": "cdp",
            "categories": {
                "performance": scores["performance"],
                "accessibility": scores["accessibility"],
                "seo": scores["seo"],
                "best_practices": scores["best_practices"],
            },
            "core_web_vitals": scores["core_web_vitals"],
            "raw_metrics": cdp,
            "confidence": 0.75,
            "warnings": ["Lighthouse CLI unavailable — using CDP approximation"],
        }

    # Last resort: HTML heuristics
    if html:
        scores = _score_from_metrics({}, html)
        return {
            "available": True,
            "source": "heuristic",
            "categories": {
                "performance": scores["performance"],
                "accessibility": scores["accessibility"],
                "seo": scores["seo"],
                "best_practices": scores["best_practices"],
            },
            "core_web_vitals": scores["core_web_vitals"],
            "confidence": 0.45,
            "warnings": ["Lighthouse CLI unavailable — using HTML heuristics"],
        }

    return {"available": False, "confidence": 0.0, "source": "unavailable"}
