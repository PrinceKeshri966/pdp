"""
Platform-agnostic DOM extractors aligned with Playwright ground-truth validation.

Shopify, headless (Gymshark), React (Allbirds), WooCommerce — no store-specific branching.
"""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

_NON_FAQ_SECTION = re.compile(
    r'class=["\'][^"\']*(?:shipping|delivery|return|policy|description|specification|'
    r'review|rating|ingredient|how-to|benefit|feature|size-guide|tab-nav|product-meta|'
    r'woocommerce-Tabs-panel--description)[^"\']*["\']',
    re.I,
)

_FAQ_SECTION = re.compile(
    r'(?:class=["\'][^"\']*faq[^"\']*["\']|id=["\'][^"\']*faq[^"\']*["\']|'
    r'itemtype=["\'][^"\']*FAQPage|data-faq|aria-label=["\'][^"\']*faq|'
    r'woocommerce-Tabs-panel--faq|class=["\'][^"\']*accordion-faq)',
    re.I,
)

_TRUST_ONTOLOGY = re.compile(
    r"made safe|certified organic|cruelty.?free|dermatologically tested|derma tested|"
    r"verified reviews?|fda(?:\s+approved)?|(?<![a-z])ce(?![a-z])\s*(?:mark|certified)?|"
    r"iso\s*\d{3,5}|trustpilot|yotpo|judge\.?me|loox|okendo|stamped|bazaarvoice|reviews\.io|"
    r"leaping bunny|peta|money.?back|100% authentic|gmp|fssai|bis certified|"
    r"norton|mcafee|pci|ssl secured|award.?winning|asia'?s 1st|made in india|"
    r"hypoallergenic|clinically proven|ecocert|cosmos organic",
    re.I,
)
_TRUST_JUNK = re.compile(
    r"^\d+\s*reviews?$|^\d+\s*ratings?$|^\d+\.\d\s*/\s*5$|"
    r"display\s*:\s*none|jdgm-|yotpo-|\.css|data-average-rating|data-number-of-reviews|"
    r"^\W+$|add to cart|buy now|verified purchase$|^\d+\s*stars?$",
    re.I,
)

_SHIPPING_GT = re.compile(
    r"free shipping|free delivery|ships?\s+worldwide|worldwide shipping|"
    r"ships?\s+in|delivery\s+in|dispatch|deliver(?:y|ed)|get it by|arrives by|"
    r"estimated delivery|standard delivery|express delivery|same.?day delivery|"
    r"(?:\$|£|€|₹|cad|aud)\s*\d[\d,]*.*(?:free shipping|free delivery)|"
    r"free (?:shipping|delivery) (?:on orders )?over|spend (?:\$|£|€|₹)\s*\d+.*free|"
    r"orders over (?:\$|£|€|₹|rs\.?\s*)[\d,]+",
    re.I,
)
_RETURN_GT = re.compile(
    r"return policy|easy returns?|hassle.?free return|free returns?|"
    r"(?:7|14|15|30|45|60|90)\s*[- ]?day[s]?\s*(?:return|money.?back|guarantee)|"
    r"\d+\s*day[s]?\s*(?:return|replacement|exchange)|money.?back guarantee|"
    r"no.?questions.?asked return",
    re.I,
)

_REVIEW_PROVIDERS: list[tuple[str, re.Pattern[str]]] = [
    ("yotpo", re.compile(r"yotpo|yotpo-main-widget|staticw2\.yotpo", re.I)),
    ("judge.me", re.compile(r"judge\.me|jdgm-|judgeme", re.I)),
    ("loox", re.compile(r"loox|loox\.io", re.I)),
    ("okendo", re.compile(r"okendo|oke-reviews", re.I)),
    ("stamped", re.compile(r"stamped\.io|stamped-", re.I)),
    ("bazaarvoice", re.compile(r"bazaarvoice|bv-rating", re.I)),
    ("reviews.io", re.compile(r"reviews\.io", re.I)),
    ("trustpilot", re.compile(r"trustpilot", re.I)),
    ("powerreviews", re.compile(r"powerreviews", re.I)),
]

_VISIBLE_REVIEW_COUNT = re.compile(
    r"(\d[\d,]*)\s*(?:reviews?|ratings?)\b",
    re.I,
)

_VARIANT_PICKER_OPTS = re.compile(
    r'class=["\'][^"\']*(?:variant|variant-picker)[^"\']*["\'][^>]*>[\s\S]*?<option\b',
    re.I,
)


def _pre_footer(html: str) -> str:
    if not html:
        return ""
    m = re.search(r"<footer\b", html, re.I)
    return html[: m.start()] if m else html


def _strip_scripts_styles(html: str) -> str:
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    return re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)


def _visible_text(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html)
    return unescape(re.sub(r"\s+", " ", t)).strip()


def _product_zone_html(html: str) -> str:
    """Isolate product form / detail region — reduces footer policy leakage."""
    if not html:
        return ""
    cleaned = _strip_scripts_styles(_pre_footer(html))
    for pattern in (
        r'(<form[^>]*class=["\'][^"\']*product-form[^"\']*["\'][^>]*>[\s\S]{200,20000})',
        r'(<div[^>]*(?:class|id)=["\'][^"\']*product(?:-detail|-info|-main|__info|__main)[^"\']*["\'][^>]*>[\s\S]{500,25000})',
        r'(<main[^>]*class=["\'][^"\']*product[^"\']*["\'][^>]*>[\s\S]{500,20000})',
        r'(<div[^>]*class=["\'][^"\']*woocommerce-product-details[^"\']*["\'][^>]*>[\s\S]{500,20000})',
    ):
        m = re.search(pattern, cleaned, re.I)
        if m:
            return m.group(1)
    return cleaned


def _faq_schema_count(html: str) -> int:
    count = 0
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html or "",
        re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("@type") or ""
            if isinstance(t, list):
                t = " ".join(str(x) for x in t)
            if "FAQPage" not in str(t):
                continue
            entities = item.get("mainEntity") or item.get("hasPart") or []
            if isinstance(entities, dict):
                entities = [entities]
            count = max(count, len(entities))
    return count


def _faq_has_dom_markers(html: str) -> bool:
    pre = _strip_scripts_styles(_pre_footer(html or ""))
    return bool(_FAQ_SECTION.search(pre) or _FAQ_ITEMTYPE.search(pre) or _FAQ_DATA.search(pre))


_FAQ_ITEMTYPE = re.compile(r'itemtype=["\'][^"\']*FAQPage', re.I)
_FAQ_DATA = re.compile(r"\bdata-faq\b", re.I)


def count_faq_dom_gt(html: str) -> int:
    """DOM FAQ: accordions, details/summary, WooCommerce FAQ tab, Q/A pairs."""
    if not html:
        return 0
    pre = _strip_scripts_styles(_pre_footer(html))

    faq_els = 0
    for m in re.finditer(r"<details\b", pre, re.I):
        ctx = pre[max(0, m.start() - 2000) : m.start()]
        if _NON_FAQ_SECTION.search(ctx) and "faq" not in ctx.lower():
            continue
        if re.search(r'class=["\'][^"\']*faq[^"\']*["\']', ctx, re.I):
            faq_els += 1
    faq_els += len(_FAQ_ITEMTYPE.findall(pre))
    faq_els += len(_FAQ_DATA.findall(pre))
    for block in re.findall(
        r'class=["\'][^"\']*faq[^"\']*["\'][^>]*>([\s\S]{0,20000})',
        pre,
        re.I,
    ):
        faq_els += len(re.findall(r'class=["\'][^"\']*accordion-item[^"\']*["\']', block, re.I))

    summary_positions: set[int] = set()
    for m in re.finditer(r"<summary\b", pre, re.I):
        ctx = pre[max(0, m.start() - 2000) : m.start()]
        if _NON_FAQ_SECTION.search(ctx) and "faq" not in ctx.lower():
            continue
        in_faq = bool(re.search(r'class=["\'][^"\']*faq[^"\']*["\']', ctx, re.I))
        in_details = bool(re.search(r"<details\b", ctx, re.I))
        if in_faq or in_details:
            summary_positions.add(m.start())
    faq_questions = len(summary_positions)

    qa_pairs = 0
    for pat in (
        r'class=["\'][^"\']*faq[^"\']*["\'][^>]*>[\s\S]{0,8000}?<dt\b',
        r"<dt\b[^>]*>[^<]{5,200}\?",
        r'class=["\'][^"\']*faq-item[^"\']*["\']',
        r'class=["\'][^"\']*woocommerce-Tabs-panel--faq[^"\']*["\']',
    ):
        qa_pairs = max(qa_pairs, len(re.findall(pat, pre, re.I)))

    return max(faq_els, faq_questions, qa_pairs)


def count_faq_unified(html: str, *, schema_count: int | None = None) -> int:
    """
    FAQ count: requires visible FAQ UI; schema augments when DOM markers exist.
    Schema-only (no DOM FAQ section) returns 0.
    """
    if not html:
        return 0
    dom = count_faq_dom_gt(html)
    if dom <= 0 and not _faq_has_dom_markers(html):
        return 0
    schema = schema_count if schema_count is not None else _faq_schema_count(html)
    return max(dom, schema) if dom > 0 else (schema if _faq_has_dom_markers(html) else 0)


def extract_trust_badges_gt(html: str) -> list[str]:
    """Certification phrases + review provider labels; excludes review counts."""
    if not html:
        return []
    pre = _strip_scripts_styles(_pre_footer(html))
    zone = _product_zone_html(html) or pre
    hits: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        phrase = re.sub(r"\s+", " ", unescape(phrase.strip()))
        if len(phrase) < 5 or _TRUST_JUNK.search(phrase):
            return
        if any(c in phrase for c in ('{"', '":"', "\\u", "&amp;", "srsltid")):
            return
        key = phrase.lower()[:80]
        if key in seen:
            return
        seen.add(key)
        hits.append(phrase[:120])

    for blob in (zone, pre):
        for m in re.finditer(r">([^<]{5,120})<", blob):
            t = m.group(1).strip()
            if _TRUST_ONTOLOGY.search(t):
                _add(t)
        for m in re.finditer(r'<img[^>]+alt=["\']([^"\']{3,80})["\']', blob, re.I):
            if _TRUST_ONTOLOGY.search(m.group(1)):
                _add(m.group(1))

    for m in re.finditer(r"(Verified Reviews?:?\s*)", pre, re.I):
        _add(m.group(1).strip())

    for label, pat in _REVIEW_PROVIDERS:
        if pat.search(pre) and label not in seen:
            seen.add(label)
            hits.append(label.replace(".", " ").title())

    hits.sort(key=len, reverse=True)
    deduped: list[str] = []
    for h in hits:
        if any(h != other and h in other for other in deduped):
            continue
        deduped.append(h)
    return deduped[:8]


def extract_policy_visibility_gt(html: str) -> tuple[bool, bool]:
    """Shipping/returns from product zone first, then pre-footer body."""
    if not html:
        return False, False
    zone_text = _visible_text(_product_zone_html(html))
    body_text = _visible_text(_strip_scripts_styles(_pre_footer(html)))
    shipping = bool(_SHIPPING_GT.search(zone_text)) or (
        bool(_SHIPPING_GT.search(body_text)) and bool(re.search(r"product-form|product-info|product-detail|add to", html or "", re.I))
    )
    returns = bool(_RETURN_GT.search(zone_text)) or (
        bool(_RETURN_GT.search(body_text)) and bool(re.search(r"product-form|product-info|product-detail|add to", html or "", re.I))
    )
    return shipping, returns


def _count_shopify_variants_json(html: str) -> int:
    m = re.search(r'"variants"\s*:\s*\[([\s\S]{10,80000}?)\]', html or "")
    if not m:
        return 0
    return len(re.findall(r'"id"\s*:', m.group(1)))


def count_variants_dom_gt(html: str) -> int:
    """Unique variant picker nodes (select, swatch, data-variant-id, radio, woo)."""
    if not html:
        return 0
    pre = _pre_footer(html)
    tag_starts: set[int] = set()
    for pat in (
        r'<select[^>]*name=["\'][^"\']*option',
        r'class=["\'][^"\']*swatch[^"\']*["\']',
        r'\bdata-variant-id=["\']',
        r'class=["\'][^"\']*variant[^"\']*["\'][^>]*>\s*<button',
        r'product-form__input[^>]*type=["\']radio["\']',
        r'class=["\'][^"\']*variations[^"\']*["\'][^>]*>\s*<select',
        r'name=["\']attribute_pa_',
    ):
        for m in re.finditer(pat, pre, re.I):
            pos = pre.rfind("<", 0, m.start() + 1)
            if pos >= 0:
                tag_starts.add(pos)
    if tag_starts:
        return len(tag_starts)
    return len(_VARIANT_PICKER_OPTS.findall(pre))


def resolve_variant_count(
    html: str,
    *,
    platform_variants: list[dict[str, Any]] | None = None,
) -> int:
    """Best variant count: max(API, Shopify JSON, DOM pickers) when plausible."""
    dom = count_variants_dom_gt(html)
    api_n = len(platform_variants) if platform_variants else 0
    json_n = _count_shopify_variants_json(html)
    candidates = [c for c in (dom, api_n, json_n) if c > 0]
    if not candidates:
        return 0
    best = max(candidates)
    if api_n and dom and api_n >= dom * 0.85:
        return max(api_n, dom)
    return best


def detect_review_provider(html: str) -> str | None:
    blob = html or ""
    for name, pat in _REVIEW_PROVIDERS:
        if pat.search(blob):
            return name
    return None


def extract_visible_review_count(html: str, visible_text: str | None = None) -> int | None:
    blob = f"{html}\n{visible_text or ''}"
    if not detect_review_provider(html) and not _VISIBLE_REVIEW_COUNT.search(blob):
        return None
    counts: list[int] = []
    for m in _VISIBLE_REVIEW_COUNT.finditer(blob):
        try:
            n = int(m.group(1).replace(",", ""))
            if 0 < n < 500_000:
                counts.append(n)
        except ValueError:
            continue
    return min(counts) if counts else None


def reconcile_review_count(*counts: int | None) -> int | None:
    valid = [c for c in counts if c is not None and c > 0]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    lo, hi = min(valid), max(valid)
    if hi > lo * 1.15:
        return lo
    return max(valid, key=lambda c: (valid.count(c), c))
