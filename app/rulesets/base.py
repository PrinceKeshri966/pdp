"""
Shared ruleset utilities and PDP leakage guards.
"""
from __future__ import annotations

import re
from typing import Any

PDP_LEAKAGE_TERMS = [
    "size guide",
    "size chart",
    "shipping policy",
    "return policy",
    "material composition",
    "fit description",
    "variant selector",
    "add to cart",
    "sku selector",
]

_LEAKAGE_RE = re.compile("|".join(re.escape(t) for t in PDP_LEAKAGE_TERMS), re.I)


def filter_pdp_leakage(items: list[str], page_type: str) -> tuple[list[str], list[str]]:
    """Remove PDP-only recommendations on non-PDP pages. Returns (filtered, flagged)."""
    if page_type in ("pdp", "product", "marketplace"):
        return items, []
    flagged: list[str] = []
    kept: list[str] = []
    for item in items:
        if _LEAKAGE_RE.search(item or ""):
            flagged.append(item)
        else:
            kept.append(item)
    return kept, flagged


def get_ruleset(page_type: str) -> dict[str, Any]:
    from app.rulesets import blog_rules, homepage_rules, marketplace_rules, pdp_rules, saas_rules

    mapping = {
        "homepage": homepage_rules.RULESET,
        "pdp": pdp_rules.RULESET,
        "product": pdp_rules.RULESET,
        "saas_landing": saas_rules.RULESET,
        "marketplace": marketplace_rules.RULESET,
        "blog": blog_rules.RULESET,
        "category_page": homepage_rules.RULESET,
        "comparison_page": pdp_rules.RULESET,
        "local_business": homepage_rules.RULESET,
        "docs": blog_rules.RULESET,
        "unknown": homepage_rules.RULESET,
    }
    return mapping.get(page_type, homepage_rules.RULESET)


def get_ux_checklist(page_type: str) -> list[str]:
    return get_ruleset(page_type).get("ux_checks", [])


def ruleset_prompt_block(page_type: str) -> str:
    rs = get_ruleset(page_type)
    checks = ", ".join(rs.get("ux_checks", [])[:10])
    forbidden = rs.get("forbidden_topics") or []
    block = f"PAGE_TYPE={page_type}. Focus UX checks: {checks}."
    if forbidden:
        block += f" NEVER mention: {', '.join(forbidden)}."
    return block
