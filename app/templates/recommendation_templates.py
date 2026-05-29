"""
Deterministic recommendation templates — avoid LLM for repetitive fixes.
"""
from __future__ import annotations

from typing import Any

from app.core.recommendation_meta import wrap_recommendation


def template_for_issue(issue_key: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ctx = context or {}
    templates = {
        "faq_schema_missing": {
            "category": "AEO",
            "action": "Add FAQPage JSON-LD with 3–5 real customer questions and concise answers.",
            "impact": "high",
            "effort": "low",
            "estimated_improvement": "Improves AI answer inclusion and rich result eligibility",
            "why_now": "FAQ schema is missing but competitors or SERP features use it",
        },
        "duplicate_h1": {
            "category": "SEO",
            "action": "Use exactly one H1 per page; demote extras to H2.",
            "impact": "high",
            "effort": "low",
            "estimated_improvement": "Clearer topical focus for crawlers",
            "why_now": "Multiple H1 tags detected",
        },
        "lazy_loading_missing": {
            "category": "SEO",
            "action": "Add loading=\"lazy\" to below-fold images; keep LCP hero image eager.",
            "impact": "medium",
            "effort": "low",
            "estimated_improvement": "Faster LCP and lower bandwidth",
            "why_now": "Many images lack lazy loading",
        },
        "missing_meta_description": {
            "category": "SEO",
            "action": "Write a unique meta description (140–160 chars) with primary keyword and CTA.",
            "impact": "high",
            "effort": "low",
            "estimated_improvement": "Better CTR from search snippets",
            "why_now": "Meta description missing or too short",
        },
        "missing_canonical": {
            "category": "SEO",
            "action": "Add rel=canonical pointing to the preferred URL for this page.",
            "impact": "medium",
            "effort": "low",
            "estimated_improvement": "Reduces duplicate content risk",
            "why_now": "Canonical tag not found",
        },
        "missing_og_tags": {
            "category": "SEO",
            "action": "Add Open Graph title, description, image, and url tags for social sharing.",
            "impact": "medium",
            "effort": "low",
            "estimated_improvement": "Consistent previews on social platforms",
            "why_now": "Open Graph tags incomplete",
        },
        "weak_cta_above_fold": {
            "category": "UX",
            "action": "Place primary CTA above the fold with contrasting color and action-oriented copy.",
            "impact": "high",
            "effort": "medium",
            "estimated_improvement": "Higher click-through to conversion path",
            "why_now": "Primary CTA not visible above fold",
        },
    }
    tpl = templates.get(issue_key)
    if not tpl:
        return None
    out = dict(tpl)
    out["confidence_meta"] = wrap_recommendation(
        out["action"],
        confidence=0.85,
        deterministic=True,
        source="template",
        evidence=[issue_key],
        page_type_validated=ctx.get("page_type_validated", True),
    )
    return out


def build_prioritized_from_facts(
    *,
    seo_facts: dict | None = None,
    seo_report: dict | None = None,
    aeo_report: dict | None = None,
    ux_facts: dict | None = None,
    visual: dict | None = None,
    page_type: str = "unknown",
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Build ranked recommendations without LLM."""
    seo_facts = seo_facts or {}
    seo_report = seo_report or {}
    aeo_report = aeo_report or {}
    ux_facts = ux_facts or {}
    visual = visual or {}
    items: list[dict[str, Any]] = []
    rank = 1

    sd = seo_facts.get("structured_data") or seo_report.get("structured_data") or {}
    if not sd.get("has_faq_schema"):
        t = template_for_issue("faq_schema_missing", {"page_type_validated": page_type != "homepage"})
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1

    h1 = seo_facts.get("h1") or seo_report.get("h1") or {}
    if h1.get("count", 1) > 1:
        t = template_for_issue("duplicate_h1")
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1

    meta = seo_facts.get("meta_description") or seo_report.get("meta_description") or {}
    if (meta.get("length") or 0) < 50:
        t = template_for_issue("missing_meta_description")
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1

    img = seo_facts.get("image_seo") or {}
    if img.get("lazy_loading_ratio", 1) < 0.5:
        t = template_for_issue("lazy_loading_missing")
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1

    if visual.get("capture_ok") and not visual.get("cta_above_fold"):
        t = template_for_issue("weak_cta_above_fold")
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1
    elif not ux_facts.get("above_fold_cta") and page_type in ("homepage", "saas_landing", "pdp"):
        t = template_for_issue("weak_cta_above_fold")
        if t:
            t["rank"] = rank
            items.append(t)
            rank += 1

    for issue in (seo_report.get("top_issues") or [])[:3]:
        if rank > max_items:
            break
        items.append(
            {
                "rank": rank,
                "category": "SEO",
                "action": issue,
                "impact": "medium",
                "effort": "medium",
                "estimated_improvement": "Addresses detected SEO gap",
                "why_now": "Listed in SEO top issues",
                "confidence_meta": wrap_recommendation(issue, confidence=0.6, source="llm"),
            }
        )
        rank += 1

    for gap in (aeo_report.get("gaps") or [])[:2]:
        if rank > max_items:
            break
        items.append(
            {
                "rank": rank,
                "category": "AEO",
                "action": gap,
                "impact": "medium",
                "effort": "medium",
                "estimated_improvement": "Improves AI visibility",
                "why_now": "AEO gap detected",
                "confidence_meta": wrap_recommendation(gap, confidence=0.55, source="llm"),
            }
        )
        rank += 1

    return items[:max_items]
