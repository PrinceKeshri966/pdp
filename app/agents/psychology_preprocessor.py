"""
Deterministic conversion psychology signal extraction — no LLM.
"""
from __future__ import annotations

import re
from typing import Any

_SCARCITY = re.compile(
    r"(only \d+ left|limited stock|almost sold out|last \d+|while supplies last|"
    r"exclusive offer|limited time)",
    re.I,
)
_URGENCY = re.compile(
    r"(hurry|ends (?:soon|tonight|today)|act now|don't miss|today only|"
    r"expires|countdown|flash sale)",
    re.I,
)
_AUTHORITY = re.compile(
    r"(expert|doctor recommended|dermatologist|award.?winning|#\d+|"
    r"as seen on|featured in|certified|years of experience|trusted by)",
    re.I,
)
_SOCIAL = re.compile(
    r"(\d+[\d,]*\s*(?:customers?|users?|people)|bestseller|"
    r"most popular|join \d+|rated \d|★|stars?|reviews?)",
    re.I,
)
_EMOTIONAL = re.compile(
    r"(love|dream|transform|confidence|feel|beautiful|premium|"
    r"lifestyle|you deserve|unlock|discover your)",
    re.I,
)
_TESTIMONIAL = re.compile(
    r'("[^"]{20,120}"|said\s+\w+|customer\s+\w+\s+said|★{1,5})',
    re.I,
)
_RECIPROCITY = re.compile(r"(free gift|bonus|complimentary|on us|no extra cost)", re.I)
_COMMITMENT = re.compile(r"(subscribe|membership|loyalty|join the|become a member)", re.I)
_CERTIFICATION = re.compile(
    r"(certified|certification|iso\s*\d+|fda|organic|vegan| cruelty.free|"
    r"dermatologist tested|clinically proven|award.?winning badge)",
    re.I,
)
_COUNTDOWN = re.compile(
    r"(countdown|timer|ends in|hours? left|minutes? left|time remaining|"
    r"offer expires|sale ends)",
    re.I,
)
_LOW_STOCK = re.compile(
    r"(only \d+ left|low stock|almost sold out|last \d+ in stock|"
    r"hurry.?only|limited quantity|few left)",
    re.I,
)
_FREE_RETURNS = re.compile(
    r"(free return|easy return|30.?day return|no.?questions return|"
    r"hassle.?free return|money.?back guarantee|satisfaction guarantee)",
    re.I,
)
_GUARANTEE = re.compile(
    r"(100% guarantee|lifetime warranty|quality guarantee|"
    r"buyer protection|secure checkout guarantee)",
    re.I,
)
_IDENTITY = re.compile(
    r"(for (?:him|her|men|women|kids|athletes|professionals)|"
    r"who (?:you|we) are|made for|perfect for|ideal for|"
    r"your (?:style|identity|journey)|people like you)",
    re.I,
)
_UNITY = re.compile(
    r"(join (?:our|the)|community|belong|together we|"
    r"be part of|members only|tribe|family of \d+|#\w+community)",
    re.I,
)
_DECOY = re.compile(
    r"(basic|standard|premium|pro|plus|ultimate|best value|most popular|"
    r"compare plans|choose (?:your|a) plan)",
    re.I,
)
_PEAK_END = re.compile(
    r"(shop now|buy now|add to cart|order today|get yours|"
    r"limited time|don't miss|start now|claim offer)",
    re.I,
)


def _page_text(ctx_pages: dict[str, dict[str, Any]], role: str) -> str:
    page = ctx_pages.get(role) or {}
    bits = [page.get("title") or ""]
    bits.extend(page.get("key_paragraphs") or [])
    bits.extend(page.get("review_snippets") or [])
    bits.extend(page.get("trust_signals") or [])
    return " ".join(bits)


def extract_psychology_facts(
    *,
    page_contexts: dict[str, dict[str, Any]] | None = None,
    structured: dict[str, Any] | None = None,
    markdown: str = "",
    scrape_html: str = "",
) -> dict[str, Any]:
    pages = page_contexts or {}
    structured = structured or {}
    main = _page_text(pages, "main").lower()
    reviews = _page_text(pages, "reviews").lower()
    blob = f"{main} {reviews} {(markdown or '')[:6000].lower()}"
    html_tail = (scrape_html or "")[-12000:].lower() if scrape_html else ""

    scarcity = list(dict.fromkeys(m.group(0) for m in _SCARCITY.finditer(blob)))[:6]
    urgency = list(dict.fromkeys(m.group(0) for m in _URGENCY.finditer(blob)))[:6]
    authority = list(dict.fromkeys(m.group(0) for m in _AUTHORITY.finditer(blob)))[:6]
    social = list(dict.fromkeys(m.group(0) for m in _SOCIAL.finditer(blob)))[:8]
    emotional = list(dict.fromkeys(m.group(0) for m in _EMOTIONAL.finditer(blob)))[:8]
    testimonials = [m.group(0)[:140] for m in _TESTIMONIAL.finditer(blob)][:5]
    certifications = list(dict.fromkeys(m.group(0) for m in _CERTIFICATION.finditer(blob)))[:6]

    price = structured.get("price") or structured.get("original_price") or ""
    charm = bool(re.search(r"\d[79]$|\d\.99", str(price)))
    inv_qty = structured.get("inventory_quantity")
    low_stock = bool(_LOW_STOCK.search(blob)) or (
        isinstance(inv_qty, int) and 0 < inv_qty <= 5
    )
    decoy_hits = len(_DECOY.findall(blob))
    if scrape_html:
        decoy_hits += len(re.findall(r'class=["\'][^"\']*plan[^"\']*["\']', scrape_html, re.I))
        decoy_hits += len(re.findall(r'class=["\'][^"\']*tier[^"\']*["\']', scrape_html, re.I))
    decoy_detected = decoy_hits >= 3
    peak_end_detected = bool(_PEAK_END.search(html_tail)) if html_tail else bool(_PEAK_END.search(blob[-800:]))
    identity_detected = bool(_IDENTITY.search(blob))
    unity_detected = bool(_UNITY.search(blob))

    return {
        "scarcity_language": scarcity,
        "urgency_language": urgency,
        "authority_claims": authority,
        "social_proof_snippets": social,
        "emotional_phrases": emotional,
        "testimonials": testimonials,
        "certification_badges": certifications,
        "reciprocity_signals": list(dict.fromkeys(_RECIPROCITY.findall(blob)))[:5],
        "commitment_signals": list(dict.fromkeys(_COMMITMENT.findall(blob)))[:5],
        "has_reviews": bool(structured.get("has_reviews")) or bool(reviews.strip()),
        "review_count": structured.get("review_count"),
        "avg_rating": structured.get("avg_rating"),
        "ugc_image_count": structured.get("ugc_image_count") or 0,
        "has_ugc_images": bool(structured.get("has_ugc_images") or structured.get("ugc_image_count")),
        "price_display": str(price) if price else None,
        "charm_pricing_detected": charm,
        "anchor_price_present": bool(structured.get("original_price") or structured.get("compare_at_price")),
        "low_stock_detected": low_stock,
        "countdown_timer_detected": bool(_COUNTDOWN.search(blob)),
        "free_returns_detected": bool(_FREE_RETURNS.search(blob)),
        "guarantee_detected": bool(_GUARANTEE.search(blob)),
        "decoy_pricing_detected": decoy_detected,
        "peak_end_rule_detected": peak_end_detected,
        "identity_alignment_detected": identity_detected,
        "unity_detected": unity_detected,
        "deterministic_psychology_score": None,
        "_deterministic": True,
    }
