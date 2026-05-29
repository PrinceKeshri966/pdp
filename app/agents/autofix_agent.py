"""
AutoFixAgent — deterministic fix generators first; LLM only when plan allows.
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger
from app.fix_generators import generate_deployable_fixes
from app.validators.autofix_validator import validate_autofix_report

logger = get_logger(__name__)

_MODEL = get_model("seo")  # Haiku for optional polish


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

    plan = state_dict(state, "agent_plan")
    aeo_report = state_dict(state, "aeo_report")
    structured = state_dict(state, "json_structured_data")
    dom_facts = state_dict(state, "dom_technical_seo")
    page_url = state.get("url") or ""
    page_type = state_dict(state, "page_type_info").get("page_type") or "unknown"

    t0 = time.monotonic()
    fallback = _fallback_autofix(seo_report, dom_facts, structured)
    deployable = generate_deployable_fixes(
        url=page_url,
        page_type=page_type,
        seo_report=seo_report,
        dom_facts=dom_facts,
        structured=structured,
        aeo_report=aeo_report,
    )
    autofix_report: dict = {
        **fallback,
        "deployable_fixes": deployable,
        "_generated_by": "fix_generators",
    }

    if plan.get("run_autofix_llm", True) and (state.get("audit_depth") or "") == "deep":
        logger.info("autofix_agent.llm_polish", model=_MODEL)
        user_message = json.dumps(
            {
                "title": fallback.get("fixed_title_tag"),
                "meta": fallback.get("fixed_meta_description"),
                "top_issues": (seo_report.get("top_issues") or [])[:4],
            },
            separators=(",", ":"),
        )
        try:
            response = await claude.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system="Return JSON: fixed_title_tag, fixed_meta_description, fixed_h1, keyword_strategy only.",
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()
            llm_fix, parse_err = safe_json_parse_report(raw, "autofix_agent")
            if not parse_err and llm_fix:
                autofix_report = _merge_autofix(llm_fix, autofix_report)
                autofix_report["_generated_by"] = "fix_generators+haiku"
        except Exception as exc:
            logger.warning("autofix_agent.llm_skip", error=str(exc))

    autofix_report = validate_autofix_report(
        autofix_report,
        seo_report=seo_report,
        dom_facts=dom_facts,
        structured=structured,
        page_type=page_type,
        url=page_url,
    )

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "autofix_agent.done",
        fixes=len(autofix_report.get("deployable_fixes") or []),
        valid=autofix_report.get("_autofix_validation", {}).get("valid_count"),
        source=autofix_report.get("_generated_by"),
        duration_ms=duration_ms,
    )

    return {
        "autofix_report": autofix_report,
        "agent_reports": [
            {
                "agent": "autofix_agent",
                "model": autofix_report.get("_generated_by", "template"),
                "output": autofix_report,
                "duration_ms": duration_ms,
            }
        ],
    }
