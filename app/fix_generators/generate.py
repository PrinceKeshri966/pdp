"""
Structured copy-paste-ready fixes (deterministic).
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from app.core.page_type_router import is_pdp


def _fix(fix_type: str, code: str, framework: str = "html") -> dict[str, Any]:
    return {
        "fix_type": fix_type,
        "copy_paste_ready": True,
        "framework": framework,
        "code": code.strip(),
    }


def faq_schema_json_ld(questions: list[dict[str, str]]) -> dict[str, Any]:
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q.get("question", ""),
                "acceptedAnswer": {"@type": "Answer", "text": q.get("answer", "")},
            }
            for q in questions
            if q.get("question")
        ],
    }
    code = f'<script type="application/ld+json">\n{json.dumps(payload, indent=2)}\n</script>'
    return _fix("faq_schema_json_ld", code)


def organization_schema(name: str, url: str) -> dict[str, Any]:
    payload = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name,
        "url": url,
    }
    code = f'<script type="application/ld+json">\n{json.dumps(payload, indent=2)}\n</script>'
    return _fix("organization_schema", code)


def breadcrumb_schema(items: list[dict[str, str]]) -> dict[str, Any]:
    elements = [
        {
            "@type": "ListItem",
            "position": i + 1,
            "name": it.get("name", ""),
            "item": it.get("url", ""),
        }
        for i, it in enumerate(items)
        if it.get("name")
    ]
    payload = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": elements}
    code = f'<script type="application/ld+json">\n{json.dumps(payload, indent=2)}\n</script>'
    return _fix("breadcrumb_schema", code)


def open_graph_tags(title: str, description: str, url: str, image: str = "") -> dict[str, Any]:
    lines = [
        f'<meta property="og:title" content="{title[:70]}" />',
        f'<meta property="og:description" content="{description[:200]}" />',
        f'<meta property="og:url" content="{url}" />',
        '<meta property="og:type" content="website" />',
    ]
    if image:
        lines.append(f'<meta property="og:image" content="{image}" />')
    return _fix("open_graph_tags", "\n".join(lines))


def twitter_card_tags(title: str, description: str, image: str = "") -> dict[str, Any]:
    lines = [
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{title[:70]}" />',
        f'<meta name="twitter:description" content="{description[:200]}" />',
    ]
    if image:
        lines.append(f'<meta name="twitter:image" content="{image}" />')
    return _fix("twitter_card_tags", "\n".join(lines))


def canonical_tag(url: str) -> dict[str, Any]:
    return _fix("canonical_tag", f'<link rel="canonical" href="{url}" />')


def meta_title_fix(title: str) -> dict[str, Any]:
    return _fix("meta_title", f"<title>{title[:60]}</title>")


def lazy_loading_snippet() -> dict[str, Any]:
    return _fix(
        "lazy_loading_images",
        '<img src="hero.jpg" alt="Hero" fetchpriority="high" />\n'
        '<img src="detail-1.jpg" alt="Detail" loading="lazy" decoding="async" />',
    )


def faq_accordion_html(questions: list[dict[str, str]]) -> dict[str, Any]:
    parts = ['<section class="faq-accordion" aria-label="Frequently asked questions">']
    for i, q in enumerate(questions[:6]):
        parts.append(
            f'  <details id="faq-{i}">\n'
            f'    <summary>{q.get("question", "")}</summary>\n'
            f'    <p>{q.get("answer", "")}</p>\n'
            f"  </details>"
        )
    parts.append("</section>")
    return _fix("faq_accordion_html", "\n".join(parts))


def generate_deployable_fixes(
    *,
    url: str,
    page_type: str,
    seo_report: dict[str, Any],
    dom_facts: dict[str, Any],
    structured: dict[str, Any],
    aeo_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Produce ready-to-deploy fix objects from audit facts."""
    fixes: list[dict[str, Any]] = []
    aeo_report = aeo_report or {}
    title = (seo_report.get("title_tag") or {}).get("value") or dom_facts.get("title_tag") or ""
    meta = (seo_report.get("meta_description") or {}).get("value") or dom_facts.get("meta_description") or ""
    brand = structured.get("brand") or structured.get("product_name") or urlparse(url).netloc
    name = structured.get("product_name") or brand

    if title:
        fixes.append(meta_title_fix(title[:60]))
    if url:
        fixes.append(canonical_tag(url))
    if title and meta:
        fixes.append(open_graph_tags(title, meta, url))
        fixes.append(twitter_card_tags(title, meta))

    sd = (seo_report.get("structured_data") or {})
    if not sd.get("has_faq_schema"):
        qs = [
            {"question": "What is this product?", "answer": (structured.get("description") or "")[:300]},
            {"question": f"What is {brand}?", "answer": f"{brand} offers quality products and services."},
        ]
        fixes.append(faq_schema_json_ld(qs))
        fixes.append(faq_accordion_html(qs))

    if is_pdp(page_type):
        crumbs = [
            {"name": "Home", "url": f"{urlparse(url).scheme}://{urlparse(url).netloc}/"},
            {"name": name or "Product", "url": url},
        ]
        fixes.append(breadcrumb_schema(crumbs))
    elif page_type in ("homepage", "saas_landing"):
        fixes.append(organization_schema(str(brand), url))

    img_seo = seo_report.get("image_seo") or {}
    if img_seo.get("score", 10) < 7:
        fixes.append(lazy_loading_snippet())

    return fixes
