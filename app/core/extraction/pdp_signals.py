"""
Enterprise PDP signal extraction — FAQ, trust, shipping, returns, variants, inventory.

Each extractor returns {value, source, confidence} via FieldResult.
Priority: Schema > Platform API > DOM > Regex fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any

from app.core.extraction.platform_parity import (
    count_faq_unified,
    detect_review_provider,
    extract_policy_visibility_gt,
    extract_trust_badges_gt,
    resolve_variant_count,
)
from app.core.extraction.schema_graph import parse_schema_graph
from app.core.extraction.shopify_theme import extract_visible_sale_price


@dataclass
class FieldResult:
    value: Any
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source, "confidence": round(self.confidence, 2)}


# ── Certification / trust ontology (India + global D2C) ──────────────────────
_TRUST_ONTOLOGY = frozenset({
    "made safe", "dermatologically tested", "cruelty free", "cruelty-free",
    "vegan", "organic certified", "usda organic", "fssai", "bis certified",
    "iso 9001", "iso 14001", "iso 27001", "gmp certified", "fda approved",
    "derma tested", "hypoallergenic", "paraben free", "sulfate free",
    "clinically proven", "dermatologist recommended", "pediatrician tested",
    "norton secured", "mcafee secure", "ssl secured", "pci dss", "pci compliant",
    "trustpilot", "verified reviews", "buy with confidence", "money back guarantee",
    "100% authentic", "genuine product", "award winning", "award-winning",
    "asia's 1st", "asia's first", "certified organic", "ecocert", "cosmos organic",
    "leaping bunny", "peta certified", "good housekeeping", "made in india",
})

_TRUST_EXCLUDE = re.compile(
    r"^\d+\s*reviews?$|^\d+\s*ratings?$|free shipping|add to cart|buy now|"
    r"^\d+\.\d\s*/\s*5$|^★+$|^⭐+$|verified purchase$|"
    r"^(?:ingredients|benefits|how to|description|specifications?)\b",
    re.I,
)

# Generic accordion markers that are NOT FAQ
_NON_FAQ_ACCORDION = re.compile(
    r'''class=["'][^"']*(?:shipping|delivery|return|policy|description|specification|'''
    r'''review|rating|ingredient|how.?to.?use|benefit|feature|size.?guide|tab-)[^"']*["']''',
    re.I,
)

_FAQ_SECTION = re.compile(
    r'(?:class=["\'][^"\']*faq[^"\']*["\']|id=["\'][^"\']*faq[^"\']*["\']|'
    r'itemtype=["\'][^"\']*FAQPage|data-faq|aria-label=["\'][^"\']*faq)',
    re.I,
)

_FAQ_HEADING = re.compile(
    r"<(?:h[2-4]|dt|summary|button)[^>]*>([^<]{5,200}\?)[^<]*<",
    re.I,
)

_SHIPPING_PATTERNS = re.compile(
    r"(?:free shipping|ships?\s+in\s+\d|delivery\s+in\s+\d|dispatch(?:es)?\s+in|"
    r"deliver(?:y|ed)\s+by|express delivery|standard delivery|"
    r"estimated delivery|delivery date|ships from|same.?day delivery|"
    r"get it by|arrives by)",
    re.I,
)

_RETURN_PATTERNS = re.compile(
    r"(?:return policy|easy returns?|hassle.?free return|exchange policy|"
    r"\d+\s*day[s]?\s*(?:return|replacement|exchange)|money.?back guarantee|"
    r"no.?questions.?asked return|free returns?)",
    re.I,
)

_FOOTER_NAV = re.compile(
    r"<(?:footer|nav)[^>]*>[\s\S]*?</(?:footer|nav)>|"
    r'''class=["'][^"']*(?:footer|site-footer|page-footer|nav-menu|'''
    r'''site-nav|main-menu|breadcrumb)[^"']*["'][^>]*>[\s\S]{0,12000}?(?=</div>|$)''',
    re.I,
)

_POLICY_LINK = re.compile(
    r'href=["\'][^"\']*(?:/policies/|/pages/(?:shipping|return|refund|delivery))[^"\']*["\']',
    re.I,
)


def _is_shopify(html: str) -> bool:
    h = (html or "").lower()
    return "cdn.shopify.com" in h or "shopify-section" in h or "shopify.theme" in h


def _strip_chrome(html: str) -> str:
    """Remove footer, nav, scripts, styles — keep main PDP content."""
    if not html:
        return ""
    t = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", t, flags=re.I)
    t = _FOOTER_NAV.sub(" ", t)
    return t


def _pdp_visible_html(html: str) -> str:
    """HTML visible on PDP — strips footer/nav and content after first footer tag."""
    if not html:
        return ""
    footer_m = re.search(r"<footer\b", html, re.I)
    if footer_m:
        html = html[: footer_m.start()]
    return _strip_chrome(html)


def _main_pdp_region(html: str) -> str:
    """Isolate product detail region when possible."""
    if not html:
        return ""
    cleaned = _pdp_visible_html(html)
    for pattern in (
        r'(<(?:main|article)[^>]*class=["\'][^"\']*product[^"\']*["\'][^>]*>[\s\S]{500,20000})',
        r'(<div[^>]*(?:class|id)=["\'][^"\']*product(?:-detail|-info|-main|__info|__main)[^"\']*["\'][^>]*>[\s\S]{500,25000})',
        r'(<form[^>]*class=["\'][^"\']*product-form[^"\']*["\'][^>]*>[\s\S]{200,15000})',
    ):
        m = re.search(pattern, cleaned, re.I)
        if m:
            return m.group(1)
    return cleaned


def _visible_text(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html)
    return unescape(re.sub(r"\s+", " ", t)).strip()


def _is_faq_block(block: str) -> bool:
    if _FAQ_SECTION.search(block):
        return True
    if _NON_FAQ_ACCORDION.search(block):
        return False
    return bool(re.search(r"\bfaq\b|frequently asked", block, re.I))


def extract_faq(
    html: str,
    *,
    schema_graph: dict[str, Any] | None = None,
) -> FieldResult:
    """
    FAQ detection — platform GT parity (Shopify / headless / React).

    DOM-visible FAQ UI is required; schema-only FAQPage entities are not counted
    unless DOM also shows FAQ markers (prevents Mamaearth-style false positives).
    """
    if not html:
        return FieldResult(0, "none", 0.0)

    graph = schema_graph or parse_schema_graph(html)
    schema_count = int(graph.get("faq_count_schema") or 0)
    value = count_faq_unified(html, schema_count=schema_count)

    if value <= 0:
        return FieldResult(0, "none", 0.0)

    source = "platform_parity.faq_dom"
    conf = 0.86
    if schema_count > 0 and _FAQ_SECTION.search(_pdp_visible_html(html)):
        source = "FAQPage.schema+dom"
        conf = 0.98
    return FieldResult(value, source, conf)


def _clean_trust_phrase(phrase: str) -> bool:
    if any(c in phrase for c in ('{"', '":"', "\\u", "srsltid", "&amp;", '","')):
        return False
    if len(phrase.strip()) < 5:
        return False
    return not _TRUST_EXCLUDE.search(phrase)


def _extract_img_alt_trust(html: str) -> list[str]:
    hits: list[str] = []
    for m in re.finditer(r"<img[^>]+>", html, re.I):
        tag = m.group(0)
        alt_m = re.search(r'alt=["\']([^"\']{3,80})["\']', tag, re.I)
        if not alt_m:
            continue
        alt = alt_m.group(1).strip()
        alt_l = alt.lower()
        if any(term in alt_l for term in _TRUST_ONTOLOGY):
            hits.append(alt)
        elif re.search(r"certif|trust|secure|verified|award|safe|guarantee", alt_l):
            hits.append(alt)
    return hits


def _extract_svg_trust(html: str) -> list[str]:
    hits: list[str] = []
    for m in re.finditer(r"<svg[^>]*>[\s\S]{0,500}?</svg>", html, re.I):
        block = m.group(0)
        for attr in ("aria-label", "title", "data-label"):
            am = re.search(rf'{attr}=["\']([^"\']{3,80})["\']', block, re.I)
            if am:
                label = am.group(1).strip()
                if not _TRUST_EXCLUDE.search(label):
                    hits.append(label)
        tm = re.search(r"<title[^>]*>([^<]{3,80})</title>", block, re.I)
        if tm:
            hits.append(tm.group(1).strip())
    return hits


def _extract_label_trust(text: str) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    # Branded trust lines (MADE SAFE, Asia's 1st, etc.)
    for m in re.finditer(
        r"([A-Z][^.!?]{8,120}(?:MADE SAFE|Verified Reviews?|Certified|Guarantee|Trusted|Award)[^.!?]{0,60}[.!?]?)",
        text,
        re.I,
    ):
        phrase = m.group(1).strip()
        if any(c in phrase for c in ('{"', '":"', "\\u")):
            continue
        key = phrase.lower()[:80]
        if key not in seen and len(phrase) > 10 and not _TRUST_EXCLUDE.search(phrase):
            seen.add(key)
            hits.append(phrase[:120])
    for term in _TRUST_ONTOLOGY:
        if term in text.lower():
            # Find the actual phrase in text
            pat = re.compile(re.escape(term), re.I)
            m = pat.search(text)
            if m:
                start = max(0, m.start() - 20)
                end = min(len(text), m.end() + 40)
                phrase = text[start:end].strip()
                key = phrase.lower()[:80]
                if key not in seen and not _TRUST_EXCLUDE.search(phrase):
                    seen.add(key)
                    hits.append(phrase[:100])
    return hits[:8]


def extract_trust_badges(html: str, *, main_text: str = "") -> FieldResult:
    region = _main_pdp_region(html)
    text = main_text or _visible_text(region)

    hits: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        phrase = phrase.strip()
        if not _clean_trust_phrase(phrase):
            return
        key = phrase.lower()[:80]
        if key in seen:
            return
        seen.add(key)
        hits.append(phrase[:120])

    # Platform GT parity — leaf trust text (Shopify, headless, React)
    for phrase in extract_trust_badges_gt(html):
        _add(phrase)

    for phrase in _extract_img_alt_trust(region) + _extract_svg_trust(region):
        _add(phrase)
    for phrase in _extract_label_trust(text):
        _add(phrase)

    if not hits:
        return FieldResult([], "none", 0.0)

    # Drop substring duplicates — prefer longest certification phrase
    hits.sort(key=len, reverse=True)
    deduped: list[str] = []
    for h in hits:
        if any(h != other and h in other for other in deduped):
            continue
        deduped.append(h)
    return FieldResult(deduped[:8], "platform_parity.trust_dom", 0.88)


def extract_shipping_visible(html: str, *, main_text: str = "") -> FieldResult:
    ship_gt, _ = extract_policy_visibility_gt(html)
    if ship_gt:
        conf = 0.86 if re.search(r"product-form|product-info|product-detail", html or "", re.I) else 0.80
        return FieldResult(True, "platform_parity.body_text", conf)

    region = _main_pdp_region(html)
    text = main_text or _visible_text(region)
    text = re.sub(r"\{[^{}]{20,}\}", " ", text)
    if _SHIPPING_PATTERNS.search(text):
        return FieldResult(True, "dom.product_zone", 0.78)
    return FieldResult(False, "none", 0.0)


def extract_return_policy_visible(html: str, *, main_text: str = "") -> FieldResult:
    _, ret_gt = extract_policy_visibility_gt(html)
    if ret_gt:
        conf = 0.86 if re.search(r"product-form|product-info|product-detail", html or "", re.I) else 0.80
        return FieldResult(True, "platform_parity.body_text", conf)

    region = _main_pdp_region(html)
    text = main_text or _visible_text(region)
    text = re.sub(r"\{[^{}]{20,}\}", " ", text)
    if _RETURN_PATTERNS.search(text):
        return FieldResult(True, "dom.product_zone", 0.78)
    return FieldResult(False, "none", 0.0)


def extract_variants(
    html: str,
    *,
    platform_variants: list[dict[str, Any]] | None = None,
    dom_picker_count: int | None = None,
) -> FieldResult:
    """
    Merge variant sources: Shopify JSON, picker buttons, swatches, dropdowns.
    Returns count (int) as value.
    """
    sources: list[tuple[int, str, float]] = []

    resolved = resolve_variant_count(html, platform_variants=platform_variants)
    if resolved:
        sources.append((resolved, "platform_parity.variant_merge", 0.93))

    api_variants = platform_variants or []
    if api_variants:
        sources.append((len(api_variants), "platform_api.variants", 0.95))

    if not html:
        if sources:
            best = max(sources, key=lambda x: x[0])
            return FieldResult(best[0], best[1], best[2])
        return FieldResult(0, "none", 0.0)

    # DOM: swatches, buttons, dropdowns, radios
    picker_selectors = len(re.findall(
        r'select[^>]*name=["\'][^"\']*option|'
        r'class=["\'][^"\']*swatch[^"\']*["\']|'
        r'data-variant-id|'
        r'product-form__input[^>]*type=["\']radio["\']|'
        r'class=["\'][^"\']*variant[^"\']*["\'][^>]*(?:button|input)',
        html,
        re.I,
    ))
    swatches = len(re.findall(
        r'class=["\'][^"\']*(?:swatch|color-swatch|variant-swatch)[^"\']*["\']',
        html,
        re.I,
    ))
    variant_buttons = len(re.findall(
        r'class=["\'][^"\']*variant[^"\']*["\'][^>]*>\s*(?:<button|<input|<label)',
        html,
        re.I,
    ))
    dropdown_opts = len(re.findall(
        r'<select[^>]*(?:variant|option)[^>]*>[\s\S]*?<option',
        html,
        re.I,
    ))

    dom_count = max(picker_selectors, swatches, variant_buttons, dropdown_opts, dom_picker_count or 0)
    if dom_count:
        sources.append((dom_count, "dom.variant_picker", 0.78))

    # Shopify embedded JSON variant count
    shopify_var_match = re.search(r'"variants"\s*:\s*\[([\s\S]{10,50000}?)\]', html)
    if shopify_var_match:
        id_count = len(re.findall(r'"id"\s*:', shopify_var_match.group(1)))
        if id_count:
            sources.append((id_count, "shopify_json.variants", 0.90))

    if not sources:
        return FieldResult(0, "none", 0.0)

    gt_src = [s for s in sources if "platform_parity.variant" in s[1]]
    api = [s for s in sources if s[1].startswith("platform_api")]
    dom_other = [s for s in sources if s[1].startswith("dom.") or s[1].startswith("shopify_json")]

    if gt_src:
        gt_val = max(gt_src, key=lambda x: x[0])[0]
        if api:
            api_val = max(api, key=lambda x: x[0])[0]
            # React/headless: DOM picker often exceeds API variant array length
            if gt_val >= api_val or gt_val >= api_val * 0.85:
                return FieldResult(gt_val, gt_src[0][1], gt_src[0][2])
        else:
            return FieldResult(gt_val, gt_src[0][1], gt_src[0][2])

    if api:
        best = max(api, key=lambda x: x[0])
        dom_best = max(dom_other, key=lambda x: x[0], default=None) if dom_other else None
        if dom_best and dom_best[0] > best[0]:
            return FieldResult(dom_best[0], dom_best[1], dom_best[2])
        return FieldResult(best[0], best[1], best[2])

    best = max(sources, key=lambda x: (x[0], x[2]))
    return FieldResult(best[0], best[1], best[2])


def extract_inventory(
    html: str,
    *,
    schema_graph: dict[str, Any] | None = None,
    inventory_quantity: int | None = None,
    availability: str | None = None,
) -> FieldResult:
    """
    Inventory from Offer.availability schema, Shopify API qty, visible DOM signals.
    Returns int quantity, str status ("Out of stock"), or None.
    """
    graph = schema_graph or parse_schema_graph(html)

    # Schema Offer.availability — highest priority
    schema_avail = graph.get("offer_availability") or availability
    if schema_avail == "OutOfStock":
        return FieldResult("Out of stock", "Offer.schema.availability", 0.95)
    if inventory_quantity is not None and inventory_quantity >= 0:
        return FieldResult(inventory_quantity, "platform_api.inventory_quantity", 0.93)

    if not html:
        if schema_avail == "InStock":
            return FieldResult(None, "Offer.schema.availability", 0.80)
        return FieldResult(None, "none", 0.0)

    region = _main_pdp_region(html)
    text = _visible_text(region)

    stock_patterns = [
        (r"\bout of stock\b", "Out of stock", 0.88),
        (r"\bsold out\b", "Out of stock", 0.88),
        (r"\bonly\s+(\d+)\s+left\b", None, 0.85),
        (r"\b(\d+)\s+in stock\b", None, 0.85),
        (r"\blow stock\b", "Low stock", 0.75),
    ]
    for pat, status, conf in stock_patterns:
        m = re.search(pat, text, re.I)
        if m:
            if status:
                return FieldResult(status, "dom.visible_text", conf)
            try:
                qty = int(m.group(1))
                return FieldResult(qty, "dom.visible_text", conf)
            except (IndexError, ValueError):
                pass

    if schema_avail == "InStock":
        return FieldResult(None, "Offer.schema.availability", 0.80)

    return FieldResult(None, "none", 0.0)


def extract_all_pdp_signals(
    html: str,
    *,
    platform_data: dict[str, Any] | None = None,
    main_text: str = "",
) -> dict[str, Any]:
    """Run all enterprise PDP signal extractors; return flat + confidence dict."""
    platform = platform_data or {}
    graph = parse_schema_graph(html)

    faq = extract_faq(html, schema_graph=graph)
    trust = extract_trust_badges(html, main_text=main_text)
    shipping = extract_shipping_visible(html, main_text=main_text)
    returns = extract_return_policy_visible(html, main_text=main_text)
    variants = extract_variants(
        html,
        platform_variants=platform.get("variants"),
        dom_picker_count=platform.get("variant_picker_count"),
    )
    inventory = extract_inventory(
        html,
        schema_graph=graph,
        inventory_quantity=platform.get("inventory_quantity"),
        availability=platform.get("availability"),
    )
    review_provider = detect_review_provider(html) or platform.get("review_provider")

    return {
        "faq_count": faq.value,
        "faq_count_confidence": faq.to_dict(),
        "trust_badges": trust.value,
        "trust_badges_confidence": trust.to_dict(),
        "shipping_visible": shipping.value,
        "shipping_visible_confidence": shipping.to_dict(),
        "return_policy_visible": returns.value,
        "return_policy_visible_confidence": returns.to_dict(),
        "variant_count": variants.value,
        "variant_count_confidence": variants.to_dict(),
        "inventory": inventory.value,
        "inventory_confidence": inventory.to_dict(),
        "review_provider": review_provider,
        "schema_graph": graph,
    }
