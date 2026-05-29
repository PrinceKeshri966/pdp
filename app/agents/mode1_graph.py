"""
app/agents/mode1_graph.py

Mode 1 LangGraph Pipeline — Fan-Out / Fan-In Architecture
──────────────────────────────────────────────────────────

Phase 1 — Sequential (Data Prep + Reliability):
  URL → [Scraper] → [ScrapeQuality] → [ContextRouter] → [VisualUX] → [Extractor]

Phase 2 — Parallel Fan-Out (Analysis):
  [Extractor] → [SEO|AEO|UX|Competitor|Psychology] → [Validator] → [Prioritization]

Phase 3–4 — Generation (AutoFix + ContentGen lazy) → END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.state import AgentState
from app.agents.scraper_agent import scraper_agent
from app.agents.scrape_validator import scrape_quality_agent
from app.agents.context_router import context_router_agent
from app.agents.visual_ux import visual_ux_agent
from app.agents.extractor_agent import extractor_agent
from app.agents.seo_agent import seo_agent
from app.agents.aeo_agent import aeo_agent
from app.agents.ux_agent import ux_agent
from app.agents.competitor_agent import competitor_agent
from app.agents.psychology_agent import psychology_agent
from app.agents.validator_agent import validator_agent
from app.agents.prioritization_agent import prioritization_agent
from app.agents.autofix_agent import autofix_agent
from app.agents.content_gen_agent import content_gen_agent
from app.agents.pipeline_stream import MODE1_PIPELINE, stream_graph_progress
from app.analytics.agent_metrics import build_run_analytics
from app.core.agent_router import agent_router_agent
from app.core.logging import get_logger

logger = get_logger(__name__)


def _should_continue(state: AgentState) -> str:
    return "continue" if state.get("status") != "failed" else "abort"


def _route_extractor(state: AgentState) -> str:
    if state.get("status") == "failed":
        return "abort"
    return "continue"


def _route_parallel_analysis(state: AgentState) -> list[str] | str:
    if state.get("status") == "failed":
        return END
    return ["seo", "aeo", "ux", "competitor", "psychology"]


async def generation_join(state: AgentState) -> AgentState:
    """Finalize pipeline; validate outputs for frontend trust, then attach analytics."""
    from app.validators.sanitize_pipeline import sanitize_mode1_for_frontend

    merged = dict(state)
    merged, _fv = sanitize_mode1_for_frontend(merged)
    analytics = build_run_analytics(merged.get("agent_reports") or [], merged)
    return {
        "status": "completed",
        "run_analytics": analytics,
        "frontend_validation": merged.get("frontend_validation"),
        "audit_reliability": merged.get("audit_reliability"),
        "autofix_report": merged.get("autofix_report"),
        "final_diagnosis": merged.get("final_diagnosis"),
        "seo_report": merged.get("seo_report"),
        "aeo_report": merged.get("aeo_report"),
        "ux_report": merged.get("ux_report"),
        "json_structured_data": merged.get("json_structured_data"),
    }


def build_mode1_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("scraper", scraper_agent)
    graph.add_node("scrape_quality", scrape_quality_agent)
    graph.add_node("context_router", context_router_agent)
    graph.add_node("visual_ux", visual_ux_agent)
    graph.add_node("extractor", extractor_agent)
    graph.add_node("agent_router", agent_router_agent)

    graph.add_node("seo", seo_agent)
    graph.add_node("aeo", aeo_agent)
    graph.add_node("ux", ux_agent)
    graph.add_node("competitor", competitor_agent)
    graph.add_node("psychology", psychology_agent)

    graph.add_node("validator", validator_agent)
    graph.add_node("prioritization", prioritization_agent)

    graph.add_node("autofix", autofix_agent)
    graph.add_node("content_gen", content_gen_agent)
    graph.add_node("generation_join", generation_join)

    graph.set_entry_point("scraper")

    graph.add_conditional_edges("scraper", _should_continue, {"continue": "scrape_quality", "abort": END})
    graph.add_conditional_edges("scrape_quality", _should_continue, {"continue": "context_router", "abort": END})
    graph.add_conditional_edges("context_router", _should_continue, {"continue": "visual_ux", "abort": END})
    graph.add_conditional_edges("visual_ux", _should_continue, {"continue": "extractor", "abort": END})

    graph.add_conditional_edges(
        "extractor",
        _route_extractor,
        {"continue": "agent_router", "abort": END},
    )
    graph.add_conditional_edges("agent_router", _route_parallel_analysis)

    graph.add_edge("seo", "validator")
    graph.add_edge("aeo", "validator")
    graph.add_edge("ux", "validator")
    graph.add_edge("competitor", "validator")
    graph.add_edge("psychology", "validator")

    graph.add_edge("validator", "prioritization")

    graph.add_edge("prioritization", "autofix")
    graph.add_edge("prioritization", "content_gen")
    graph.add_edge("autofix", "generation_join")
    graph.add_edge("content_gen", "generation_join")
    graph.add_edge("generation_join", END)

    return graph


_mode1_graph = build_mode1_graph().compile()


def build_mode1_initial_state(
    url: str,
    tenant_id: str,
    user_id: str,
    competitor_urls: list[str] | None = None,
    compare_as: str = "auto",
) -> AgentState:
    return {
        "url": url,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "competitor_urls": competitor_urls or [],
        "compare_as": compare_as or "auto",
        "agent_reports": [],
        "errors": [],
        "status": "running",
        "markdown_content": None,
        "scraper_method": None,
        "dom_technical_seo": None,
        "scrape_html": None,
        "scrape_validation": None,
        "page_type_info": None,
        "agent_plan": None,
        "audit_depth": "standard",
        "scrape_retry_count": 0,
        "scrape_retry_methods": [],
        "partial_analysis": False,
        "page_contexts": None,
        "agent_context_packages": None,
        "seo_preprocessor_facts": None,
        "ux_preprocessor_facts": None,
        "psychology_preprocessor_facts": None,
        "extraction_confidence": None,
        "visual_ux_facts": None,
        "json_structured_data": None,
        "seo_report": None,
        "aeo_report": None,
        "ux_report": None,
        "competitor_report": None,
        "psychology_report": None,
        "validation_report": None,
        "deterministic_scores": None,
        "audit_reliability": None,
        "run_analytics": None,
        "final_diagnosis": None,
        "autofix_report": None,
        "generated_content": None,
        "business_input": None,
        "business_understanding": None,
        "pdp_research": None,
        "final_blueprint": None,
    }


async def stream_mode1(
    url: str,
    tenant_id: str,
    user_id: str,
    competitor_urls: list[str] | None = None,
    compare_as: str = "auto",
):
    initial_state = build_mode1_initial_state(url, tenant_id, user_id, competitor_urls, compare_as)
    logger.info("mode1.start", url=url, tenant_id=tenant_id)
    async for event, state in stream_graph_progress(_mode1_graph, initial_state, MODE1_PIPELINE):
        if event["type"] == "done":
            logger.info(
                "mode1.done",
                status=state.get("status"),
                agents_ran=len(state.get("agent_reports", [])),
                health_score=(state.get("final_diagnosis") or {}).get("overall_health_score"),
                reliability=(state.get("audit_reliability") or {}).get("report_reliability"),
            )
        yield event, state


async def run_mode1(
    url: str,
    tenant_id: str,
    user_id: str,
    competitor_urls: list[str] | None = None,
    compare_as: str = "auto",
) -> AgentState:
    initial_state = build_mode1_initial_state(url, tenant_id, user_id, competitor_urls, compare_as)
    logger.info("mode1.start", url=url, tenant_id=tenant_id)
    final_state: AgentState = await _mode1_graph.ainvoke(initial_state)  # type: ignore[assignment]
    logger.info(
        "mode1.done",
        status=final_state.get("status"),
        agents_ran=len(final_state.get("agent_reports", [])),
        health_score=(final_state.get("final_diagnosis") or {}).get("overall_health_score"),
    )
    return final_state
