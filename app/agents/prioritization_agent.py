"""
app/agents/prioritization_agent.py

PrioritizationAgent  (Mode 1 – Phase 3, Sequential)   Model: Claude Haiku
───────────────────────────────────────────────────────────────────────────
Fan-In node. Receives all 5 parallel analysis reports and synthesizes
them into a single unified diagnosis with prioritized action plan.

This is what the user sees as their "Overall Health Score" dashboard.
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

_MODEL = get_model("autofix")  # Sonnet — large multi-report synthesis needs full context window

_SYSTEM_PROMPT = """
You are a senior e-commerce optimization strategist.
You have received analysis reports from 5 specialized agents.
Synthesize them into a single unified diagnosis with a prioritized action plan.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema:
{
  "overall_health_score": float (0-10),
  "score_breakdown": {
    "seo": float (0-10),
    "ai_visibility": float (0-10),
    "ux_conversion": float (0-10),
    "competitor_position": float (0-10),
    "psychology": float (0-10)
  },
  "prioritized_recommendations": [
    {
      "rank": int,
      "category": "SEO|AEO|UX|Competitor|Psychology",
      "action": string,
      "impact": "high|medium|low",
      "effort": "low|medium|high",
      "estimated_improvement": string,
      "why_now": string
    }
  ],
  "quick_wins": [string],
  "long_term_fixes": [string],
  "executive_summary": string
}
""".strip()


async def prioritization_agent(state: AgentState) -> AgentState:
    """Synthesize all analysis reports into unified prioritized diagnosis."""
    seo = state.get("seo_report", {})
    aeo = state.get("aeo_report", {})
    ux = state.get("ux_report", {})
    competitor = state.get("competitor_report", {})
    psychology = state.get("psychology_report", {})

    if not any([seo, aeo, ux]):
        return {"errors": ["prioritization_agent: no analysis reports available"]}

    logger.info("prioritization_agent.start", model=_MODEL)
    t0 = time.monotonic()

    def _summarize(report: dict, score_key: str, issues_keys: list[str]) -> dict:
        """Extract only score + top issues from a report to reduce token usage."""
        summary: dict = {"score": report.get(score_key)}
        for key in issues_keys:
            val = report.get(key)
            if val:
                summary[key] = val[:5] if isinstance(val, list) else val
        return summary

    seo_summary = _summarize(seo, "overall_seo_score", ["top_issues", "quick_wins"])
    aeo_summary = _summarize(aeo, "ai_visibility_score", ["gaps", "recommendations"])
    ux_summary = _summarize(ux, "conversion_score", ["recommendations"])
    competitor_summary = _summarize(competitor, "benchmark_scores", ["your_gaps_vs_competitors", "opportunities"])
    psychology_summary = _summarize(psychology, "overall_psychology_score", ["missing_triggers", "recommended_triggers"])
    # cap psychology triggers to 3 to avoid bloat
    if isinstance(psychology_summary.get("recommended_triggers"), list):
        psychology_summary["recommended_triggers"] = psychology_summary["recommended_triggers"][:3]

    user_message = f"""Synthesize these 5 analysis summaries into a unified diagnosis:

SEO: {json.dumps(seo_summary)}
AEO: {json.dumps(aeo_summary)}
UX: {json.dumps(ux_summary)}
Competitor: {json.dumps(competitor_summary)}
Psychology: {json.dumps(psychology_summary)}

Create a prioritized action plan (max 10 items) ranked by impact/effort ratio.
Quick wins = high impact + low effort. Long term = high impact + high effort."""

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    final_diagnosis, parse_err = safe_json_parse_report(raw, "prioritization_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "prioritization_agent.done",
        health_score=final_diagnosis.get("overall_health_score"),
        recommendations=len(final_diagnosis.get("prioritized_recommendations", [])),
        duration_ms=duration_ms,
    )

    return {
        "final_diagnosis": final_diagnosis,
        "status": "completed",
        "agent_reports": [
            {
                "agent": "prioritization_agent",
                "model": _MODEL,
                "output": final_diagnosis,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
