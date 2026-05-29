"""
Confidence scores for every audit section.
"""
from __future__ import annotations

from typing import Any


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def compute_section_confidence(state: dict[str, Any]) -> dict[str, Any]:
    """Compute per-section confidence scores based on capture quality and data sources."""
    browser = state.get("browser_capture") or {}
    scrape_val = state.get("scrape_validation") or {}
    ext_conf = state.get("extraction_confidence") or {}
    method = state.get("scraper_method") or "unknown"
    visual = state.get("visual_ux_facts") or {}
    lighthouse = browser.get("lighthouse") or {}
    schema = browser.get("schema_validation") or {}
    tech = browser.get("technical_crawl") or {}
    dom_seo = browser.get("dom_seo") or {}

    is_browser = method.startswith("playwright") or method == "browser_capture"
    scrape_conf = float(scrape_val.get("confidence") or (0.85 if is_browser else 0.55))
    ext_overall = float(ext_conf.get("overall_extraction_confidence") or 0.7)

    sections: dict[str, dict[str, Any]] = {}

    sections["scrape"] = {
        "confidence": round(_clamp(scrape_conf), 2),
        "source": method,
        "browser_first": is_browser,
    }

    sections["extraction"] = {
        "confidence": round(_clamp(ext_overall), 2),
        "field_confidence": ext_conf.get("field_confidence") or {
            "product_name": ext_conf.get("product_name_confidence"),
            "price": ext_conf.get("price_confidence"),
            "reviews": ext_conf.get("reviews_confidence"),
            "brand": ext_conf.get("brand_confidence"),
            "images": ext_conf.get("image_confidence"),
            "schema": ext_conf.get("schema_confidence"),
        },
    }

    sections["seo"] = {
        "confidence": round(_clamp(
            (dom_seo.get("confidence") or 0.7) * (0.9 if is_browser else 0.6)
        ), 2),
        "source": "rendered_dom" if is_browser else "markdown_heuristic",
    }

    sections["structured_data"] = {
        "confidence": round(_clamp(schema.get("overall_confidence") or (0.8 if is_browser else 0.5)), 2),
        "schemas_validated": list((schema.get("schemas") or {}).keys()),
    }

    sections["technical_seo"] = {
        "confidence": round(_clamp(tech.get("confidence") or (0.75 if is_browser else 0.45)), 2),
        "checks_run": ["robots.txt", "sitemap.xml", "canonical", "hreflang", "open_graph", "twitter_cards"],
    }

    lh_conf = float(lighthouse.get("confidence") or 0.0)
    sections["performance"] = {
        "confidence": round(_clamp(lh_conf if lighthouse.get("available") else 0.3), 2),
        "source": lighthouse.get("source", "unavailable"),
        "categories": lighthouse.get("categories"),
    }

    vis_conf = 0.85 if visual.get("capture_ok") and visual.get("vision_analysis") else (
        0.7 if visual.get("capture_ok") else 0.35
    )
    sections["visual_ux"] = {
        "confidence": round(_clamp(vis_conf), 2),
        "vision_verified": bool(visual.get("vision_analysis")),
        "screenshot_captured": bool(visual.get("screenshot_base64")),
    }

    sections["competitor_benchmark"] = {
        "confidence": round(_clamp(
            0.8 if (state.get("competitor_report") or {}).get("benchmark_metrics") else 0.5
        ), 2),
    }

    for agent_key in ("aeo", "ux", "psychology", "competitor"):
        report = state.get(f"{agent_key}_report") or {}
        score = report.get(f"overall_{agent_key}_score") or report.get("overall_score")
        base = 0.7 if score is not None else 0.5
        if agent_key == "competitor" and report.get("skipped"):
            base = 0.0
        sections[agent_key] = {
            "confidence": round(_clamp(base * min(scrape_conf, ext_overall + 0.1)), 2),
            "score_available": score is not None,
        }

    overall = round(
        sum(s["confidence"] for s in sections.values()) / max(len(sections), 1), 2
    )
    return {
        "section_confidence": sections,
        "overall_confidence": overall,
        "capture_method": method,
        "browser_first": is_browser,
    }
