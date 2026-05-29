"""
Shared helpers for streaming LangGraph pipeline progress to the frontend.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

MODE1_PIPELINE: list[tuple[str, str]] = [
    ("scraper", "Scraper Agent: Fetching page..."),
    ("scrape_quality", "Scrape Validator: Checking content quality..."),
    ("context_router", "Context Router: Mapping strategic pages..."),
    ("visual_ux", "Visual UX: Capturing layout signals..."),
    ("extractor", "Extractor Agent: Parsing product data..."),
    ("agent_router", "Agent Router: Calibrating audit depth..."),
    ("seo", "SEO Agent: Auditing search signals..."),
    ("aeo", "AEO Agent: Checking AI visibility..."),
    ("ux", "UX Agent: Evaluating conversion..."),
    ("competitor", "Competitor Agent: Benchmarking market..."),
    ("psychology", "Psychology Agent: Analyzing triggers..."),
    ("validator", "Validator: Cross-checking report accuracy..."),
    ("prioritization", "Prioritization Agent: Building action plan..."),
    ("autofix", "AutoFix Agent: Generating fixes..."),
    ("content_gen", "Content Agent: Preparing copy shell..."),
]

MODE2_PIPELINE: list[tuple[str, str]] = [
    ("business", "Business Agent: Parsing your market..."),
    ("pdp_researcher", "PDP Researcher Agent: Benchmarking competitors..."),
    ("blueprint", "Blueprint Agent: Designing your layout..."),
]

_PIPELINE_NODES = {node for node, _ in MODE1_PIPELINE} | {node for node, _ in MODE2_PIPELINE}


def merge_state(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in update.items():
        if key in ("agent_reports", "errors") and isinstance(merged.get(key), list) and isinstance(value, list):
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def next_running_label(completed: set[str], pipeline: list[tuple[str, str]]) -> str:
    for node, label in pipeline:
        if node not in completed:
            return label
    return "Finishing up..."


async def stream_graph_progress(
    graph: Any,
    initial_state: dict[str, Any],
    pipeline: list[tuple[str, str]],
) -> AsyncIterator[tuple[dict[str, Any], dict[str, Any]]]:
    """
    Yield (progress_event, partial_state) while the graph runs.
    Final yield includes the merged state in the event payload type 'done'.
    """
    completed: set[str] = set()
    state = dict(initial_state)

    yield (
        {
            "type": "progress",
            "agent": pipeline[0][0],
            "label": pipeline[0][1],
            "status": "running",
            "completed_count": 0,
            "total_count": len(pipeline),
        },
        state,
    )

    async for chunk in graph.astream(initial_state, stream_mode="updates"):
        for node_name, update in chunk.items():
            state = merge_state(state, update)
            if node_name not in _PIPELINE_NODES:
                continue

            completed.add(node_name)
            if len(completed) < len(pipeline):
                nxt = next_running_label(completed, pipeline)
                nxt_agent = next(node for node, _ in pipeline if node not in completed)
                yield (
                    {
                        "type": "progress",
                        "agent": nxt_agent,
                        "label": nxt,
                        "status": "running",
                        "completed_count": len(completed),
                        "total_count": len(pipeline),
                    },
                    state,
                )

    yield (
        {
            "type": "done",
            "label": "Analysis complete",
            "status": "completed",
            "completed_count": len(pipeline),
            "total_count": len(pipeline),
        },
        state,
    )
