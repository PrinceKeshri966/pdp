"""
app/agents/claude_client.py

Single AsyncAnthropic client shared across all agents.
Avoids re-creating the HTTP connection pool on every call.
"""
from anthropic import AsyncAnthropic
from app.core.config import get_settings

_settings = get_settings()

# Module-level singleton – instantiated once at import time.
claude: AsyncAnthropic = AsyncAnthropic(api_key=_settings.anthropic_api_key)
