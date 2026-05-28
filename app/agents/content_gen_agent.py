"""
app/agents/content_gen_agent.py

Lazy by default: core copy from structured + autofix only.
Full generation (FAQs, social, email, AB tests) via generate_full_content() on demand.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("autofix")

_LAZY_SECTIONS = (
    "faqs",
    "social_captions",
    "email_marketing",
    "ab_test_variants",
    "push_notification_copy",
    "implementation_checklist",
)

_CORE_SYSTEM = """
You are an e-commerce copywriter. Return ONLY valid JSON (no markdown fences).

Generate ONLY the sections requested in the user message.
Keep outputs concise and copy-paste ready.
""".strip()

_SECTION_SCHEMAS: dict[str, str] = {
    "faqs": '"faqs": [{"question": string, "answer": string}]',
    "social_captions": '"social_captions": {"instagram": string, "whatsapp": string, "twitter": string, "linkedin": string}',
    "email_marketing": '"email_marketing": {"subject_lines": [string], "preview_text": string, "hero_copy": string}',
    "ab_test_variants": '"ab_test_variants": {"title_variant_b": string, "cta_variant_a": string, "cta_variant_b": string, "description_variant_b": string}',
    "push_notification_copy": '"push_notification_copy": {"title": string, "body": string}',
    "core_copy": """
"product_description": string,
"ai_optimized_description": string,
"meta_title": string,
"meta_description": string,
"bullet_points": [string],
"suggested_h2s": [string]
""".strip(),
}


def build_lazy_generated_content(
    structured: dict[str, Any],
    seo_report: dict[str, Any],
    autofix_report: dict[str, Any],
) -> dict[str, Any]:
    """Minimal content shell — no LLM. Preserves frontend tab compatibility."""
    title = (
        autofix_report.get("fixed_title_tag")
        or (seo_report.get("title_tag") or {}).get("value")
        or structured.get("product_name")
        or ""
    )
    meta = (
        autofix_report.get("fixed_meta_description")
        or (seo_report.get("meta_description") or {}).get("value")
        or ""
    )
    desc = structured.get("description") or autofix_report.get("rewritten_product_description") or ""
    return {
        "_lazy": True,
        "_lazy_sections": list(_LAZY_SECTIONS),
        "product_description": desc[:4000] if desc else "",
        "ai_optimized_description": autofix_report.get("ai_optimized_description") or "",
        "brand_story_snippet": "",
        "faqs": [],
        "meta_title": title[:70] if title else "",
        "meta_description": meta[:160] if meta else "",
        "open_graph_title": title[:70] if title else "",
        "open_graph_description": meta[:200] if meta else "",
        "schema_markup": autofix_report.get("schema_markup_snippet") or "",
        "faq_schema": "",
        "social_captions": {},
        "email_marketing": None,
        "push_notification_copy": None,
        "suggested_h2s": autofix_report.get("suggested_h2s") or [],
        "bullet_points": structured.get("features") or [],
        "size_guide_copy": None,
        "keyword_strategy": autofix_report.get("keyword_strategy") or {},
        "ab_test_variants": {},
    }


async def generate_full_content(
    *,
    structured: dict[str, Any],
    seo_report: dict[str, Any],
    aeo_report: dict[str, Any],
    diagnosis: dict[str, Any],
    autofix_report: dict[str, Any],
    existing: dict[str, Any] | None = None,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    """
    On-demand LLM generation for lazy sections.
    sections: subset of _LAZY_SECTIONS + 'core_copy', or None for all lazy sections.
    """
    base = dict(existing or build_lazy_generated_content(structured, seo_report, autofix_report))
    if base.get("_lazy") is False:
        return base

    want = sections or list(_LAZY_SECTIONS)
    if "all" in want:
        want = list(_LAZY_SECTIONS) + ["core_copy"]

    schema_parts = [_SECTION_SCHEMAS[s] for s in want if s in _SECTION_SCHEMAS]
    if not schema_parts:
        return base

    user_message = f"""
Product:
{json.dumps(structured, separators=(',', ':'))[:2500]}

SEO issues: {(seo_report.get('top_issues') or [])[:5]}
AEO gaps: {(aeo_report.get('gaps') or [])[:5]}
Quick wins: {(diagnosis.get('quick_wins') or [])[:5]}

Generate JSON with ONLY these keys:
{{{', '.join(schema_parts)}}}
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=3500,
        system=_CORE_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    generated, parse_err = safe_json_parse_report(response.content[0].text.strip(), "content_gen_full")
    if parse_err:
        raise ValueError(parse_err)

    for key, val in generated.items():
        if val is not None and val != "" and val != []:
            base[key] = val

    def _filled(section: str) -> bool:
        if section == "faqs":
            return bool(base.get("faqs"))
        if section == "social_captions":
            return bool(base.get("social_captions"))
        if section == "email_marketing":
            return bool(base.get("email_marketing"))
        if section == "ab_test_variants":
            return bool(base.get("ab_test_variants"))
        if section == "push_notification_copy":
            return bool(base.get("push_notification_copy"))
        return True

    remaining = [s for s in _LAZY_SECTIONS if not _filled(s)]
    base["_lazy_sections"] = remaining
    base["_lazy"] = bool(remaining)

    return base


async def content_gen_agent(state: AgentState) -> AgentState:
    """Pipeline step: lazy placeholder only (no LLM)."""
    structured = state_dict(state, "json_structured_data")
    if not structured:
        return {"errors": ["content_gen_agent: no json_structured_data"]}

    seo = state_dict(state, "seo_report")
    autofix = state_dict(state, "autofix_report")

    t0 = time.monotonic()
    generated_content = build_lazy_generated_content(structured, seo, autofix)
    duration_ms = int((time.monotonic() - t0) * 1000)

    logger.info("content_gen_agent.done", lazy=True, duration_ms=duration_ms)

    return {
        "generated_content": generated_content,
        "status": "completed",
        "agent_reports": [
            {
                "agent": "content_gen_agent",
                "model": "lazy_placeholder",
                "output": {"_lazy": True, "sections_deferred": list(_LAZY_SECTIONS)},
                "duration_ms": duration_ms,
            }
        ],
    }
