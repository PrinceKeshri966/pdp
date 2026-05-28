"""
Per-agent latency, tokens, cost estimates, and run-level analytics.
"""
from __future__ import annotations

from typing import Any

# USD per 1M tokens (approximate Haiku/Sonnet blend for estimates)
_COST_IN = {"haiku": 0.80, "sonnet": 3.00, "default": 1.50}
_COST_OUT = {"haiku": 4.00, "sonnet": 15.00, "default": 8.00}


def _model_tier(model: str) -> str:
    m = (model or "").lower()
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    return "default"


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    tier = _model_tier(model)
    return round(
        (input_tokens / 1_000_000) * _COST_IN[tier] + (output_tokens / 1_000_000) * _COST_OUT[tier],
        6,
    )


def record_agent_metric(
    agent: str,
    *,
    model: str = "heuristic",
    duration_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_hit: bool = False,
    confidence: float | None = None,
    parse_failure: bool = False,
    retry_count: int = 0,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "model": model,
        "duration_ms": duration_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimate_cost_usd(model, input_tokens, output_tokens),
        "cache_hit": cache_hit,
        "confidence": confidence,
        "parse_failure": parse_failure,
        "retry_count": retry_count,
    }


def build_run_analytics(agent_reports: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    """Aggregate metrics from agent_reports + reliability state."""
    rows: list[dict[str, Any]] = []
    total_in = total_out = 0
    total_ms = 0
    total_cost = 0.0
    parse_failures = 0

    for r in agent_reports or []:
        model = r.get("model") or "heuristic"
        inp = int(r.get("input_tokens") or 0)
        out = int(r.get("output_tokens") or 0)
        dur = int(r.get("duration_ms") or 0)
        cost = estimate_cost_usd(model, inp, out)
        total_in += inp
        total_out += out
        total_ms += dur
        total_cost += cost
        if r.get("parse_error"):
            parse_failures += 1
        rows.append(
            record_agent_metric(
                r.get("agent", "unknown"),
                model=model,
                duration_ms=dur,
                input_tokens=inp,
                output_tokens=out,
                cache_hit=bool(r.get("cache_hit")),
                confidence=r.get("confidence"),
                parse_failure=bool(r.get("parse_error")),
                retry_count=int(r.get("retry_count") or 0),
            )
        )

    ar = state.get("audit_reliability") or {}
    return {
        "agents": rows,
        "totals": {
            "duration_ms": total_ms,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "estimated_cost_usd": round(total_cost, 4),
            "parse_failures": parse_failures,
            "agent_count": len(rows),
        },
        "reliability": ar,
    }
