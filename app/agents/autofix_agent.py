"""
app/agents/autofix_agent.py

AutoFixAgent — focused SEO/AEO fixes (slim prompt, compact inputs).
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.competitor_discovery import resolve_homepage_mode
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("autofix")

_SYSTEM_PROMPT = """
You are a senior e-commerce SEO/AEO specialist.
Given audit issues and product facts, return ONLY valid JSON (no markdown fences).

Do NOT generate FAQs, social captions, email copy, or AB test variants.

{
  "fixed_title_tag": string,
  "fixed_meta_description": string,
  "fixed_h1": string,
  "suggested_h2s": [string],
  "rewritten_product_description": string,
  "ai_optimized_description": string,
  "schema_markup_snippet": string,
  "open_graph_tags": {"og_title": string, "og_description": string, "og_type": string},
  "keyword_strategy": {
    "primary": string,
    "secondary": [string],
    "lsi_keywords": [string],
    "ai_query_keywords": [string]
  },
  "priority_action_plan": [
    {"priority": "high|medium|low", "action": string, "expected_impact": string}
  ],
  "estimated_seo_score_improvement": float,
  "estimated_ai_visibility_improvement": float
}
""".strip()


def _fallback_autofix(seo_report: dict, dom_facts: dict, structured: dict) -> dict:
    title = (seo_report.get("title_tag") or {}).get("value") or dom_facts.get("title_tag") or ""
    meta = (seo_report.get("meta_description") or {}).get("value") or dom_facts.get("meta_description") or ""
    h1 = (seo_report.get("h1") or {}).get("value") or structured.get("product_name") or ""
    fixes: dict = {
        "fixed_title_tag": title[:60] if title else None,
        "fixed_meta_description": meta[:160] if meta else None,
        "fixed_h1": h1[:120] if h1 else None,
        "suggested_h2s": [],
        "priority_action_plan": [],
    }
    for issue in (seo_report.get("top_issues") or [])[:5]:
        fixes["priority_action_plan"].append(
            {"priority": "high", "action": issue, "expected_impact": "Improves search visibility"}
        )
    for win in (seo_report.get("quick_wins") or [])[:3]:
        if win not in [p["action"] for p in fixes["priority_action_plan"]]:
            fixes["priority_action_plan"].append(
                {"priority": "medium", "action": win, "expected_impact": "Quick SEO improvement"}
            )
    brand = structured.get("brand") or ""
    if brand and title:
        fixes["open_graph_tags"] = {
            "og_title": title[:70],
            "og_description": (meta or title)[:200],
            "og_type": "website",
        }
    return {k: v for k, v in fixes.items() if v is not None}


def _merge_autofix(primary: dict, fallback: dict) -> dict:
    out = dict(fallback)
    for key, val in primary.items():
        if val is None or val == "" or val == []:
            continue
        out[key] = val
    return out


async def autofix_agent(state: AgentState) -> AgentState:
    seo_report = state_dict(state, "seo_report")
    if not seo_report:
        return {"errors": ["autofix_agent: no seo_report"]}

    aeo_report = state_dict(state, "aeo_report")
    diagnosis = state_dict(state, "final_diagnosis")
    structured = state_dict(state, "json_structured_data")
    dom_facts = state_dict(state, "dom_technical_seo")
    page_url = state.get("url") or ""
    homepage_mode = resolve_homepage_mode(page_url, state.get("compare_as"))
    fallback = _fallback_autofix(seo_report, dom_facts, structured)

    logger.info("autofix_agent.start", model=_MODEL)
    t0 = time.monotonic()

    page_type_note = (
        "Page type: HOMEPAGE — WebSite/Organization schema, hero CTAs.\n"
        if homepage_mode
        else ""
    )

    user_message = f"""
{page_type_note}
DOM facts: {json.dumps(dom_facts, separators=(',', ':'))}
Product: {json.dumps({k: structured.get(k) for k in ('product_name', 'brand', 'description', 'price', 'features')}, separators=(',', ':'))}
SEO top_issues: {json.dumps(seo_report.get('top_issues', [])[:6])}
SEO quick_wins: {json.dumps(seo_report.get('quick_wins', [])[:4])}
AEO gaps: {json.dumps((aeo_report.get('gaps') or [])[:4])}
Priority actions: {json.dumps((diagnosis.get('quick_wins') or [])[:4])}
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    autofix_report, parse_err = safe_json_parse_report(raw, "autofix_agent")
    if parse_err:
        logger.warning("autofix_agent.parse_fallback", error=parse_err)
        autofix_report = fallback
    else:
        autofix_report = _merge_autofix(autofix_report, fallback)

    if not (
        autofix_report.get("fixed_title_tag")
        or autofix_report.get("fixed_meta_description")
        or autofix_report.get("fixed_h1")
    ):
        autofix_report = _merge_autofix(fallback, autofix_report)

    logger.info("autofix_agent.done", actions=len(autofix_report.get("priority_action_plan", [])), duration_ms=duration_ms)

    return {
        "autofix_report": autofix_report,
        "agent_reports": [
            {
                "agent": "autofix_agent",
                "model": _MODEL,
                "output": autofix_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
