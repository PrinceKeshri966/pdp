"""
Deterministic UX / CRO signal extraction — no LLM.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.extraction.pdp_signals import (
    extract_return_policy_visible,
    extract_shipping_visible,
    extract_trust_badges,
)
from app.core.evidence.audit_findings import _classify_gallery_images

_CTA = re.compile(
    r"\b(add to cart|buy now|shop now|get started|sign up|subscribe|"
    r"download|order now|try free|book now|join now|learn more|add to bag)\b",
    re.I,
)
_PAYMENT = re.compile(
    r"(visa|mastercard|amex|paypal|upi|razorpay|paytm|gpay|google pay|"
    r"apple pay|cod|cash on delivery|emi\b)",
    re.I,
)
_URGENCY = re.compile(
    r"(only \d+ left|limited stock|ends in|hurry|last chance|"
    r"\d+ people viewing|sold in last|almost gone|flash sale|today only)",
    re.I,
)
_MOBILE = re.compile(
    r"(viewport|mobile|responsive|touch|tap target|swipe)",
    re.I,
)
_REVIEW = re.compile(
    r"(reviews?|ratings?|testimonials?|customer says|verified buyer)",
    re.I,
)
_ZOOM = re.compile(
    r"(data-zoom|zoom-image|image-zoom|magnify|product-zoom|photoswipe|"
    r'class=["\'][^"\']*zoom[^"\']*["\'])',
    re.I,
)
_MATERIAL = re.compile(
    r"(material[s]?\s*:|composition|fabric|100%\s*cotton|polyester|leather|"
    r"ingredients?|what(?:\'|)s inside|made from)",
    re.I,
)
_FIT = re.compile(
    r"(fit[s]?\s*:|regular fit|slim fit|relaxed fit|true to size|"
    r"size.?chart|how it fits|fit guide)",
    re.I,
)
_SPECS = re.compile(
    r'(<table[^>]*class=["\'][^"\']*spec|specifications?|technical details|'
    r"product details|dimensions?|weight:|warranty)",
    re.I,
)


def _text_blob(*parts: str) -> str:
    return " ".join(p for p in parts if p).lower()


def _page_text(ctx_pages: dict[str, dict[str, Any]], role: str) -> str:
    page = ctx_pages.get(role) or {}
    bits = [page.get("title") or ""]
    for h in page.get("headings") or []:
        bits.append(h.get("text", ""))
    bits.extend(page.get("key_paragraphs") or [])
    bits.extend(page.get("trust_signals") or [])
    bits.extend(page.get("cta_examples") or [])
    return _text_blob(*bits)


def extract_ux_facts(
    *,
    page_contexts: dict[str, dict[str, Any]] | None = None,
    structured: dict[str, Any] | None = None,
    markdown: str = "",
    scrape_html: str = "",
) -> dict[str, Any]:
    """Compact UX facts from context pages + structured product data."""
    pages = page_contexts or {}
    structured = structured or {}
    pdp_signals = structured.get("_pdp_signals") or {}

    main_t = _page_text(pages, "main")
    main_body = ""
    if scrape_html:
        main_body = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", scrape_html, flags=re.I)
        main_body = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", main_body, flags=re.I)
        main_body = re.sub(r"<[^>]+>", " ", main_body)
        main_body = re.sub(r"\s+", " ", main_body).strip()
    main_visible = _text_blob(main_t, main_body, (markdown or "")[:12000])

    ctas = list(dict.fromkeys(_CTA.findall(main_visible)))
    urgency = list(dict.fromkeys(m.group(0) for m in _URGENCY.finditer(main_visible)))[:8]

    images_count = int(structured.get("images_count") or 0)
    has_video = bool(structured.get("has_video"))
    has_reviews = bool(structured.get("has_reviews")) or bool(_REVIEW.search(main_visible))
    review_count = structured.get("review_count")
    rating = structured.get("avg_rating")

    # Enterprise trust/shipping/returns — use precomputed pipeline signals when available
    if pdp_signals.get("trust_badges_confidence"):
        trust_result = pdp_signals["trust_badges_confidence"]
        trust_hits = trust_result.get("value") or pdp_signals.get("trust_badges") or []
        trust_confidence = trust_result
    else:
        trust = extract_trust_badges(scrape_html or "", main_text=main_body or main_t)
        trust_hits = trust.value or []
        trust_confidence = trust.to_dict()

    if pdp_signals.get("shipping_visible_confidence"):
        shipping_visible = bool(pdp_signals.get("shipping_visible"))
        shipping_confidence = pdp_signals["shipping_visible_confidence"]
    else:
        ship = extract_shipping_visible(scrape_html or "", main_text=main_body)
        shipping_visible = bool(ship.value)
        shipping_confidence = ship.to_dict()

    if pdp_signals.get("return_policy_visible_confidence"):
        returns_visible = bool(pdp_signals.get("return_policy_visible"))
        returns_confidence = pdp_signals["return_policy_visible_confidence"]
    else:
        ret = extract_return_policy_visible(scrape_html or "", main_text=main_body)
        returns_visible = bool(ret.value)
        returns_confidence = ret.to_dict()

    payment_icons = bool(_PAYMENT.search(main_visible))
    mobile_hints = [m.group(0) for m in _MOBILE.finditer(main_visible)][:5]
    gallery = _classify_gallery_images(scrape_html or "", structured)
    html_blob = scrape_html or ""
    zoom_detected = bool(_ZOOM.search(html_blob))
    material_detected = bool(_MATERIAL.search(main_visible) or _MATERIAL.search(html_blob[:50000]))
    fit_detected = bool(_FIT.search(main_visible) or _FIT.search(html_blob[:50000]))
    specs_detected = bool(_SPECS.search(html_blob[:80000]))

    return {
        "cta_candidates": ctas[:10],
        "cta_count": len(ctas),
        "trust_badges": trust_hits,
        "trust_badges_confidence": trust_confidence,
        "payment_mentions": list(dict.fromkeys(_PAYMENT.findall(main_visible)))[:8],
        "shipping_visible": shipping_visible,
        "shipping_visible_confidence": shipping_confidence,
        "return_policy_visible": returns_visible,
        "return_policy_visible_confidence": returns_confidence,
        "reviews_visible": has_reviews,
        "review_count_visible": review_count is not None,
        "avg_rating_visible": rating is not None,
        "urgency_snippets": urgency,
        "mobile_ux_hints": mobile_hints,
        "images_count": images_count,
        "has_video": has_video,
        "lifestyle_image_count": gallery["lifestyle"],
        "packshot_count": gallery["packshot"],
        "gallery_classification": gallery,
        "has_size_guide": bool(structured.get("has_size_guide")),
        "zoom_capability_detected": zoom_detected,
        "material_composition_detected": material_detected,
        "fit_description_detected": fit_detected,
        "specifications_table_detected": specs_detected,
        "sticky_cta_detected": bool(structured.get("sticky_cta_detected")),
        "above_fold_cta": structured.get("above_fold_cta"),
        "trust_badges_structured": structured.get("trust_badges") or [],
        "money_back_guarantee": bool(re.search(r"money.?back|satisfaction guarantee", main_visible, re.I)),
        "security_badges": bool(re.search(r"secure|ssl|encrypted|pci", main_visible, re.I)),
        "_deterministic": True,
    }
