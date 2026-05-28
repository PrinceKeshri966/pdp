"""
Deterministic UX / CRO signal extraction — no LLM.
"""
from __future__ import annotations

import re
from typing import Any

_CTA = re.compile(
    r"\b(add to cart|buy now|shop now|get started|sign up|subscribe|"
    r"download|order now|try free|book now|join now|learn more|add to bag)\b",
    re.I,
)
_TRUST = re.compile(
    r"(secure|ssl|verified|trusted|guarantee|money.?back|free shipping|"
    r"certified|award|norton|mcafee|pci|iso\s*\d|bbb|trustpilot|"
    r"\d+\+?\s*(reviews?|ratings?)|\d\.\d\s*/\s*5|★|⭐|verified purchase)",
    re.I,
)
_PAYMENT = re.compile(
    r"(visa|mastercard|amex|paypal|upi|razorpay|paytm|gpay|google pay|"
    r"apple pay|cod|cash on delivery|emi\b)",
    re.I,
)
_SHIPPING = re.compile(
    r"(free shipping|ships in|delivery in|dispatch|deliver(?:y|ed) by|"
    r"shipping policy|express delivery)",
    re.I,
)
_RETURNS = re.compile(
    r"(return policy|easy returns|\d+\s*day[s]?\s*return|money.?back|"
    r"hassle.?free return|exchange policy)",
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
) -> dict[str, Any]:
    """Compact UX facts from context pages + structured product data."""
    pages = page_contexts or {}
    structured = structured or {}
    main_t = _page_text(pages, "main")
    ship_t = _page_text(pages, "shipping")
    ret_t = _page_text(pages, "returns")
    blob = _text_blob(main_t, ship_t, ret_t, (markdown or "")[:8000].lower())

    ctas = list(dict.fromkeys(_CTA.findall(blob)))
    trust_hits = list(dict.fromkeys(m.group(0) for m in _TRUST.finditer(blob)))[:12]
    urgency = list(dict.fromkeys(m.group(0) for m in _URGENCY.finditer(blob)))[:8]

    images_count = int(structured.get("images_count") or 0)
    has_video = bool(structured.get("has_video"))
    has_reviews = bool(structured.get("has_reviews")) or bool(_REVIEW.search(blob))
    review_count = structured.get("review_count")
    rating = structured.get("avg_rating")

    shipping_visible = bool(_SHIPPING.search(blob)) or bool(structured.get("shipping_info"))
    returns_visible = bool(_RETURNS.search(blob)) or bool(structured.get("return_policy"))
    payment_icons = bool(_PAYMENT.search(blob))

    mobile_hints = [m.group(0) for m in _MOBILE.finditer(blob)][:5]

    return {
        "cta_candidates": ctas[:10],
        "cta_count": len(ctas),
        "trust_badges": trust_hits,
        "payment_mentions": list(dict.fromkeys(_PAYMENT.findall(blob)))[:8],
        "shipping_visible": shipping_visible,
        "return_policy_visible": returns_visible,
        "reviews_visible": has_reviews,
        "review_count_visible": review_count is not None,
        "avg_rating_visible": rating is not None,
        "urgency_snippets": urgency,
        "mobile_ux_hints": mobile_hints,
        "images_count": images_count,
        "has_video": has_video,
        "has_size_guide": bool(structured.get("has_size_guide")),
        "above_fold_cta": structured.get("above_fold_cta"),
        "trust_badges_structured": structured.get("trust_badges") or [],
        "money_back_guarantee": bool(re.search(r"money.?back|satisfaction guarantee", blob, re.I)),
        "security_badges": bool(re.search(r"secure|ssl|encrypted|pci", blob, re.I)),
        "_deterministic": True,
    }
