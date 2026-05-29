"""
Standardized evidence payloads for every audit check (SEO, AEO, UX, Psychology, Competitor).

Rule: a finding is only emitted when evidence exists (has_evidence=True).
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable

from app.agents.state import state_dict
from app.core.evidence.check_registry import (
    ALL_CHECK_IDS,
    _ctx_from_state,
    resolve_check_value,
)
from app.core.extraction.schema_graph import parse_schema_graph

_LIFESTYLE_HINTS = re.compile(
    r"lifestyle|model|wearing|in.?use|on.?body|styled|outfit|scene|context|"
    r"hero.?shot|environment|real.?life|in.?action",
    re.I,
)
_PACKSHOT_HINTS = re.compile(
    r"packshot|product.?only|white.?background|studio|flat.?lay|front.?view|"
    r"side.?view|detail|closeup|thumbnail|gallery",
    re.I,
)
_FAQ_QUESTION = re.compile(
    r"<(?:summary|dt|button|h[3-5])[^>]*>([^<]{5,200}\?)[^<]*<",
    re.I,
)
_REVIEW_PROVIDER = re.compile(
    r"(yotpo|judge\.?me|loox|stamped|okendo|reviews?\.io|trustpilot|"
    r"shopify.?product.?reviews|spr|bazaarvoice|power.?reviews)",
    re.I,
)


def _clip(text: str | None, n: int = 240) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _evidence(
    *,
    ev_type: str,
    source: str,
    confidence: float,
    detection_method: str,
    extracted_text: str | None = None,
    bound_key: str | None = None,
    highlight_region: str | None = None,
    visual_metrics: dict[str, Any] | None = None,
    items: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "type": ev_type,
        "source": source,
        "confidence": round(float(confidence or 0), 2),
        "detection_method": detection_method,
        "extracted_text": extracted_text,
        "bound_key": bound_key,
        "highlight_region": highlight_region,
        "visual_metrics": visual_metrics or {},
        "items": items or [],
    }


def _finding(
    check_id: str,
    *,
    passed: bool,
    finding: str,
    explanation: str,
    fix_recommendation: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "finding": finding,
        "explanation": explanation,
        "fix_recommendation": fix_recommendation,
        "has_evidence": True,
        "evidence": evidence,
    }


def _classify_gallery_images(html: str, structured: dict[str, Any]) -> dict[str, Any]:
    urls = list(structured.get("image_urls") or [])
    if not urls and html:
        for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
            src = m.group(1)
            if src.startswith("data:") or "icon" in src.lower() or "logo" in src.lower():
                continue
            urls.append(src)
    packshot = lifestyle = unknown = 0
    samples: list[str] = []
    for url in urls[:24]:
        alt_m = re.search(
            rf'src=["\']{re.escape(url)}["\'][^>]*alt=["\']([^"\']*)["\']|'
            rf'alt=["\']([^"\']*)["\'][^>]*src=["\']{re.escape(url)}["\']',
            html or "",
            re.I,
        )
        alt = (alt_m.group(1) or alt_m.group(2) or "") if alt_m else ""
        blob = f"{url} {alt}".lower()
        if _LIFESTYLE_HINTS.search(blob):
            lifestyle += 1
            samples.append(f"Lifestyle: {alt or url.split('/')[-1][:40]}")
        elif _PACKSHOT_HINTS.search(blob):
            packshot += 1
            samples.append(f"Packshot: {alt or url.split('/')[-1][:40]}")
        else:
            unknown += 1
    total = len(urls)
    return {
        "total": total,
        "packshot": packshot,
        "lifestyle": lifestyle,
        "unknown": unknown,
        "samples": samples[:6],
    }


def _extract_faq_questions(html: str, schema_graph: dict[str, Any]) -> list[str]:
    questions: list[str] = []
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html or "",
        re.I,
    ):
        try:
            import json

            data = json.loads(unescape(block.strip()))
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("@type", "")).lower() != "faqpage":
                continue
            entities = node.get("mainEntity") or []
            if isinstance(entities, dict):
                entities = [entities]
            for ent in entities:
                if isinstance(ent, dict):
                    q = ent.get("name") or ent.get("headline")
                    if q:
                        questions.append(_clip(str(q), 160))
    if not questions and html:
        for m in _FAQ_QUESTION.finditer(html):
            questions.append(_clip(m.group(1).strip(), 160))
    seen: set[str] = set()
    out: list[str] = []
    for q in questions:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out[:12]


def _schema_types(schema_graph: dict[str, Any]) -> list[str]:
    return list(schema_graph.get("detected_types") or [])


def _build_cta_found(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    cta = ctx["ux"].get("cta_analysis") or {}
    ctas = ctx["ux_facts"].get("cta_candidates") or []
    items = [
        {"label": "CTA detected", "value": "Yes" if passed else "No"},
        {"label": "CTA count", "value": str(ctx["ux_facts"].get("cta_count") or 0)},
    ]
    if ctas:
        items.append({"label": "Sample CTA", "value": ctas[0]})
    ev = _evidence(
        ev_type="textual",
        source="ux_preprocessor.cta_candidates",
        confidence=0.88,
        detection_method="Regex scan for buy/add-to-cart CTA phrases in visible text",
        items=items,
        extracted_text=f"Primary CTA {'found' if passed else 'not found'}; candidates: {', '.join(ctas[:3]) or 'none'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Primary CTA found on page" if passed else "No primary CTA detected",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add a clear Add to Cart or Buy Now button above the fold.",
        evidence=ev,
    )


def _build_trust_rating(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    structured = ctx["structured"]
    rating = structured.get("avg_rating")
    items = [
        {"label": "Rating visible", "value": "Yes" if passed else "No"},
        {"label": "Average rating", "value": str(rating) if rating is not None else "Not detected"},
        {"label": "Review count", "value": str(structured.get("review_count") or "Not detected")},
    ]
    ev = _evidence(
        ev_type="textual",
        source="json_structured_data.avg_rating",
        confidence=0.85 if rating is not None else 0.6,
        detection_method="Structured extraction + visible rating widget scan",
        items=items,
        extracted_text=f"Rating visible: {passed}; avg={rating or 'n/a'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Star rating visible" if passed else "No star rating visible on page",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Display average star rating near the product title.",
        evidence=ev,
    )


def _build_schema_breadcrumb(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    types = _schema_types(ctx["schema_graph"])
    items = [{"label": "Schema types", "value": ", ".join(types) or "None"}]
    if passed:
        items.append({"label": "BreadcrumbList", "value": "present"})
    ev = _evidence(
        ev_type="textual",
        source="schema_graph.parse",
        confidence=0.92 if passed else 0.9,
        detection_method="JSON-LD graph parser — BreadcrumbList node",
        items=items,
        extracted_text=f"BreadcrumbList schema: {'present' if passed else 'absent'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Breadcrumb schema present" if passed else "Breadcrumb schema missing",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add BreadcrumbList JSON-LD for navigation rich results.",
        evidence=ev,
    )


def _build_cta_above_fold(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    visual = ctx["visual"]
    bounds = (visual.get("element_bounds") or {}).get("cta") or {}
    vh = float(visual.get("viewport_height") or 900)
    cta_y = float(bounds.get("y") or 0)
    cta_h = float(bounds.get("height") or 0)
    cta_bottom = cta_y + cta_h
    distance = max(0, cta_y - vh) if cta_y > vh else 0
    above = visual.get("cta_above_fold")
    if above is None:
        above = passed
    items = [
        {"label": "CTA above fold", "value": "Yes" if above else "No"},
        {"label": "Viewport height", "value": f"{int(vh)}px"},
        {"label": "CTA top position", "value": f"{int(cta_y)}px" if bounds else "Not measured"},
        {"label": "Distance below fold", "value": f"{int(distance)}px" if distance else "0px (in viewport)"},
    ]
    ev = _evidence(
        ev_type="visual" if bounds else "detection",
        source="browser_capture.element_bounds",
        confidence=0.92 if visual.get("capture_ok") else 0.65,
        detection_method="Playwright getBoundingClientRect vs viewport height",
        bound_key="cta",
        highlight_region="Primary buy button / CTA",
        visual_metrics={
            "fold_line_y": vh,
            "cta_y": cta_y,
            "cta_bottom": cta_bottom,
            "distance_from_viewport_px": distance,
        },
        items=items,
        extracted_text=f"CTA {'visible without scrolling' if above else f'below fold by {int(distance)}px'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Primary CTA visible above the fold" if passed else "Primary CTA is below the fold",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Move Add to Cart / Buy Now into the hero so it appears without scrolling on desktop.",
        evidence=ev,
    )


def _build_trust_reviews(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    structured = ctx["structured"]
    pdp = ctx["pdp"]
    html = ctx["html"]
    provider = _REVIEW_PROVIDER.search(html or "")
    provider_name = provider.group(1) if provider else "DOM text scan"
    review_count = structured.get("review_count")
    rating = structured.get("avg_rating")
    items = [
        {"label": "Review provider", "value": provider_name},
        {"label": "Review count", "value": str(review_count) if review_count is not None else "Not detected"},
        {"label": "Average rating", "value": str(rating) if rating is not None else "Not visible"},
        {"label": "Reviews section", "value": "Present" if passed else "Missing"},
    ]
    conf = float(structured.get("reviews_confidence") or pdp.get("trust_badges_confidence", {}).get("confidence") or 0.75)
    ev = _evidence(
        ev_type="visual" if (ctx["visual"].get("element_bounds") or {}).get("trust") else "textual",
        source="structured_data + dom.review_widget",
        confidence=conf,
        detection_method="Schema AggregateRating + review widget pattern match",
        bound_key="trust" if (ctx["visual"].get("element_bounds") or {}).get("trust") else None,
        highlight_region="Reviews & ratings strip",
        items=items,
        extracted_text=f"Provider: {provider_name}; Count: {review_count or 'n/a'}; Rating: {rating or 'n/a'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Customer reviews detected" if passed else "No review signals detected on page",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add a review widget (Yotpo, Judge.me) and expose star rating near the product title.",
        evidence=ev,
    )


def _build_trust_badges(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    pdp = ctx["pdp"]
    badges = list(pdp.get("trust_badges") or ctx["ux_facts"].get("trust_badges") or [])
    conf_meta = pdp.get("trust_badges_confidence") or {}
    items = [{"label": f"Badge {i + 1}", "value": b} for i, b in enumerate(badges[:8])]
    if not items:
        items = [{"label": "Trust badges", "value": "None detected"}]
    ev = _evidence(
        ev_type="visual" if badges and (ctx["visual"].get("element_bounds") or {}).get("trust") else "textual",
        source=conf_meta.get("source") or "pdp_signals.trust_badges",
        confidence=float(conf_meta.get("confidence") or 0.8),
        detection_method="Trust ontology match on img alt, SVG labels, and visible text",
        bound_key="trust" if (ctx["visual"].get("element_bounds") or {}).get("trust") else None,
        highlight_region="Trust badges & certifications",
        items=items,
        extracted_text="; ".join(badges[:5]) if badges else "No certification or security badges found",
    )
    label = {
        "trust_security": "Security / payment trust badges",
        "trust_moneyback": "Money-back guarantee",
        "trust_return": "Return policy visibility",
    }.get(check_id, "Trust signals")
    return _finding(
        check_id,
        passed=passed,
        finding=f"{label}: {'detected' if passed else 'not detected'}",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Surface return policy, payment security icons, and guarantee copy near the buy button.",
        evidence=ev,
    )


def _build_faq(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    pdp = ctx["pdp"]
    faq_conf = pdp.get("faq_count_confidence") or {}
    count = int(pdp.get("faq_count") or 0)
    questions = _extract_faq_questions(ctx["html"], ctx["schema_graph"])
    items = [{"label": "FAQ count", "value": str(count)}]
    items.extend({"label": f"Q{i + 1}", "value": q} for i, q in enumerate(questions[:6]))
    ev = _evidence(
        ev_type="visual" if questions and (ctx["visual"].get("element_bounds") or {}).get("faq") else "textual",
        source=faq_conf.get("source") or "pdp_signals.faq",
        confidence=float(faq_conf.get("confidence") or 0.85),
        detection_method="FAQPage schema + FAQ section accordion scan",
        bound_key="faq" if (ctx["visual"].get("element_bounds") or {}).get("faq") else None,
        highlight_region="FAQ accordion section",
        items=items,
        extracted_text="; ".join(questions[:4]) if questions else f"{count} FAQ items detected",
    )
    if check_id == "faq_schema":
        types = _schema_types(ctx["schema_graph"])
        has = "FAQPage" in types
        ev = _evidence(
            ev_type="textual",
            source="schema_graph.parse",
            confidence=0.95 if has else 0.9,
            detection_method="JSON-LD @type inventory",
            items=[{"label": "Schema types", "value": ", ".join(types) or "None"}],
            extracted_text=f"FAQPage schema: {'present' if has else 'absent'}",
        )
    return _finding(
        check_id,
        passed=passed,
        finding="FAQ content ready for AI/search" if passed else "FAQ missing or weak",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add 5+ conversational Q&A pairs and FAQPage JSON-LD schema.",
        evidence=ev,
    )


def _build_schema_product(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    sg = ctx["schema_graph"]
    types = _schema_types(sg)
    items = [{"label": t, "value": "present"} for t in types] or [{"label": "Schema types", "value": "None detected"}]
    ev = _evidence(
        ev_type="textual",
        source="schema_graph.parse",
        confidence=float((sg.get("schemas") or {}).get("Product", {}).get("confidence") or 0.92),
        detection_method="JSON-LD graph parser — Product node validation",
        items=items,
        extracted_text=f"Detected types: {', '.join(types) if types else 'none'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding="Product schema present" if passed else "Product schema missing or incomplete",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add Product JSON-LD with name, price, availability, image, brand, and aggregateRating.",
        evidence=ev,
    )


def _build_img_lifestyle(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    gallery = _classify_gallery_images(ctx["html"], ctx["structured"])
    items = [
        {"label": "Gallery images", "value": str(gallery["total"])},
        {"label": "Packshot", "value": str(gallery["packshot"])},
        {"label": "Lifestyle", "value": str(gallery["lifestyle"])},
        {"label": "Unclassified", "value": str(gallery["unknown"])},
    ]
    items.extend({"label": "Sample", "value": s} for s in gallery["samples"][:4])
    ev = _evidence(
        ev_type="detection",
        source="dom.image_gallery_classifier",
        confidence=0.78,
        detection_method="URL/alt keyword classification (packshot vs lifestyle)",
        highlight_region="Product image gallery",
        visual_metrics={"packshot": gallery["packshot"], "lifestyle": gallery["lifestyle"], "total": gallery["total"]},
        items=items,
        extracted_text=f"Packshot: {gallery['packshot']}, Lifestyle: {gallery['lifestyle']}, Total: {gallery['total']}",
    )
    labels = {
        "img_lifestyle": "Lifestyle images in gallery",
        "img_angles": "Multiple product angles",
        "img_video": "Product video",
        "img_zoom": "Image zoom capability",
    }
    return _finding(
        check_id,
        passed=passed,
        finding=f"{labels.get(check_id, check_id)}: {'yes' if passed else 'no'}",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="Add lifestyle shots showing product in use alongside packshots.",
        evidence=ev,
    )


def _build_textual_dom(
    check_id: str,
    passed: bool,
    ctx: dict[str, Any],
    *,
    field_label: str,
    extracted: str,
    source: str,
    confidence: float,
    method: str,
    fix: str,
    bound_key: str | None = None,
) -> dict[str, Any]:
    ev = _evidence(
        ev_type="visual" if bound_key and (ctx["visual"].get("element_bounds") or {}).get(bound_key) else "textual",
        source=source,
        confidence=confidence,
        detection_method=method,
        extracted_text=extracted,
        bound_key=bound_key,
        highlight_region=field_label,
        items=[{"label": field_label, "value": _clip(extracted, 200) or "Not found"}],
    )
    return _finding(
        check_id,
        passed=passed,
        finding=f"{field_label}: {'pass' if passed else 'fail'}",
        explanation=extracted or "Not detected in scraped HTML",
        fix_recommendation=fix,
        evidence=ev,
    )


def _build_generic(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any]:
    """Fallback detection evidence — never empty."""
    seo = ctx["seo"]
    aeo = ctx["aeo"]
    ux = ctx["ux"]
    psych = ctx["psych"]
    blob = {
        "seo_score": seo.get("overall_seo_score"),
        "aeo_score": aeo.get("ai_visibility_score"),
        "ux_score": ux.get("conversion_score"),
        "psych_score": psych.get("overall_psychology_score"),
        "page_type": ux.get("page_type"),
    }
    items = [{"label": k.replace("_", " ").title(), "value": str(v)} for k, v in blob.items() if v is not None]
    ev = _evidence(
        ev_type="detection",
        source="agent_report.heuristic",
        confidence=0.6,
        detection_method="Derived from agent report boolean + preprocessor facts",
        items=items or [{"label": "Check", "value": check_id}],
        extracted_text=f"Automated audit flag: {'pass' if passed else 'fail'}",
    )
    return _finding(
        check_id,
        passed=passed,
        finding=f"Check {check_id}: {'pass' if passed else 'needs attention'}",
        explanation=ev["extracted_text"] or "",
        fix_recommendation="See AutoFix tab for recommended copy and schema snippets.",
        evidence=ev,
    )


_BUILDERS: dict[str, Callable[[str, bool, dict[str, Any]], dict[str, Any]]] = {
    "cta_above_fold": _build_cta_above_fold,
    "cta_found": _build_cta_found,
    "trust_reviews": _build_trust_reviews,
    "trust_rating": _build_trust_rating,
    "trust_security": _build_trust_badges,
    "trust_moneyback": _build_trust_badges,
    "trust_return": _build_trust_badges,
    "faq_schema": _build_faq,
    "faq_conversational": _build_faq,
    "schema_product": _build_schema_product,
    "schema_breadcrumb": _build_schema_breadcrumb,
    "schema_review": _build_schema_product,
    "img_lifestyle": _build_img_lifestyle,
    "img_angles": _build_img_lifestyle,
    "img_video": _build_img_lifestyle,
    "img_zoom": _build_img_lifestyle,
}


def _build_seo_text_checks(check_id: str, passed: bool, ctx: dict[str, Any]) -> dict[str, Any] | None:
    seo = ctx["seo"]
    dom = ctx["dom"]
    fixes = {
        "kw_in_h1": ("H1 headline", seo.get("h1", {}).get("value"), "seo_report.h1", 0.88, "DOM h1 extraction", "Include primary keyword in the single H1.", "h1"),
        "kw_in_title": ("Page title", dom.get("title_tag") or seo.get("title_tag", {}).get("value"), "dom.title_tag", 0.9, "HTML title tag parse", "Put brand + keyword in <title>.", None),
        "kw_in_meta": ("Meta description", dom.get("meta_description") or seo.get("meta_description", {}).get("value"), "dom.meta_description", 0.88, "Meta description parse", "Write 150–160 char meta with keyword.", None),
        "tech_canonical": ("Canonical URL", "Present" if passed else "Missing", "dom.canonical", 0.92, "link[rel=canonical] scan", "Add canonical link in <head>.", None),
        "tech_og": ("Open Graph tags", "Present" if passed else "Missing", "dom.open_graph", 0.9, "og:* meta scan", "Add og:title, og:description, og:image.", None),
    }
    if check_id not in fixes:
        return None
    label, extracted, source, conf, method, fix, bound = fixes[check_id]
    return _build_textual_dom(check_id, passed, ctx, field_label=label, extracted=str(extracted or ""), source=source, confidence=conf, method=method, fix=fix, bound_key=bound)


def build_check_evidence(check_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
    ctx = _ctx_from_state(state)
    passed = resolve_check_value(check_id, ctx)
    if passed is None:
        return None
    payload = None
    if check_id in _BUILDERS:
        payload = _BUILDERS[check_id](check_id, passed, ctx)
    else:
        text = _build_seo_text_checks(check_id, passed, ctx)
        payload = text or _build_generic(check_id, passed, ctx)
    if payload:
        payload["status"] = "pass" if passed else "fail"
    return payload


def build_competitor_evidence(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    comp = state_dict(state, "competitor_report")
    lc = comp.get("live_compare") or {}
    sites = lc.get("sites") or []
    rows = lc.get("rows") or []
    out: dict[str, dict[str, Any]] = {}
    you = sites[0] if sites else {}
    you_name = you.get("name") or "You"
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        check_id = f"competitor_{key}"
        values = row.get("values") or []
        you_val = values[0] if values else None
        best_i = row.get("best_index", 0)
        you_win = bool(row.get("you_win"))
        passed = you_win
        best_name = sites[best_i].get("name") if best_i < len(sites) else "Competitor"
        items = []
        for i, site in enumerate(sites):
            if not site.get("scrape_ok") and site.get("role") != "you":
                continue
            v = values[i] if i < len(values) else None
            items.append({
                "label": site.get("name") or f"Site {i + 1}",
                "value": str(v) if v is not None else "n/a",
            })
        ev = _evidence(
            ev_type="detection",
            source="competitor_agent.live_scrape",
            confidence=0.85 if you.get("scrape_ok") else 0.55,
            detection_method="Side-by-side live HTML feature extraction per URL",
            items=items,
            extracted_text=f"You ({you_name}): {you_val}; Best: {best_name} ({values[best_i] if best_i < len(values) else 'n/a'})",
        )
        out[check_id] = _finding(
            check_id,
            passed=passed,
            finding=f"{row.get('label')}: {'you lead' if passed else 'competitor leads'}",
            explanation=ev["extracted_text"] or "",
            fix_recommendation=f"Close the gap on {row.get('label')} — benchmark against {best_name}.",
            evidence=ev,
        )
    return out


def build_audit_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Map check_id -> evidence payload. Only includes checks with resolvable status."""
    evidence: dict[str, Any] = {}
    for check_id in ALL_CHECK_IDS:
        payload = build_check_evidence(check_id, state)
        if payload and payload.get("has_evidence"):
            evidence[check_id] = payload
    evidence.update(build_competitor_evidence(state))
    return evidence
