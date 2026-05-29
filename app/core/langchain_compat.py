"""Compatibility shim for langchain_core / langgraph on langchain 1.x."""
from __future__ import annotations


def patch_langchain_globals() -> None:
    """langchain_core.callbacks.manager calls langchain.debug — missing in langchain 1.x."""
    try:
        import langchain
    except ImportError:
        return
    if not hasattr(langchain, "debug"):
        langchain.debug = False  # type: ignore[attr-defined]
    if not hasattr(langchain, "verbose"):
        langchain.verbose = False  # type: ignore[attr-defined]
