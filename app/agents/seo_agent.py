"""
app/agents/seo_agent.py

SEOAgent — deterministic facts from seo_preprocessor; Claude for semantic reasoning only.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.agents.claude_client import claude
from app.rulesets.base import ruleset_prompt_block
from app.agents.context_router import format_context_for_llm
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.scoring_engine import apply_reliability_caps, blend_score, compute_deterministic_scores
from app.agents.seo_preprocessor import extract_seo_facts
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("seo")

_SYSTEM_PROMPT = """
You are an expert e-commerce SEO strategist. Deterministic SEO metrics are ALREADY
extracted in PRECOMPUTED_SEO_FACTS — do NOT recount headings, links, schema, word counts,
or title/meta lengths.

Your job: semantic reasoning ONLY. Return ONLY valid JSON (no markdown fences).

{
  "keyword_analysis": {
    "primary_keyword": string,
    "secondary_keywords": [string],
    "search_intent": "informational|commercial|transactional|navigational",
    "intent_gaps": [string],
    "score": float (0-10)
  },
  "semantic_content_issues": [string],
  "url_structure_issues": [string],
  "overall_seo_score": float (0-10),
  "top_issues": [string],
  "quick_wins": [string]
}
""".strip()


def _avg_section_scores(facts: dict[str, Any]) -> float:
    keys = ("title_tag", "meta_description", "h1", "headings_structure", "keyword_analysis",
            "content_quality", "image_seo", "structured_data", "links", "technical_seo")
    scores = [facts[k]["score"] for k in keys if isinstance(facts.get(k), dict) and facts[k].get("score") is not None]
    return round(sum(scores) / len(scores), 1) if scores else 5.0


def merge_seo_report(facts: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """Merge Python-extracted facts with Claude semantic layer for frontend compatibility."""
    report = {k: v for k, v in facts.items() if k != "_deterministic"}
    ka_facts = dict(report.get("keyword_analysis") or {})
    ka_llm = llm.get("keyword_analysis") or {}
    report["keyword_analysis"] = {
        **ka_facts,
        "primary_keyword": ka_llm.get("primary_keyword") or ka_facts.get("primary_keyword", ""),
        "secondary_keywords": ka_llm.get("secondary_keywords") or ka_facts.get("secondary_keywords", []),
        "density_pct": ka_facts.get("density_pct", 0),
        "in_title": ka_facts.get("in_title", False),
        "in_h1": ka_facts.get("in_h1", False),
        "in_meta_description": ka_facts.get("in_meta_description", False),
        "in_first_100_words": ka_facts.get("in_first_100_words", False),
        "search_intent": ka_llm.get("search_intent"),
        "intent_gaps": ka_llm.get("intent_gaps", []),
        "score": ka_llm.get("score") if ka_llm.get("score") is not None else ka_facts.get("score", 5.0),
    }
    url = report.setdefault("url_structure", {})
    url["issues"] = list(llm.get("url_structure_issues") or url.get("issues") or [])
    report["overall_seo_score"] = llm.get("overall_seo_score") if llm.get("overall_seo_score") is not None else _avg_section_scores(report)
    report["top_issues"] = llm.get("top_issues") or []
    for issue in llm.get("semantic_content_issues") or []:
        if issue not in report["top_issues"]:
            report["top_issues"].append(issue)
    report["quick_wins"] = llm.get("quick_wins") or []
    return report


def _apply_dom_ground_truth(seo_report: dict, dom_facts: dict) -> dict:
    if not dom_facts:
        return seo_report
    title_val = dom_facts.get("title_tag")
    if title_val:
        title_block = seo_report.setdefault("title_tag", {})
        title_block["value"] = title_val
        title_block["length"] = len(title_val)
    meta_val = dom_facts.get("meta_description")
    if meta_val is not None:
        meta_block = seo_report.setdefault("meta_description", {})
        meta_block["value"] = meta_val
        meta_block["length"] = len(meta_val)
    tech = seo_report.setdefault("technical_seo", {})
    if "canonical_present" in dom_facts:
        tech["canonical_present"] = bool(dom_facts["canonical_present"])
    if "open_graph_present" in dom_facts:
        tech["open_graph_present"] = bool(dom_facts["open_graph_present"])
    structured = seo_report.setdefault("structured_data", {})
    if dom_facts.get("product_schema_present"):
        structured["has_product_schema"] = True
        structured["detected"] = True
        types = structured.setdefault("types", [])
        if "Product" not in types:
            types.append("Product")
    if dom_facts.get("faq_schema_present"):
        structured["has_faq_schema"] = True
        structured["detected"] = True
        types = structured.setdefault("types", [])
        if "FAQPage" not in types:
            types.append("FAQPage")
    return seo_report


async def seo_agent(state: AgentState) -> AgentState:
    packages = state.get("agent_context_packages") or {}
    seo_ctx = packages.get("seo")
    if not seo_ctx:
        return {"errors": ["seo_agent: no agent_context_packages.seo"]}

    dom_facts = state_dict(state, "dom_technical_seo")
    facts = state.get("seo_preprocessor_facts") or extract_seo_facts(
        url=state.get("url") or "",
        markdown=state.get("markdown_content") or "",
        scrape_html=state.get("scrape_html") or "",
        dom_technical_seo=dom_facts,
        page_main_summary=(state.get("page_contexts") or {}).get("main"),
    )

    structured = state_dict(state, "json_structured_data")
    page_type = state_dict(state, "page_type_info").get("page_type") or state_dict(state, "scrape_validation").get("page_type") or "unknown"

    logger.info("seo_agent.start", model=_MODEL, precomputed=True)
    t0 = time.monotonic()

    user_message = (
        "PRECOMPUTED_SEO_FACTS (ground truth — do not contradict):\n"
        f"{json.dumps({k: v for k, v in facts.items() if k != '_deterministic'}, separators=(',', ':'))}\n\n"
        + ruleset_prompt_block(page_type)
        + "\n\n"
        + f"Product extractor summary:\n{json.dumps(structured, separators=(',', ':'))[:2000]}\n\n"
        + "SEO context package:\n"
        + format_context_for_llm(seo_ctx, max_chars=2500)
        + "\n\nProvide search intent, intent gaps, semantic issues, and prioritized recommendations."
    )

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=1536,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    llm_layer, parse_err = safe_json_parse_report(raw, "seo_agent")
    if parse_err:
        return {"errors": [parse_err]}

    seo_report = merge_seo_report(facts, llm_layer)
    seo_report = _apply_dom_ground_truth(seo_report, dom_facts)

    det = compute_deterministic_scores(
        seo_facts=facts,
        scrape_validation=state_dict(state, "scrape_validation"),
        extraction_confidence=state_dict(state, "extraction_confidence"),
        page_type=page_type,
        visual_ux_facts=state_dict(state, "visual_ux_facts"),
    )
    llm_overall = seo_report.get("overall_seo_score")
    blended = blend_score(det["deterministic_scores"]["seo"], llm_overall)
    seo_report["overall_seo_score"] = apply_reliability_caps(blended, dict(state))
    seo_report["score_source"] = "deterministic_blend"
    seo_report["deterministic_seo_score"] = det["deterministic_scores"]["seo"]

    logger.info("seo_agent.done", score=seo_report.get("overall_seo_score"), duration_ms=duration_ms)

    return {
        "seo_report": seo_report,
        "deterministic_scores": det,
        "agent_reports": [
            {
                "agent": "seo_agent",
                "model": _MODEL,
                "input": {"preprocessor": True, "context_package": "seo"},
                "output": seo_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
