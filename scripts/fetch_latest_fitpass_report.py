"""Load latest fitpass analysis from DB for verification."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.analysis_report import AnalysisReport


async def main() -> None:
    async with AsyncSessionLocal() as session:
        q = (
            select(AnalysisReport)
            .where(AnalysisReport.source_url.ilike("%fitpass%"))
            .order_by(AnalysisReport.created_at.desc())
            .limit(1)
        )
        r = await session.execute(q)
        report = r.scalar_one_or_none()
        if not report:
            print("No fitpass report in DB")
            return
        jsd = report.json_structured_data or {}
        dom = jsd.get("_dom_technical_seo") or {}
        out = {
            "id": str(report.id),
            "status": report.status,
            "source_url": report.source_url,
            "created_at": str(report.created_at),
            "dom_technical_seo": dom,
            "seo_report": report.seo_report,
            "competitor_report": report.competitor_report,
            "json_structured_data": jsd,
        }
        path = ROOT / "_verify_fitpass_latest.json"
        path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"Saved {path}")
        seo = report.seo_report or {}
        print("title:", (seo.get("title_tag") or {}).get("value", "")[:80])
        print("meta len:", len((seo.get("meta_description") or {}).get("value") or ""))
        lc = (report.competitor_report or {}).get("live_compare") or {}
        print("competitors:", [s.get("url") for s in lc.get("sites", []) if s.get("role") == "competitor"])


if __name__ == "__main__":
    asyncio.run(main())
