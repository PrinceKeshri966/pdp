"""
app/agents/autofix_agent.py

AutoFixAgent  (Mode 1 – Node 3)   Model: Claude Sonnet (reasoning)
────────────────────────────────────────────────────────────────────
Receives the SEO report and the raw Markdown; produces concrete,
copy-paste-ready fixes for every identified issue.

Uses the Anthropic SDK directly (AsyncAnthropic.messages.create).
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("autofix")

_SYSTEM_PROMPT = """
You are a senior e-commerce content strategist, SEO specialist, and AEO expert.
Given a product page's raw Markdown and its full audit reports, generate
concrete, copy-paste-ready fixes for every identified issue.
Follow Google Search Essentials, E-E-A-T guidelines, and schema.org Product spec.

Return ONLY a valid JSON object – no prose, no markdown fences.

Required JSON schema:
{
  "fixed_title_tag": string,
  "fixed_meta_description": string,
  "fixed_h1": string,
  "suggested_h2s": [string],
  "canonical_fix": string | null,
  "hreflang_fix": string | null,
  "robots_meta_fix": string | null,
  "rewritten_product_description": string,
  "ai_optimized_description": string,
  "eeat_improvements": {
    "author_bio_suggestion": string,
    "expertise_signals": [string],
    "trust_signals_to_add": [string]
  },
  "schema_markup_snippet": string,
  "faq_schema_snippet": string,
  "speakable_schema_snippet": string,
  "open_graph_tags": {
    "og_title": string,
    "og_description": string,
    "og_type": string
  },
  "image_alt_tag_suggestions": [{"image_context": string, "suggested_alt": string}],
  "internal_link_suggestions": [{"anchor_text": string, "target_page_type": string}],
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


async def autofix_agent(state: AgentState) -> AgentState:
    """Generate copy-paste SEO + AEO fixes using Sonnet's reasoning capability."""
    markdown = state.get("markdown_content", "")
    seo_report = state_dict(state, "seo_report")
    aeo_report = state_dict(state, "aeo_report")
    diagnosis = state_dict(state, "final_diagnosis")

    if not seo_report:
        return {"errors": ["autofix_agent: no seo_report"]}

    logger.info("autofix_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""
Product page Markdown (truncated to 6000 chars):
{markdown[:6000]}

---
SEO Audit Report (JSON):
{json.dumps(seo_report, indent=2)}

---
AEO Report (AI Visibility gaps):
{json.dumps(aeo_report.get('gaps', []), indent=2)}

---
Top Priority Actions:
{json.dumps(diagnosis.get('quick_wins', []), indent=2)}

Generate complete, actionable fixes for every issue found.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)

    autofix_report, parse_err = safe_json_parse_report(raw, "autofix_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "autofix_agent.done",
        actions=len(autofix_report.get("priority_action_plan", [])),
        duration_ms=duration_ms,
    )

    return {
        "autofix_report": autofix_report,
        "agent_reports": [
            {
                "agent": "autofix_agent",
                "model": _MODEL,
                "input": {
                    "markdown_chars": len(markdown),
                    "seo_report_summary": {
                        "overall_seo_score": seo_report.get("overall_seo_score"),
                        "top_issues": seo_report.get("top_issues", [])[:3],
                        "quick_wins": seo_report.get("quick_wins", [])[:3],
                    },
                },
                "output": autofix_report,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
