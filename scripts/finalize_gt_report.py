import asyncio, json, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import langchain
    if not hasattr(langchain, "debug"):
        langchain.debug = False
except Exception:
    pass

from scripts.ground_truth_validation import compare_site, render_markdown, run_pipeline, _pipeline_fields, _GROUND_TRUTH_JS
from scripts.regenerate_ground_truth_report import merge_boat_gt, MAMAEARTH_PDP

OUT = ROOT / "exports" / "ground_truth"


async def mama_gt():
    from playwright.async_api import async_playwright
    from app.core.html_metadata import BROWSER_UA
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(viewport={"width": 1366, "height": 900}, user_agent=BROWSER_UA)
        page = await ctx.new_page()
        await page.goto(MAMAEARTH_PDP, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(4000)
        gt = await page.evaluate(_GROUND_TRUTH_JS)
        gt["pdp_url"] = page.url
        await ctx.close()
        await b.close()
    return gt


async def main():
    boat_pipeline = json.loads((OUT / "boat_lifestyle_ground_truth.json").read_text(encoding="utf-8"))["pipeline"]
    print("Extracting Mamaearth ground truth...")
    mama_gt_data = await mama_gt()
    print("Running Mamaearth pipeline...")
    state = await run_pipeline(MAMAEARTH_PDP)
    mama_pipeline = _pipeline_fields(state)

    (OUT / "mamaearth_ground_truth.json").write_text(
        json.dumps({"ground_truth": mama_gt_data, "pipeline": mama_pipeline}, indent=2, default=str),
        encoding="utf-8",
    )

    boat_gt = merge_boat_gt()
    results = [
        compare_site("Boat Lifestyle", "https://www.boat-lifestyle.com/", boat_gt, boat_pipeline),
        compare_site("Mamaearth", "https://mamaearth.in/", mama_gt_data, mama_pipeline),
    ]
    md = render_markdown(results, [{"pipeline_fields": boat_pipeline}, {"pipeline_fields": mama_pipeline}])
    note = (
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "> **Scope:** Boat PDP discovered from homepage → `airdopes-181-pro-bluetooth-earbuds`. "
        "Mamaearth live PDP → `onion-hair-oil-...-redensyl-200ml` (old slug returns 404).\n\n"
    )
    md = note + md.split("\n", 1)[1]
    (OUT / "ground_truth_validation_report.md").write_text(md, encoding="utf-8")
    print("Report saved.")
    print(md)


if __name__ == "__main__":
    asyncio.run(main())
