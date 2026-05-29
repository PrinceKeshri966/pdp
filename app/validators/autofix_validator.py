"""
Validate AutoFix before/after pairs — reject no-op and fake fixes.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from app.rulesets.base import PDP_LEAKAGE_TERMS, get_ruleset

_GENERIC_NOOP = re.compile(
    r"^(optimize|improve|enhance|update|fix)\s+(your\s+)?(page|site|seo)\b",
    re.I,
)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _similarity(a: str | None, b: str | None) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _semantic_gain(before: str, after: str) -> float:
    """Heuristic 0–1: larger = more meaningful change."""
    sim = _similarity(before, after)
    if sim >= 0.95:
        return 0.0
    bl, al = len(before or ""), len(after or "")
    length_delta = abs(al - bl) / max(bl, al, 1)
    return round(min(1.0, (1.0 - sim) * 0.7 + min(length_delta, 0.3)), 2)


def _page_type_allows_field(field: str, page_type: str) -> bool:
    pt = (page_type or "unknown").lower()
    if pt in ("pdp", "product", "marketplace"):
        return True
    if field in ("fixed_title_tag", "fixed_meta_description", "fixed_h1", "open_graph_tags"):
        return True
    if field in ("rewritten_product_description", "size_guide", "shipping"):
        return False
    return True


def _issue_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("issue") or item.get("text") or item.get("action") or item)
    return str(item)


def _field_supported_by_evidence(
    field: str,
    *,
    seo_report: dict,
    dom_facts: dict,
    structured: dict,
) -> bool:
    seo_issues = " ".join(_issue_text(i) for i in (seo_report.get("top_issues") or [])).lower()
    if field == "fixed_title_tag":
        title = (seo_report.get("title_tag") or {}).get("value") or dom_facts.get("title_tag") or ""
        return bool(title) or bool(structured.get("product_name")) or "title" in seo_issues
    if field == "fixed_meta_description":
        meta = (seo_report.get("meta_description") or {}).get("value") or dom_facts.get("meta_description") or ""
        return bool(meta) or "meta" in seo_issues or (seo_report.get("meta_description") or {}).get("length", 0) < 50
    if field == "fixed_h1":
        return bool((seo_report.get("h1") or {}).get("value")) or "h1" in seo_issues
    if field == "rewritten_product_description":
        return bool(structured.get("description")) or bool(structured.get("product_name"))
    return True


def validate_fix_pair(
    before: str | None,
    after: str | None,
    *,
    field: str = "generic",
    page_type: str = "unknown",
    seo_report: dict | None = None,
    dom_facts: dict | None = None,
    structured: dict | None = None,
) -> dict[str, Any]:
    """
    Return { valid_fix, reason, change_strength, semantic_difference }.
    """
    seo_report = seo_report or {}
    dom_facts = dom_facts or {}
    structured = structured or {}

    if not after or not str(after).strip():
        return {
            "valid_fix": False,
            "reason": "empty_after",
            "change_strength": 0.0,
            "semantic_difference": 0.0,
        }

    if not _page_type_allows_field(field, page_type):
        return {
            "valid_fix": False,
            "reason": f"irrelevant_for_page_type:{page_type}",
            "change_strength": 0.0,
            "semantic_difference": 0.0,
        }

    forbidden = get_ruleset(page_type).get("forbidden_topics") or []
    after_l = (after or "").lower()
    for term in forbidden:
        if term.lower() in after_l:
            return {
                "valid_fix": False,
                "reason": f"page_type_forbidden:{term}",
                "change_strength": 0.0,
                "semantic_difference": 0.0,
            }

    sim = _similarity(before, after)
    if _normalize(before) == _normalize(after):
        return {
            "valid_fix": False,
            "reason": "before_equals_after",
            "change_strength": 0.0,
            "semantic_difference": 0.0,
        }

    if sim > 0.95:
        return {
            "valid_fix": False,
            "reason": f"similarity_too_high:{sim:.2f}",
            "change_strength": 0.0,
            "semantic_difference": round(1.0 - sim, 2),
        }

    # Whitespace-only change
    if re.sub(r"\W+", "", before or "") == re.sub(r"\W+", "", after or ""):
        return {
            "valid_fix": False,
            "reason": "whitespace_only_change",
            "change_strength": 0.0,
            "semantic_difference": 0.0,
        }

    if _GENERIC_NOOP.search(after or ""):
        return {
            "valid_fix": False,
            "reason": "generic_noop_rewrite",
            "change_strength": 0.0,
            "semantic_difference": _semantic_gain(before or "", after or ""),
        }

    if not _field_supported_by_evidence(field, seo_report=seo_report, dom_facts=dom_facts, structured=structured):
        return {
            "valid_fix": False,
            "reason": "unsupported_by_evidence",
            "change_strength": 0.0,
            "semantic_difference": _semantic_gain(before or "", after or ""),
        }

    sem = _semantic_gain(before or "", after)
    if sem < 0.08:
        return {
            "valid_fix": False,
            "reason": "semantic_change_too_weak",
            "change_strength": sem,
            "semantic_difference": round(1.0 - sim, 2),
        }

    return {
        "valid_fix": True,
        "reason": "ok",
        "change_strength": sem,
        "semantic_difference": round(1.0 - sim, 2),
    }


def _suggest_title_fix(before: str, structured: dict, url: str) -> str | None:
    """When before is a domain placeholder, propose product-based title."""
    pn = (structured.get("product_name") or "").strip()
    brand = (structured.get("brand") or "").strip()
    if not pn:
        return None
    host = urlparse(url or "").netloc.replace("www.", "").lower()
    b_norm = _normalize(before)
    if host and (b_norm == _normalize(host) or b_norm == _normalize("www." + host) or len(before or "") < 28):
        title = f"{pn}"
        if brand and brand.lower() not in pn.lower():
            title = f"{pn} | {brand}"
        return title[:60]
    return None


def validate_autofix_report(
    autofix: dict[str, Any],
    *,
    seo_report: dict,
    dom_facts: dict,
    structured: dict,
    page_type: str,
    url: str = "",
) -> dict[str, Any]:
    """
    Validate and sanitize autofix report. Adds fix_comparisons and _valid_fixes map.
    """
    autofix = dict(autofix or {})
    comparisons: list[dict[str, Any]] = []
    valid_fixes: dict[str, bool] = {}
    suppressed: list[dict[str, Any]] = []

    pairs = [
        ("title_tag", "fixed_title_tag", (seo_report.get("title_tag") or {}).get("value") or dom_facts.get("title_tag")),
        ("meta_description", "fixed_meta_description", (seo_report.get("meta_description") or {}).get("value") or dom_facts.get("meta_description")),
        ("h1", "fixed_h1", (seo_report.get("h1") or {}).get("value") or structured.get("product_name")),
        ("description", "rewritten_product_description", structured.get("description") or ""),
    ]

    cleaned = dict(autofix)
    for label, after_key, before_val in pairs:
        after_val = autofix.get(after_key)
        if after_val is None:
            continue
        before_s = str(before_val or "")
        after_s = str(after_val or "")

        # Try to improve domain-only title before validation
        if after_key == "fixed_title_tag":
            suggested = _suggest_title_fix(before_s, structured, url)
            if suggested and _similarity(before_s, suggested) < 0.95:
                after_s = suggested
                cleaned[after_key] = suggested

        result = validate_fix_pair(
            before_s,
            after_s,
            field=after_key,
            page_type=page_type,
            seo_report=seo_report,
            dom_facts=dom_facts,
            structured=structured,
        )
        comparisons.append(
            {
                "field": label,
                "before": before_s,
                "after": after_s if result["valid_fix"] else None,
                "proposed_after": after_s,
                **result,
            }
        )
        valid_fixes[after_key] = result["valid_fix"]
        if result["valid_fix"]:
            cleaned[after_key] = after_s
        else:
            if after_key in cleaned:
                del cleaned[after_key]
            suppressed.append({"field": after_key, "reason": result["reason"], "before": before_s[:200]})

    # Deployable fixes — require non-empty code with substance
    deployable_in = autofix.get("deployable_fixes") or []
    deployable_out: list[dict] = []
    for fix in deployable_in:
        code = (fix.get("code") or "").strip()
        if len(code) < 12 or code in ('<title></title>', '""'):
            suppressed.append({"field": fix.get("fix_type"), "reason": "empty_deployable_code"})
            continue
        if _similarity(code, "") < 0.01:
            continue
        deployable_out.append(fix)
    cleaned["deployable_fixes"] = deployable_out

    # Priority actions — drop if duplicate of top_issues without new info
    plan_out = []
    for item in autofix.get("priority_action_plan") or []:
        action = (item.get("action") or "").strip()
        if not action or _GENERIC_NOOP.search(action):
            continue
        if any(_similarity(action, _issue_text(iss)) > 0.92 for iss in (seo_report.get("top_issues") or [])):
            if len(action) < 80:
                continue
        plan_out.append(item)
    cleaned["priority_action_plan"] = plan_out

    cleaned["fix_comparisons"] = comparisons
    cleaned["_valid_fixes"] = valid_fixes
    cleaned["_suppressed_fixes"] = suppressed
    cleaned["_autofix_validation"] = {
        "valid_count": sum(1 for v in valid_fixes.values() if v),
        "suppressed_count": len(suppressed),
        "has_meaningful_change": any(valid_fixes.values()) or len(deployable_out) > 0,
    }

    return cleaned
