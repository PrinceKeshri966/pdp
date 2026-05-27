"""
app/agents/mode2_graph.py

Mode 2 LangGraph Pipeline
──────────────────────────
Chat Input
  →  [BusinessAgent]         Sonnet  (understand intent)
  →  [PDPResearcherAgent]    Haiku   (research patterns)
  →  [BlueprintAgent]        Sonnet  (synthesise blueprint)
  →  END

Each node is an async function: (AgentState) -> AgentState.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.state import AgentState
from app.agents.business_agent import business_agent
from app.agents.pdp_researcher_agent import pdp_researcher_agent
from app.agents.blueprint_agent import blueprint_agent
from app.agents.pipeline_stream import MODE2_PIPELINE, stream_graph_progress
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Guard: abort graph on hard failure ────────────────────────────────────────
def _should_continue(state: AgentState) -> str:
    return "continue" if state.get("status") != "failed" else "abort"


# ── Build the graph ───────────────────────────────────────────────────────────
def build_mode2_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("business", business_agent)
    graph.add_node("pdp_researcher", pdp_researcher_agent)
    graph.add_node("blueprint", blueprint_agent)

    # Entry point
    graph.set_entry_point("business")

    # business → pdp_researcher
    graph.add_conditional_edges(
        "business",
        _should_continue,
        {"continue": "pdp_researcher", "abort": END},
    )

    # pdp_researcher → blueprint
    graph.add_conditional_edges(
        "pdp_researcher",
        _should_continue,
        {"continue": "blueprint", "abort": END},
    )

    # blueprint → END
    graph.add_edge("blueprint", END)

    return graph


# ── Compiled graph (singleton) ────────────────────────────────────────────────
_mode2_graph = build_mode2_graph().compile()


def build_mode2_initial_state(
    business_input: str, tenant_id: str, user_id: str
) -> AgentState:
    return {
        "business_input": business_input,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "agent_reports": [],
        "errors": [],
        "status": "running",
        "url": None,
        "markdown_content": None,
        "json_structured_data": None,
        "seo_report": None,
        "autofix_report": None,
        "business_understanding": None,
        "pdp_research": None,
        "final_blueprint": None,
    }


async def stream_mode2(business_input: str, tenant_id: str, user_id: str):
    initial_state = build_mode2_initial_state(business_input, tenant_id, user_id)
    logger.info("mode2.start", chars=len(business_input), tenant_id=tenant_id)
    async for event, state in stream_graph_progress(_mode2_graph, initial_state, MODE2_PIPELINE):
        if event["type"] == "done":
            logger.info(
                "mode2.done",
                status=state.get("status"),
                agents_ran=len(state.get("agent_reports", [])),
            )
        yield event, state


async def run_mode2(
    business_input: str, tenant_id: str, user_id: str
) -> AgentState:
    """
    Entry-point called by the FastAPI route.

    Parameters
    ----------
    business_input : Free-text merchant brief / chat input.
    tenant_id      : UUID string of the requesting tenant.
    user_id        : UUID string of the requesting user.

    Returns
    -------
    AgentState
        Final state with `final_blueprint` populated.
    """
    initial_state = build_mode2_initial_state(business_input, tenant_id, user_id)

    logger.info("mode2.start", chars=len(business_input), tenant_id=tenant_id)
    final_state: AgentState = await _mode2_graph.ainvoke(initial_state)  # type: ignore[assignment]
    logger.info(
        "mode2.done",
        status=final_state.get("status"),
        agents_ran=len(final_state.get("agent_reports", [])),
    )
    return final_state
