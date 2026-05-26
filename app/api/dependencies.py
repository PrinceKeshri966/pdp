"""
app/api/dependencies.py

Reusable FastAPI dependencies that combine Clerk auth + DB lookup
so every route gets a fully hydrated (tenant, user) context.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import ClerkUser, get_current_user
from app.models.tenant import Tenant
from app.models.user import User

settings = get_settings()


# ── Resolve or auto-provision DB user from Clerk JWT ─────────────────────────
async def get_db_user(
    clerk_user: ClerkUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Look up (or create on first login) the DB User row that corresponds
    to the authenticated Clerk identity.
    """
    result = await db.execute(
        select(User).where(User.clerk_user_id == clerk_user.clerk_id)
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        # Auto-provision on first SSO login (or dev bypass)
        db_user = User(
            clerk_user_id=clerk_user.clerk_id,
            email=clerk_user.email or f"{clerk_user.clerk_id}@unknown.clerk",
            full_name="Dev User" if clerk_user.clerk_id == "user_dev_local" else None,
        )
        db.add(db_user)
        await db.flush()   # get the generated UUID

    return db_user


# ── Resolve tenant from DB user ───────────────────────────────────────────────
async def get_db_tenant(
    db_user: User = Depends(get_db_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """
    Return the Tenant the authenticated user belongs to.
    Raises 403 if the user has no tenant yet.
    """
    if db_user.tenant_id is None:
        # Dev mode: auto-create a workspace so API calls work without Clerk org setup
        if settings.dev_auth_bypass and settings.app_env == "development":
            tenant = Tenant(
                name="Dev Workspace",
                slug="dev-workspace",
                plan="free",
            )
            db.add(tenant)
            await db.flush()
            db_user.tenant_id = tenant.id
            db_user.role = "owner"
            await db.flush()
            return tenant

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any tenant.",
        )
    result = await db.execute(
        select(Tenant).where(Tenant.id == db_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant not found or inactive.",
        )
    return tenant
