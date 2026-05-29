"""
Per-domain extraction strategy memory (learns Playwright-first / XHR success).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_MEMORY_PATH = Path(__file__).resolve().parents[3] / "data" / "domain_extraction_memory.json"


def _domain(url: str) -> str:
    return (urlparse(url).netloc or "").lower().replace("www.", "")


def load_domain_strategy(url: str) -> dict[str, Any] | None:
    dom = _domain(url)
    if not dom or not _MEMORY_PATH.exists():
        return None
    try:
        data = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
        return data.get(dom)
    except Exception:
        return None


def record_domain_success(
    url: str,
    *,
    scraper_method: str,
    overall_confidence: float,
    platform: str | None = None,
    used_network: bool = False,
) -> None:
    """Persist winning strategy when extraction is strong."""
    if overall_confidence < 0.55:
        return
    dom = _domain(url)
    if not dom:
        return
    _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    store: dict[str, Any] = {}
    if _MEMORY_PATH.exists():
        try:
            store = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            store = {}
    entry = store.get(dom) or {}
    entry.update({
        "preferred_scraper": scraper_method,
        "playwright_first": scraper_method.startswith("playwright"),
        "use_network_capture": used_network,
        "platform": platform,
        "last_confidence": round(overall_confidence, 2),
        "success_count": int(entry.get("success_count") or 0) + 1,
    })
    store[dom] = entry
    _MEMORY_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def should_force_playwright_first(url: str, page_type: str | None = None) -> bool:
    if (page_type or "").lower() in ("pdp", "product"):
        return True
    mem = load_domain_strategy(url)
    if mem and mem.get("playwright_first"):
        return True
    return False
