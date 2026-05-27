"""
app/agents/model_router.py

get_model(agent_name) → model string
──────────────────────────────────────
Every agent calls this instead of hard-coding a model name.
Switching models later means editing ONE dict.

Model tier guide
────────────────
Sonnet  →  complex reasoning, code generation, multi-step orchestration
Haiku   →  fast parsing, pattern extraction, lightweight classification
"""
from app.core.config import get_settings

_settings = get_settings()

# ── Assignment table ──────────────────────────────────────────────────────────
_AGENT_MODEL_MAP: dict[str, str] = {
    # ── Sonnet (Claude 4.5 Sonnet) ────────────────────────────────────────────
    "orchestrator":          _settings.model_sonnet,
    "business_understanding": _settings.model_sonnet,
    "autofix":               _settings.model_sonnet,
    "blueprint_generator":   _settings.model_sonnet,

    # ── Haiku (Claude 4.5 Haiku) ──────────────────────────────────────────────
    "seo":                   _settings.model_haiku,
    "aeo":                   _settings.model_haiku,
    "ux":                    _settings.model_haiku,
    "psychology":            _settings.model_haiku,
    "competitor":            _settings.model_haiku,
    "scraper_parser":        _settings.model_haiku,
    "chat_interface":        _settings.model_haiku,
    "pdp_researcher":        _settings.model_haiku,
}

_DEFAULT_MODEL = _settings.model_haiku   # safe fallback


def get_model(agent_name: str) -> str:
    """
    Return the Claude model string for the given agent.

    Parameters
    ----------
    agent_name : str
        One of the keys in _AGENT_MODEL_MAP (case-insensitive).

    Returns
    -------
    str
        Full Anthropic model identifier, e.g. ``"claude-sonnet-4-6"``.

    Example
    -------
    >>> get_model("autofix")
    'claude-sonnet-4-6'
    >>> get_model("seo")
    'claude-haiku-4-5-20251001'
    """
    return _AGENT_MODEL_MAP.get(agent_name.lower(), _DEFAULT_MODEL)
