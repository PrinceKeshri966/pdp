"""
app/models/user.py
Platform user – linked to a Clerk SSO identity and optionally to a Tenant.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Clerk identity ────────────────────────────────────────────────────────
    clerk_user_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )  # e.g. "user_2NxAbc..."

    # ── Tenant FK (nullable = superadmin / unaffiliated user) ─────────────────
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Profile ───────────────────────────────────────────────────────────────
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Role inside the tenant  ("owner" | "admin" | "member") ───────────────
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant: Mapped["Tenant"] = relationship(  # type: ignore[name-defined]
        "Tenant", back_populates="users"
    )
    reports: Mapped[list["AnalysisReport"]] = relationship(  # type: ignore[name-defined]
        "AnalysisReport", back_populates="created_by", lazy="noload"
    )
    blueprints: Mapped[list["Blueprint"]] = relationship(  # type: ignore[name-defined]
        "Blueprint", back_populates="created_by", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r}>"
