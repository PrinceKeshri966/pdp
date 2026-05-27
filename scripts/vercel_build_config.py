#!/usr/bin/env python3
"""Build public/config.json from Vercel env vars (fallback if live API slow)."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
PUBLIC.mkdir(exist_ok=True)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

google_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
google_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
app_env = (os.getenv("APP_ENV") or "production").strip()
dev_bypass = (os.getenv("DEV_AUTH_BYPASS") or "false").lower() == "true"

if google_id and google_secret:
    provider = "google"
elif (os.getenv("CLERK_PUBLISHABLE_KEY") or "").strip() and "dummy" not in (os.getenv("CLERK_PUBLISHABLE_KEY") or "").lower():
    provider = "clerk"
else:
    provider = "none"

auth_required = provider != "none" or not (dev_bypass and app_env == "development")

config = {
    "auth_provider": provider,
    "auth_required": auth_required,
    "clerk_publishable_key": os.getenv("CLERK_PUBLISHABLE_KEY") or "",
    "google_login_url": "/api/v1/auth/google/login",
}

(PUBLIC / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
print("Wrote public/config.json", config)
