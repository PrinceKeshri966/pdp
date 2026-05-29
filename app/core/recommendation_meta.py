"""
Confidence-layered recommendation metadata.
"""
from __future__ import annotations

from typing import Any


def wrap_recommendation(
    text: str,
    *,
    confidence: float = 0.7,
    deterministic: bool = False,
    visual_verified: bool = False,
    source: str = "heuristic",
    evidence: list[str] | None = None,
    page_type_validated: bool = True,
) -> dict[str, Any]:
    return {
        "text": text,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "deterministic": deterministic,
        "visual_verified": visual_verified,
        "source": source,
        "evidence": evidence or [],
        "page_type_validated": page_type_validated,
    }


def enrich_recommendation_list(
    items: list[str],
    *,
    base_confidence: float = 0.65,
    source: str = "llm",
    page_type_validated: bool = True,
    visual_verified: bool = False,
) -> list[dict[str, Any]]:
    return [
        wrap_recommendation(
            t,
            confidence=base_confidence,
            source=source,
            page_type_validated=page_type_validated,
            visual_verified=visual_verified,
        )
        for t in items
        if t
    ]
