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
) -> dict[str, Any]:
    pages = page_contexts or {}
    structured = structured or {}
    main = _page_text(pages, "main").lower()
    reviews = _page_text(pages, "reviews").lower()
    blob = f"{main} {reviews} {(markdown or '')[:6000].lower()}"

    scarcity = list(dict.fromkeys(m.group(0) for m in _SCARCITY.finditer(blob)))[:6]
    urgency = list(dict.fromkeys(m.group(0) for m in _URGENCY.finditer(blob)))[:6]
    authority = list(dict.fromkeys(m.group(0) for m in _AUTHORITY.finditer(blob)))[:6]
    social = list(dict.fromkeys(m.group(0) for m in _SOCIAL.finditer(blob)))[:8]
    emotional = list(dict.fromkeys(m.group(0) for m in _EMOTIONAL.finditer(blob)))[:8]
    testimonials = [m.group(0)[:140] for m in _TESTIMONIAL.finditer(blob)][:5]

    price = structured.get("price") or structured.get("original_price") or ""
    charm = bool(re.search(r"\d[79]$|\d\.99", str(price)))

    return {
        "scarcity_language": scarcity,
        "urgency_language": urgency,
        "authority_claims": authority,
        "social_proof_snippets": social,
        "emotional_phrases": emotional,
        "testimonials": testimonials,
        "reciprocity_signals": list(dict.fromkeys(_RECIPROCITY.findall(blob)))[:5],
        "commitment_signals": list(dict.fromkeys(_COMMITMENT.findall(blob)))[:5],
        "has_reviews": bool(structured.get("has_reviews")) or bool(reviews.strip()),
        "review_count": structured.get("review_count"),
        "avg_rating": structured.get("avg_rating"),
        "price_display": str(price) if price else None,
        "charm_pricing_detected": charm,
        "anchor_price_present": bool(structured.get("original_price")),
        "_deterministic": True,
    }
