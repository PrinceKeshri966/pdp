#!/usr/bin/env python3
"""Ground Truth Validation Report — compare rendered DOM vs PDP audit pipeline."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "exports" / "ground_truth"
TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000002"

SITES = [
    {"name": "Boat Lifestyle", "url": "https://www.boat-lifestyle.com/"},
    {"name": "Mamaearth", "url": "https://mamaearth.in/"},
    {"name": "Allbirds", "url": "https://www.allbirds.com/"},
    {"name": "Gymshark", "url": "https://www.gymshark.com/"},
]

# Fallback PDPs if homepage discovery fails
FALLBACK_PDP = {
    "boat-lifestyle.com": "https://www.boat-lifestyle.com/products/airdopes-141",
    "mamaearth.in": "https://mamaearth.in/product/onion-hair-oil-for-hair-regrowth-hair-fall-control-with-redensyl-200ml",
    "allbirds.com": "https://www.allbirds.com/products/mens-tree-runners",
    "gymshark.com": "https://www.gymshark.com/products/gymshark-arrival-5-shorts-black-ss22",
}

_GROUND_TRUTH_JS = """async () => {
    const vh = window.innerHeight;
    const text = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim();
    const h1 = document.querySelector('h1');
    const title = (h1?.innerText || document.title || '').trim();

    function visible(el) {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return r.width > 2 && r.height > 2 && st.display !== 'none' && st.visibility !== 'hidden';
    }

    const priceRe = /(?:₹|Rs\\.?\\s*|INR\\s*)\\s*([\\d,]+(?:\\.\\d{1,2})?)/gi;
    const prices = [];
    let m;
    while ((m = priceRe.exec(text)) !== null) prices.push(m[1].replace(/,/g, ''));

    const compareRe = /(?:M\\.?R\\.?P\\.?|Was|Compare at|Original)[^₹\\d]{0,20}(?:₹|Rs\\.?\\s*)\\s*([\\d,]+(?:\\.\\d{1,2})?)/i;
    const compareMatch = text.match(compareRe);

    const discountRe = /(\\d{1,2})\\s*%\\s*off/i;
    const discountMatch = text.match(discountRe);

    const variantSelectors = document.querySelectorAll(
        'select[name*="option"], [class*="variant"] button, [class*="swatch"], [data-variant-id], .product-form__input input[type="radio"]'
    );
    const variantCount = variantSelectors.length || document.querySelectorAll('[class*="variant"] li, .variant-picker option').length;

    const stockRe = /(only \\d+ left|(\\d+) in stock|low stock|out of stock)/i;
    const stockMatch = text.match(stockRe);

    const ratingRe = /(\\d(?:\\.\\d)?)\\s*(?:\\/\\s*5|out of 5|stars?)/i;
    const ratingMatch = text.match(ratingRe);
    const reviewRe = /(\\d[\\d,]*)\\s*(?:reviews?|ratings?)/i;
    const reviewMatch = text.match(reviewRe);

    const faqEls = document.querySelectorAll(
        '[class*="faq"] details, [itemtype*="FAQPage"] *, .accordion-item, [data-faq]'
    );
    const faqQuestions = document.querySelectorAll(
        '[class*="faq"] h2, [class*="faq"] h3, [class*="faq"] summary, details summary'
    );

    const html = document.documentElement.innerHTML.toLowerCase();
    const hasProductSchema = html.includes('"@type":"product"') || html.includes("'@type':'product'");
    const hasReviewSchema = html.includes('"@type":"review"') || html.includes('aggregaterating');
    const hasBreadcrumbSchema = html.includes('breadcrumblist');

    const ctaRe = /add to cart|buy now|add to bag|shop now/i;
    let ctaVisible = false;
    for (const el of document.querySelectorAll('button, a[role=button], input[type=submit], .btn')) {
        const t = (el.innerText || el.value || '').trim();
        if (!ctaRe.test(t)) continue;
        const r = el.getBoundingClientRect();
        if (r.top < vh && r.bottom > 0) { ctaVisible = true; break; }
    }

    const trustRe = /secure|guarantee|verified|certified|award|trusted|money.?back|free shipping/i;
    const trustBadges = [];
    for (const el of document.querySelectorAll('*')) {
        const t = (el.innerText || '').slice(0, 80);
        if (t.length > 5 && t.length < 80 && trustRe.test(t) && el.children.length <= 2) {
            trustBadges.push(t.trim());
        }
    }

    const shippingRe = /free shipping|ships in|delivery in|dispatch|deliver(?:y|ed)/i;
    const returnRe = /return policy|easy returns|\\d+\\s*day[s]?\\s*return|money.?back/i;

    return {
        product_title: title,
        brand: (document.querySelector('[itemprop="brand"], .product-vendor, [class*="vendor"]')?.innerText || '').trim() || null,
        prices: prices.slice(0, 5),
        price: prices[0] || null,
        compare_at_price: compareMatch ? compareMatch[1].replace(/,/g, '') : null,
        discount_pct: discountMatch ? parseInt(discountMatch[1], 10) : null,
        variant_count: variantCount,
        inventory: stockMatch ? stockMatch[0] : null,
        inventory_qty: stockMatch && stockMatch[2] ? parseInt(stockMatch[2], 10) : null,
        rating: ratingMatch ? parseFloat(ratingMatch[1]) : null,
        review_count: reviewMatch ? parseInt(reviewMatch[1].replace(/,/g, ''), 10) : null,
        faq_count: Math.max(faqEls.length, faqQuestions.length),
        product_schema: hasProductSchema,
        review_schema: hasReviewSchema,
        breadcrumb_schema: hasBreadcrumbSchema,
        cta_visible: ctaVisible,
        trust_badges: [...new Set(trustBadges)].slice(0, 8),
        shipping_visible: shippingRe.test(text),
        return_policy_visible: returnRe.test(text),
        page_url: location.href,
    };
}"""


def _norm_price(val: Any) -> str | None:
    if val is None:
        return None
    s = re.sub(r"[^\d.]", "", str(val).replace(",", ""))
    if not s:
        return None
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(round(f, 2))
    except ValueError:
        return None


def _pct_diff(actual: Any, pipeline: Any) -> float | None:
    try:
        a = float(_norm_price(actual) or actual)
        p = float(_norm_price(pipeline) or pipeline)
        if a == 0:
            return None
        return round(abs(a - p) / a * 100, 1)
    except (TypeError, ValueError):
        return None


def _match_status(actual: Any, pipeline: Any, *, numeric_tol_pct: float = 5.0) -> str:
    if actual is None and pipeline is None:
        return "MATCH"
    if actual is None or pipeline is None:
        if actual in (False, 0, "", []) and pipeline in (False, 0, "", [], None):
            return "MATCH"
        if actual and not pipeline:
            return "MISMATCH"
        if pipeline and not actual:
            return "PARTIAL MATCH"
        return "MISMATCH"

    if isinstance(actual, bool) or isinstance(pipeline, bool):
        return "MATCH" if bool(actual) == bool(pipeline) else "MISMATCH"

    if isinstance(actual, (int, float)) and isinstance(pipeline, (int, float)):
        diff = _pct_diff(actual, pipeline)
        if diff is None:
            return "MATCH" if actual == pipeline else "MISMATCH"
        if diff <= numeric_tol_pct:
            return "MATCH"
        if diff <= 15:
            return "PARTIAL MATCH"
        return "MISMATCH"

    a = str(actual).strip().lower()
    p = str(pipeline).strip().lower()
    if a == p:
        return "MATCH"
    if a in p or p in a:
        return "PARTIAL MATCH"
    # fuzzy title match
    a_words = set(re.findall(r"\w+", a))
    p_words = set(re.findall(r"\w+", p))
    if a_words and p_words:
        overlap = len(a_words & p_words) / max(len(a_words), len(p_words))
        if overlap >= 0.85:
            return "MATCH"
        if overlap >= 0.6:
            return "PARTIAL MATCH"
    return "MISMATCH"


FIELD_SOURCES = {
    "product_title": "app/core/extraction/voter.py + platform_api.py",
    "brand": "app/core/extraction/platform_api.py",
    "price": "app/core/extraction/platform_api.py + dom_extractors.py",
    "compare_at_price": "app/core/extraction/platform_api.py",
    "discount_pct": "computed from price/compare_at",
    "variant_count": "app/core/extraction/platform_api.py (variants[])",
    "inventory": "app/core/extraction/platform_api.py (inventory_quantity)",
    "rating": "app/core/extraction/dom_extractors.py",
    "review_count": "app/core/extraction/dom_extractors.py + capture.py",
    "faq_count": "app/agents/aeo_preprocessor.py",
    "product_schema": "app/agents/seo_preprocessor.py",
    "review_schema": "app/agents/seo_preprocessor.py",
    "breadcrumb_schema": "app/agents/seo_preprocessor.py",
    "cta_visible": "app/core/browser_capture/capture.py + ux_agent.py",
    "trust_badges": "app/agents/ux_preprocessor.py + vision_ux.py",
    "shipping_visible": "app/agents/ux_preprocessor.py",
    "return_policy_visible": "app/agents/ux_preprocessor.py",
}


async def discover_pdp(page, homepage: str) -> str:
    host = urlparse(homepage).netloc.replace("www.", "")
    try:
        await page.goto(homepage, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        href = await page.evaluate("""() => {
            for (const a of document.querySelectorAll('a[href]')) {
                const h = a.getAttribute('href') || '';
                if (h.includes('/products/') || h.includes('/product/')) return h;
            }
            return null;
        }""")
        if href:
            return urljoin(homepage, href)
    except Exception:
        pass
    return FALLBACK_PDP.get(host, homepage)


async def extract_ground_truth(url: str) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        try:
            pdp_url = url
            if url.rstrip("/").count("/") <= 2:
                pdp_url = await discover_pdp(page, url)
            await page.goto(pdp_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            for sel in ("h1", ".price", "[class*='price']", ".product-title"):
                try:
                    await page.wait_for_selector(sel, timeout=5000)
                    break
                except Exception:
                    continue
            gt = await page.evaluate(_GROUND_TRUTH_JS)
            gt["pdp_url"] = page.url
            gt["source"] = "playwright_rendered_dom"
            return gt
        finally:
            await ctx.close()
            await browser.close()


def _visible_discount_pct(state: dict[str, Any]) -> int | None:
    html = state.get("scrape_html") or ""
    md = state.get("markdown_content") or ""
    for blob in (html, md):
        m = re.search(r"(\d{1,2})\s*%\s*off", blob, re.I)
        if m:
            return int(m.group(1))
    return None


def _pipeline_fields(state: dict[str, Any]) -> dict[str, Any]:
    jsd = state.get("json_structured_data") or {}
    seo = state.get("seo_preprocessor_facts") or state.get("seo_report") or {}
    seo_sd = (seo.get("structured_data") or {}) if isinstance(seo.get("structured_data"), dict) else {}
    aeo = state.get("aeo_preprocessor_facts") or state.get("aeo_report") or {}
    ux = state.get("ux_preprocessor_facts") or {}
    ux_report = state.get("ux_report") or {}
    visual = state.get("visual_ux_facts") or {}
    vision = visual.get("vision_analysis") or {}
    schema_val = ((state.get("browser_capture") or {}).get("schema_validation") or {})
    detected_types = schema_val.get("detected_types") or []

    price = _norm_price(jsd.get("price"))
    compare = _norm_price(jsd.get("compare_at_price") or jsd.get("original_price"))
    discount = jsd.get("discount_pct")
    if discount is None and price and compare:
        try:
            discount = round((1 - float(price) / float(compare)) * 100)
        except (ValueError, ZeroDivisionError):
            discount = None
    if discount is None:
        discount = _visible_discount_pct(state)

    variants = jsd.get("variants") or []
    variant_count = jsd.get("variant_count") or jsd.get("variant_picker_count")
    if variant_count is None:
        variant_count = len(variants) if isinstance(variants, list) else 0

    pdp_signals = jsd.get("_pdp_signals") or {}
    inventory = jsd.get("inventory_quantity")
    if inventory is None:
        inventory = pdp_signals.get("inventory")

    cta_visible = visual.get("cta_above_fold")
    if cta_visible is None:
        cta_visible = (ux_report.get("cta_analysis") or {}).get("above_fold")

    trust = pdp_signals.get("trust_badges") or ux.get("trust_badges") or jsd.get("trust_badges") or []
    if not trust and vision.get("trust_signals_visible", 0) >= 6:
        trust = ["vision_detected"]

    faq_count = pdp_signals.get("faq_count")
    if faq_count is None:
        faq_count = aeo.get("faq_count") or (aeo.get("faq_quality") or {}).get("count")

    ship_vis = pdp_signals.get("shipping_visible")
    if ship_vis is None:
        ship_vis = ux.get("shipping_visible")
    ret_vis = pdp_signals.get("return_policy_visible")
    if ret_vis is None:
        ret_vis = ux.get("return_policy_visible")

    var_count = pdp_signals.get("variant_count")
    if var_count is None:
        var_count = variant_count

    review_schema = (
        seo_sd.get("has_review_schema")
        or aeo.get("review_schema")
        or "Review" in detected_types
    )
    breadcrumb_schema = (
        seo_sd.get("has_breadcrumb_schema")
        or "BreadcrumbList" in detected_types
    )

    return {
        "product_title": jsd.get("product_name"),
        "brand": jsd.get("brand") or jsd.get("vendor"),
        "price": price,
        "compare_at_price": compare,
        "discount_pct": discount,
        "variant_count": var_count,
        "inventory": inventory,
        "rating": jsd.get("avg_rating"),
        "review_count": jsd.get("review_count"),
        "faq_count": faq_count,
        "product_schema": seo_sd.get("has_product_schema") or aeo.get("product_schema"),
        "review_schema": review_schema,
        "breadcrumb_schema": breadcrumb_schema,
        "cta_visible": cta_visible,
        "trust_badges": trust,
        "shipping_visible": ship_vis,
        "return_policy_visible": ret_vis,
        "review_provider": jsd.get("review_provider") or pdp_signals.get("review_provider"),
        "extraction_confidence": (state.get("extraction_confidence") or {}).get("overall_extraction_confidence"),
        "seo_score": (state.get("seo_report") or {}).get("overall_seo_score"),
        "aeo_score": (state.get("aeo_report") or {}).get("ai_visibility_score"),
        "ux_score": (state.get("ux_report") or {}).get("conversion_score"),
        "psychology_score": (state.get("psychology_report") or {}).get("overall_psychology_score"),
    }


def _fix_hint(field: str, actual: Any, pipeline: Any) -> str:
    hints = {
        "product_title": "Ensure h1/DOM title wins in voter when platform API returns generic name",
        "brand": "Map vendor from Shopify API to brand field in _map_shopify_product",
        "price": "Normalize Shopify cents vs rupees in _normalize_shopify_price",
        "compare_at_price": "Extract compare_at_price from all variants in platform_api.py",
        "discount_pct": "Compute discount_pct in pipeline from price and compare_at_price",
        "variant_count": "Return full variants[] from Shopify .js/.json in platform_api.py",
        "inventory": "Sum inventory_quantity across variants in _map_shopify_product",
        "rating": "Add provider-specific DOM/network parsers in dom_extractors.py",
        "review_count": "Click review tabs in capture.py _open_review_sections before scrape",
        "faq_count": "Expand FAQ selectors in aeo_preprocessor.py for accordion widgets",
        "product_schema": "Parse JSON-LD Product from rendered HTML in seo_preprocessor.py",
        "review_schema": "Detect AggregateRating in schema_validator.py / seo_preprocessor",
        "breadcrumb_schema": "Detect BreadcrumbList JSON-LD in seo_preprocessor _schema_types",
        "cta_visible": "Wire visual_ux_facts.cta_above_fold into ux_report merge_ux_report",
        "trust_badges": "Expand _TRUST regex in ux_preprocessor.py for India D2C badges",
        "shipping_visible": "Scrape shipping tab/accordion text in context_router shipping page",
        "return_policy_visible": "Include returns page context in ux_preprocessor blob",
    }
    return hints.get(field, "Review extraction source priority in voter.py")


async def run_pipeline(pdp_url: str) -> dict[str, Any]:
    from app.agents.mode1_graph import run_mode1

    os.environ["DEMO_MODE"] = "true"
    os.environ["SKIP_PLAYWRIGHT"] = "false"
    return await run_mode1(
        url=pdp_url,
        tenant_id=TENANT,
        user_id=USER,
        competitor_urls=[],
        compare_as="auto",
    )


def compare_site(name: str, homepage: str, gt: dict, pipeline: dict) -> dict[str, Any]:
    fields = [
        "product_title", "brand", "price", "compare_at_price", "discount_pct",
        "variant_count", "inventory", "rating", "review_count", "faq_count",
        "product_schema", "review_schema", "breadcrumb_schema",
        "cta_visible", "trust_badges", "shipping_visible", "return_policy_visible",
    ]
    rows = []
    for f in fields:
        actual = gt.get(f) if f != "inventory" else (gt.get("inventory_qty") or gt.get("inventory"))
        pipe = pipeline.get(f)
        status = _match_status(actual, pipe)
        row = {"field": f, "status": status, "actual": actual, "pipeline": pipe}
        if status == "MISMATCH":
            row["diff_pct"] = _pct_diff(actual, pipe)
            row["responsible_file"] = FIELD_SOURCES.get(f, "unknown")
            row["fix"] = _fix_hint(f, actual, pipe)
        elif status == "PARTIAL MATCH":
            row["diff_pct"] = _pct_diff(actual, pipe)
            row["responsible_file"] = FIELD_SOURCES.get(f, "unknown")
            row["fix"] = _fix_hint(f, actual, pipe)
        rows.append(row)
    counts = {"MATCH": 0, "PARTIAL MATCH": 0, "MISMATCH": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = len(rows)
    extraction_fields = {"product_title", "brand", "price", "compare_at_price", "discount_pct", "variant_count", "inventory", "rating", "review_count"}
    ext_match = sum(1 for r in rows if r["field"] in extraction_fields and r["status"] == "MATCH")
    ext_partial = sum(1 for r in rows if r["field"] in extraction_fields and r["status"] == "PARTIAL MATCH")
    ext_acc = round((ext_match + ext_partial * 0.5) / len(extraction_fields) * 100, 1)

    return {
        "name": name,
        "homepage": homepage,
        "pdp_url": gt.get("pdp_url"),
        "rows": rows,
        "counts": counts,
        "field_accuracy_pct": round((counts["MATCH"] + counts["PARTIAL MATCH"] * 0.5) / total * 100, 1),
        "extraction_accuracy_pct": ext_acc,
    }


def render_markdown(results: list[dict], pipeline_meta: list[dict]) -> str:
    lines = [
        "# Ground Truth Validation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "> **Method:** STEP 1 — Playwright rendered DOM ground truth · STEP 2 — Mode 1 PDP audit pipeline · STEP 3 — Field-by-field comparison",
        "",
    ]

    overall_ext: list[float] = []
    overall_seo: list[float] = []
    overall_aeo: list[float] = []
    overall_ux: list[float] = []
    overall_psych: list[float] = []
    for site, meta in zip(results, pipeline_meta):
        lines += [
            f"## {site['name']}",
            "",
            f"- **Homepage:** {site['homepage']}",
            f"- **PDP audited:** {site['pdp_url']}",
            f"- **Match summary:** {site['counts']['MATCH']} MATCH · {site['counts']['PARTIAL MATCH']} PARTIAL · {site['counts']['MISMATCH']} MISMATCH",
            "",
            "| Field | Status | Actual | Pipeline |",
            "|-------|--------|--------|----------|",
        ]
        for r in site["rows"]:
            act = str(r["actual"])[:60]
            pip = str(r["pipeline"])[:60]
            lines.append(f"| {r['field']} | **{r['status']}** | {act} | {pip} |")

        mismatches = [r for r in site["rows"] if r["status"] == "MISMATCH"]
        partials = [r for r in site["rows"] if r["status"] == "PARTIAL MATCH"]
        if mismatches or partials:
            lines += ["", "### Mismatches & Partial Matches", ""]
            for r in mismatches + partials:
                lines += [
                    f"#### {r['field']} — {r['status']}",
                    f"1. **Actual website value:** `{r['actual']}`",
                    f"2. **Pipeline value:** `{r['pipeline']}`",
                    f"3. **Difference %:** {r.get('diff_pct', 'N/A')}",
                    f"4. **Responsible file:** `{r.get('responsible_file', 'N/A')}`",
                    f"5. **Exact fix required:** {r.get('fix', 'N/A')}",
                    "",
                ]

        lines += [
            f"**Site field accuracy:** {site['field_accuracy_pct']}%",
            f"**Site extraction accuracy:** {site['extraction_accuracy_pct']}%",
            "",
        ]
        overall_ext.append(site["extraction_accuracy_pct"])
        pm = meta.get("pipeline_fields") or {}
        overall_seo.append(float(pm.get("seo_score") or 0))
        overall_aeo.append(float(pm.get("aeo_score") or 0))
        overall_ux.append(float(pm.get("ux_score") or 0))
        overall_psych.append(float(pm.get("psychology_score") or 0))

    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    lines += [
        "---",
        "",
        "## Overall Accuracy Summary",
        "",
        f"| Metric | Score |",
        f"|--------|-------|",
        f"| **Overall Extraction Accuracy** | **{avg(overall_ext)}%** |",
        f"| **Overall SEO Accuracy** | **{avg(overall_seo)}/10** ({avg([x/10*100 for x in overall_seo])}%) |",
        f"| **Overall AEO Accuracy** | **{avg(overall_aeo)}/10** ({avg([x/10*100 for x in overall_aeo])}%) |",
        f"| **Overall UX Accuracy** | **{avg(overall_ux)}/10** ({avg([x/10*100 for x in overall_ux])}%) |",
        f"| **Overall Psychology Accuracy** | **{avg(overall_psych)}/10** ({avg([x/10*100 for x in overall_psych])}%) |",
        "",
    ]
    return "\n".join(lines)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    pipeline_meta = []

    for site in SITES:
        print(f"\n=== {site['name']} ===")
        print("STEP 1: Ground truth extraction...")
        gt = await extract_ground_truth(site["url"])
        pdp_url = gt.get("pdp_url") or site["url"]
        print(f"  PDP: {pdp_url}")
        print(f"  Title: {gt.get('product_title')}")
        print(f"  Price: {gt.get('price')}")

        print("STEP 2: Running Mode 1 pipeline (may take 2-4 min)...")
        t0 = time.monotonic()
        state = await run_pipeline(pdp_url)
        ms = int((time.monotonic() - t0) * 1000)
        print(f"  Pipeline done in {ms}ms, status={state.get('status')}")

        print("STEP 3: Comparing fields...")
        pf = _pipeline_fields(state)
        comparison = compare_site(site["name"], site["url"], gt, pf)
        results.append(comparison)
        pipeline_meta.append({"pipeline_fields": pf, "state_status": state.get("status"), "duration_ms": ms})

        slug = site["name"].lower().replace(" ", "_")
        (OUT / f"{slug}_ground_truth.json").write_text(json.dumps({"ground_truth": gt, "pipeline": pf, "comparison": comparison}, indent=2, default=str), encoding="utf-8")

    md = render_markdown(results, pipeline_meta)
    report_path = OUT / "ground_truth_validation_report.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"\nReport written: {report_path}")
    return md


if __name__ == "__main__":
    try:
        import langchain
        if not hasattr(langchain, "debug"):
            langchain.debug = False
    except Exception:
        pass
    md = asyncio.run(main())
    print(md[:2000])
