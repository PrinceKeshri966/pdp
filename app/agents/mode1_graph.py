"""
app/agents/mode1_graph.py

Mode 1 LangGraph Pipeline — Fan-Out / Fan-In Architecture
──────────────────────────────────────────────────────────

Phase 1 — Sequential (Data Prep):
  URL → [Scraper] → [ContextRouter] → [Extractor]

Phase 2 — Parallel Fan-Out (Analysis):
  [Extractor] → [SEO] ──────────┐
              → [AEO] ──────────┤
              → [UX]  ──────────┤→ Fan-In → [Prioritization]
              → [Competitor] ───┤
              → [Psychology] ───┘

Phase 3 — Sequential (Synthesis):
  [Prioritization]

Phase 4 — Parallel Fan-Out (Generation):
  [Prioritization] → [AutoFix] ──────┐
                   → [ContentGen] ───┘→ END

Total estimated latency: ~17s vs ~35s sequential
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.state import AgentState
from app.agents.scraper_agent import scraper_agent
from app.agents.context_router import context_router_agent
from app.agents.extractor_agent import extractor_agent
from app.agents.seo_agent import seo_agent
from app.agents.aeo_agent import aeo_agent
from app.agents.ux_agent import ux_agent
from app.agents.competitor_agent import competitor_agent
from app.agents.psychology_agent import psychology_agent
from app.agents.prioritization_agent import prioritization_agent
from app.agents.autofix_agent import autofix_agent
from app.agents.content_gen_agent import content_gen_agent
from app.agents.pipeline_stream import MODE1_PIPELINE, stream_graph_progress
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Guard: abort graph on hard failure ────────────────────────────────────────
def _should_continue(state: AgentState) -> str:
    return "continue" if state.get("status") != "failed" else "abort"


def _route_extractor(state: AgentState) -> list[str] | str:
    """Conditionally fan-out to all 5 agents, or abort if failed."""
    if state.get("status") == "failed":
        return END
    return ["seo", "aeo", "ux", "competitor", "psychology"]


async def generation_join(state: AgentState) -> AgentState:
    """Wait for autofix + content_gen parallel branches before pipeline ends."""
    return {"status": "completed"}


# ── Build the graph ───────────────────────────────────────────────────────────
def build_mode1_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # ── Register all nodes ────────────────────────────────────────────────────
    graph.add_node("scraper", scraper_agent)
    graph.add_node("context_router", context_router_agent)
    graph.add_node("extractor", extractor_agent)

    # Phase 2 — parallel analysis
    graph.add_node("seo", seo_agent)
    graph.add_node("aeo", aeo_agent)
    graph.add_node("ux", ux_agent)
    graph.add_node("competitor", competitor_agent)
    graph.add_node("psychology", psychology_agent)

    # Phase 3 — synthesis
    graph.add_node("prioritization", prioritization_agent)

    # Phase 4 — parallel generation (join so both finish before END)
    graph.add_node("autofix", autofix_agent)
    graph.add_node("content_gen", content_gen_agent)
    graph.add_node("generation_join", generation_join)

    # ── Entry point ───────────────────────────────────────────────────────────
    graph.set_entry_point("scraper")

    # ── Phase 1: Sequential ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "scraper",
        _should_continue,
        {"continue": "context_router", "abort": END},
    )
    graph.add_conditional_edges(
        "context_router",
        _should_continue,
        {"continue": "extractor", "abort": END},
    )

    # ── Phase 2: Fan-Out (extractor → all 5 analysis agents in parallel) ──────
    graph.add_conditional_edges("extractor", _route_extractor)

    # ── Phase 3: Fan-In (all 5 → prioritization) ─────────────────────────────
    graph.add_edge("seo", "prioritization")
    graph.add_edge("aeo", "prioritization")
    graph.add_edge("ux", "prioritization")
    graph.add_edge("competitor", "prioritization")
    graph.add_edge("psychology", "prioritization")

    # ── Phase 4: Fan-Out → join (both agents must finish; avoids dropped autofix_report) ─
    graph.add_edge("prioritization", "autofix")
    graph.add_edge("prioritization", "content_gen")
    graph.add_edge("autofix", "generation_join")
    graph.add_edge("content_gen", "generation_join")
    graph.add_edge("generation_join", END)

    return graph


# ── Compiled graph singleton ──────────────────────────────────────────────────
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
        "page_contexts": None,
        "agent_context_packages": None,
        "seo_preprocessor_facts": None,
        "ux_preprocessor_facts": None,
        "psychology_preprocessor_facts": None,
        "json_structured_data": None,
        "seo_report": None,
        "aeo_report": None,
        "ux_report": None,
        "competitor_report": None,
        "psychology_report": None,
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
            )
        yield event, state


async def run_mode1(
    url: str,
    tenant_id: str,
    user_id: str,
    competitor_urls: list[str] | None = None,
    compare_as: str = "auto",
) -> AgentState:
    """
    Entry-point called by the FastAPI route.

    Parameters
    ----------
    url              : Product page URL to analyse.
    tenant_id        : UUID string of the requesting tenant.
    user_id          : UUID string of the requesting user.
    competitor_urls  : Optional list of up to 2 competitor URLs (user-provided).
    """
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
