#!/usr/bin/env python3
"""Capture CTO demo UI screenshots from exported frontend_payload.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_viewer_html(payload: dict, title: str) -> str:
    rel = payload.get("audit_reliability") or {}
    diag = payload.get("final_diagnosis") or {}
    autofix = payload.get("autofix_report") or {}
    comp = payload.get("competitor_report") or {}
    fixes = autofix.get("deployable_fixes") or []
    recs = diag.get("prioritized_recommendations") or []

    def esc(s):
        return json.dumps(str(s) if s is not None else "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>body{{font-family:system-ui;background:#f8fafc;padding:24px}}</style></head>
<body>
<h1 class="text-2xl font-black mb-4">{title}</h1>
<div id="reliability-banner" class="rounded-xl border p-4 mb-6 bg-amber-50 border-amber-200">
  <p class="font-bold text-amber-900">Audit reliability: {rel.get('report_reliability','—')}
    {'<span class="ml-2 px-2 py-0.5 bg-indigo-100 text-indigo-800 rounded text-xs">Demo Ready</span>' if rel.get('demo_mode') else ''}
  </p>
  <div class="grid grid-cols-3 gap-3 mt-3 text-sm">
    <div><span class="text-slate-500 text-xs uppercase">Page type</span><br><b>{rel.get('page_type') or rel.get('detected_page_type') or '—'}</b></div>
    <div><span class="text-slate-500 text-xs uppercase">Audit depth</span><br><b>{rel.get('audit_depth') or '—'}</b></div>
    <div><span class="text-slate-500 text-xs uppercase">Visual verified</span><br><b class="{'text-emerald-700' if rel.get('visual_verified') else 'text-amber-800'}">{'Yes' if rel.get('visual_verified') else 'Text-only'}</b></div>
    <div><span class="text-slate-500 text-xs uppercase">Scrape</span><br><b>{rel.get('scrape_quality')}</b></div>
    <div><span class="text-slate-500 text-xs uppercase">Extraction</span><br><b>{rel.get('extraction_confidence_pct', 0)}%</b></div>
    <div><span class="text-slate-500 text-xs uppercase">Hallucination risk</span><br><b>{rel.get('hallucination_risk')}</b></div>
  </div>
  {'<div id="contradictions" class="mt-3 p-2 bg-amber-100 border border-amber-300 rounded text-sm"><b>Contradictions:</b> ' + ' · '.join(rel.get('contradictions') or []) + '</div>' if rel.get('contradictions') else ''}
  {'<div class="mt-2 p-2 bg-red-50 border border-red-200 rounded text-sm"><b>Flags:</b> ' + ' · '.join(rel.get('hallucination_flags') or []) + '</div>' if rel.get('hallucination_flags') else ''}
</div>
<div id="scores" class="grid grid-cols-5 gap-3 mb-6">
  <div class="bg-white border rounded-lg p-3"><span class="text-xs text-slate-500">Health</span><div class="text-2xl font-black">{diag.get('overall_health_score','—')}</div></div>
  <div class="bg-white border rounded-lg p-3"><span class="text-xs text-slate-500">SEO</span><div class="text-2xl font-black">{(payload.get('seo_report') or {}).get('overall_seo_score','—')}</div></div>
  <div class="bg-white border rounded-lg p-3"><span class="text-xs text-slate-500">AEO</span><div class="text-2xl font-black">{(payload.get('aeo_report') or {}).get('ai_visibility_score','—')}</div></div>
  <div class="bg-white border rounded-lg p-3"><span class="text-xs text-slate-500">UX</span><div class="text-2xl font-black">{(payload.get('ux_report') or {}).get('conversion_score','—')}</div></div>
  <div class="bg-white border rounded-lg p-3"><span class="text-xs text-slate-500">Psych</span><div class="text-2xl font-black">{(payload.get('psychology_report') or {}).get('overall_psychology_score','—')}</div></div>
</div>
<div id="deployable-fixes" class="bg-white border rounded-xl p-4 mb-6">
  <h2 class="font-bold mb-2">Deployable fixes ({len(fixes)})</h2>
  <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto max-h-96">{json.dumps(fixes[:6], indent=2)[:8000]}</pre>
</div>
<div id="competitor-analysis" class="bg-white border rounded-xl p-4 mb-6">
  <h2 class="font-bold mb-2">Competitor analysis</h2>
  <p class="text-sm text-slate-600">Data source: {comp.get('data_source')} · Competitors: {', '.join(comp.get('competitors_analyzed') or []) or 'none'}</p>
  <pre class="text-xs bg-slate-50 p-3 rounded overflow-auto max-h-64">{json.dumps((comp.get('live_compare') or {}).get('rows', [])[:8], indent=2)[:4000]}</pre>
</div>
<div id="recommendations" class="bg-white border rounded-xl p-4">
  <h2 class="font-bold mb-2">Prioritized recommendations</h2>
  <ul class="text-sm list-disc pl-5">{''.join(f'<li>{r.get("action", r)}</li>' for r in recs[:8])}</ul>
</div>
</body></html>"""


async def capture(run_dir: Path) -> None:
    payload_path = run_dir / "frontend_payload.json"
    if not payload_path.is_file():
        print(f"Skip {run_dir}: no frontend_payload.json")
        return
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    url = payload.get("source_url", run_dir.name)
    viewer = run_dir / "cto_viewer.html"
    viewer.write_text(build_viewer_html(payload, url), encoding="utf-8")
    shots = run_dir / "ui_screenshots"
    shots.mkdir(exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(viewer.as_uri(), wait_until="networkidle")
        await page.screenshot(path=str(shots / "01_full_report.png"), full_page=True)
        for sel, name in [
            ("#reliability-banner", "02_reliability_banner"),
            ("#scores", "03_scores"),
            ("#deployable-fixes", "04_deployable_fixes"),
            ("#competitor-analysis", "05_competitor_analysis"),
            ("#contradictions", "06_contradictions"),
        ]:
            el = await page.query_selector(sel)
            if el:
                await el.screenshot(path=str(shots / f"{name}.png"))
        await browser.close()
    print(f"UI screenshots -> {shots}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: capture_cto_ui_screenshots.py <export_run_dir> [...]")
        sys.exit(1)
    import asyncio

    for arg in sys.argv[1:]:
        asyncio.run(capture(Path(arg)))


if __name__ == "__main__":
    main()
