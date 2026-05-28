"""POST fitpass audit to local uvicorn and save result."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings

URL = "https://fitpass.co.in/"
OUT = ROOT / "_verify_fitpass_latest.json"


def make_token() -> str:
    s = get_settings()
    payload = {
        "iss": "optipdp",
        "sub": "b4c4f424-e944-4efb-9bdd-c82c93fca503",
        "email": "dev@test.local",
        "name": "Dev User",
        "exp": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def stream_analyze() -> dict:
    token = make_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body = {"url": URL, "compare_as": "auto", "competitor_urls": []}
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        with client.stream(
            "POST",
            "http://127.0.0.1:8000/api/v1/analyze/pdp/stream",
            headers=headers,
            json=body,
        ) as resp:
            resp.raise_for_status()
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    part, buf = buf.split("\n\n", 1)
                    for line in part.split("\n"):
                        if not line.startswith("data: "):
                            continue
                        data = json.loads(line[6:])
                        if data.get("type") == "progress":
                            print(f"  [{data.get('completed_count', '?')}/{data.get('total_count', '?')}] {data.get('label', '')}")
                        if data.get("type") == "error":
                            raise RuntimeError(data.get("detail", "stream error"))
                        if data.get("type") == "done":
                            return data["result"]
    raise RuntimeError("stream ended without done")


def main() -> None:
    print("Starting audit via http://127.0.0.1:8000 ...")
    t0 = time.time()
    result = stream_analyze()
    print(f"Done in {int(time.time() - t0)}s")
    OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"Saved {OUT}")
    seo = result.get("seo_report") or {}
    print("title:", (seo.get("title_tag") or {}).get("value"))
    print("meta len:", len((seo.get("meta_description") or {}).get("value") or ""))
    dom = result.get("dom_technical_seo") or {}
    print("dom title:", dom.get("title_tag"))
    lc = (result.get("competitor_report") or {}).get("live_compare") or {}
    print("competitors:", [s.get("url") for s in lc.get("sites", []) if s.get("role") == "competitor"])


if __name__ == "__main__":
    main()
