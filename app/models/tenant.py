"""
app/models/tenant.py
Tenant = a brand / company that signs up on the platform.
Maps 1-to-1 with a Clerk Organization when org features are enabled.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Clerk Organisation ID (optional – for SSO org routing) ────────────────
    clerk_org_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )

    # ── Basic info ────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Plan / billing ────────────────────────────────────────────────────────
    plan: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Arbitrary tenant-level config (AI prefs, brand tone, etc.) ────────────
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    users: Mapped[list["User"]] = relationship(  # type: ignore[name-defined]
        "User", back_populates="tenant", lazy="noload"
    )
    reports: Mapped[list["AnalysisReport"]] = relationship(  # type: ignore[name-defined]
        "AnalysisReport", back_populates="tenant", lazy="noload"
    )
    blueprints: Mapped[list["Blueprint"]] = relationship(  # type: ignore[name-defined]
        "Blueprint", back_populates="tenant", lazy="noload"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tenant id={self.id} slug={self.slug!r}>"
