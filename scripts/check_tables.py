"""List tables created by init_db(). Run: venv\\Scripts\\python.exe scripts/check_tables.py"""
import asyncio

from sqlalchemy import text

from app.core.database import engine

EXPECTED = ("tenants", "users", "analysis_reports", "blueprints")


async def main() -> None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result.fetchall()]
    print("All tables:", tables)
    for name in EXPECTED:
        print(f"  {name}: {'OK' if name in tables else 'MISSING'}")


if __name__ == "__main__":
    asyncio.run(main())
