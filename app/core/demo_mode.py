"""
CTO demo mode — faster, cache-friendly audits without architecture changes.
Enable via DEMO_MODE=true in environment or Settings.demo_mode.
"""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache
def is_demo_mode() -> bool:
    v = os.getenv("DEMO_MODE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    try:
        from app.core.config import get_settings

        return bool(get_settings().demo_mode)
    except Exception:
        return False
