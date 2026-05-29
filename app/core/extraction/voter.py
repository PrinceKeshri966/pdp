"""
Multi-strategy field voting with per-field confidence and sources.
"""
from __future__ import annotations

import re
from typing import Any


_FIELD_SOURCES: dict[str, list[str]] = {}


def _norm_price(val: Any) -> str | None:
    if val is None:
        return None
    s = re.sub(r"[^\d.]", "", str(val).replace(",", ""))
    if not s or not re.search(r"\d", s):
        return None
    try:
        f = float(s)
        if f > 1_000_000:
            return None
        return str(int(f)) if f == int(f) else str(round(f, 2))
    except ValueError:
        return None


def _norm_name(val: Any) -> str | None:
    if not val:
        return None
    s = str(val).strip()
    if len(s) < 2 or s.lower() in ("unknown", "product", "n/a", "home"):
        return None
    # Reject bare brand-only names on PDPs (e.g. "Mamaearth" without product detail)
    if s.lower() in ("mamaearth", "boat", "killer jeans") and len(s.split()) <= 2:
        return None
    if re.search(r"^(product_)?recommendations?$|related_products|widget_", s, re.I):
        return None
    if re.search(r"^get the app$|^download app$|^shop now$", s, re.I):
        return None
    if re.match(r"^www\.[a-z0-9.-]+\.[a-z]{2,}$", s, re.I):
        return None
    return s[:300]


def _add_candidate(
    field: str,
    value: Any,
    confidence: float,
    source: str,
    candidates: dict[str, list[tuple[Any, float, str]]],
) -> None:
    if value is None or value == "" or value == []:
        return
    candidates.setdefault(field, []).append((value, confidence, source))


def vote_product_fields(
    *,
    schema: dict[str, Any] | None = None,
    open_graph: dict[str, Any] | None = None,
    dom: dict[str, Any] | None = None,
    network: dict[str, Any] | None = None,
    platform_api: dict[str, Any] | None = None,
    next_data: dict[str, Any] | None = None,
    llm: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Merge strategies; return (structured_product, field_meta).
    field_meta maps field -> {confidence, source, agreement}.
    """
    candidates: dict[str, list[tuple[Any, float, str]]] = {}

    def ingest(block: dict[str, Any] | None, base_conf: float, source: str) -> None:
        if not block:
            return
        for k, v in block.items():
            if k.startswith("_"):
                continue
            _add_candidate(k, v, base_conf, source, candidates)

    ingest(schema, 0.92, "json_ld")
    ingest(platform_api, 0.95, "platform_api")
    ingest(network, 0.92, "network_xhr")
    ingest(next_data, 0.82, "next_data")
    ingest(open_graph, 0.75, "open_graph")
    ingest(dom, 0.7, "dom_selectors")
    ingest(llm, 0.65, "llm")

    merged: dict[str, Any] = {}
    meta: dict[str, Any] = {}

    for field, opts in candidates.items():
        if field in ("image_urls", "features", "categories", "breadcrumb", "color_variants", "size_variants", "trust_badges", "video_urls"):
            best = max(opts, key=lambda x: x[1])
            merged[field] = best[0]
            meta[field] = {"confidence": best[1], "source": best[2]}
            continue
        if field == "price":
            priced = []
            for val, conf, src in opts:
                n = _norm_price(val)
                if n:
                    priced.append((n, conf, src))
            if not priced:
                continue
            by_val: dict[str, list[tuple[float, str]]] = {}
            for n, conf, src in priced:
                by_val.setdefault(n, []).append((conf, src))
            best_price = max(
                by_val.keys(),
                key=lambda p: (len(by_val[p]), sum(c for c, _ in by_val[p])),
            )
            sources = by_val[best_price]
            agreement = len(sources) >= 2
            conf = min(0.98, max(c for c, _ in sources) + (0.08 if agreement else 0))
            merged["price"] = best_price
            meta["price"] = {
                "confidence": round(conf, 2),
                "source": sources[0][1],
                "agreement": agreement,
            }
            continue
        if field == "product_name":
            named = []
            for val, conf, src in opts:
                n = _norm_name(val)
                if n:
                    named.append((n, conf, src))
            if not named:
                continue
            best = max(named, key=lambda x: x[1])
            merged["product_name"] = best[0]
            meta["product_name"] = {"confidence": best[1], "source": best[2]}
            continue
        best = max(opts, key=lambda x: x[1])
        merged[field] = best[0]
        meta[field] = {"confidence": best[1], "source": best[2]}

    if meta.get("price", {}).get("agreement"):
        meta.setdefault("schema_confidence", {"confidence": 0.95, "source": "cross_validated"})
    elif schema and schema.get("price"):
        meta["schema_confidence"] = {"confidence": 0.9, "source": "json_ld"}

    return merged, meta
