"""
app/core/config.py
Central settings loaded from environment variables / .env file.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "Multi-Tenant AI Commerce OS"
    app_env: str = "development"
    secret_key: str = "changeme"
    debug: bool = True
    demo_mode: bool = False  # DEMO_MODE=true — faster CTO demos (see app/core/demo_mode.py)

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/commerce_os"

    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── Clerk (optional — use if not using Google OAuth below) ───────────────
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""
    clerk_jwt_key: str = ""   # PEM public key — same as "JWKS Public Key" in Clerk dashboard
    dev_auth_bypass: bool = True  # skip auth in local dev only when no provider configured

    # ── Google OAuth (Sign in / Sign up) ─────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    app_base_url: str = "http://localhost:8000"
    jwt_expire_hours: int = 168  # 7 days

    @property
    def clerk_enabled(self) -> bool:
        pk = self.clerk_publishable_key.strip()
        return bool(pk) and "dummy" not in pk.lower()

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id.strip() and self.google_client_secret.strip())

    # ── Screenshot API (Vercel UI → Render backend) ───────────────────────────
    screenshot_api_url: str = ""  # e.g. https://your-app.onrender.com

    # ── Jina Reader ──────────────────────────────────────────────────────────
    jina_api_key: str = ""

    # ── Firecrawl ──────────────────────────────────────────────────────────────────────────────────
    firecrawl_api_key: str = ""

    # ── Redis (optional caching) ─────────────────────────────────────────────
    redis_url: str = ""

    # ── CORS ─────────────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    # ── Model aliases (single source of truth) ───────────────────────────────
    model_sonnet: str = "claude-sonnet-4-6"
    model_haiku: str = "claude-haiku-4-5-20251001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
