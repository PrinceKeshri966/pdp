"""
app/models/blueprint.py
Stores the full output of Mode 2: Chat → BusinessAgent → PDPResearcher → BlueprintGenerator.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Blueprint(Base):
    __tablename__ = "blueprints"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Foreign keys ──────────────────────────────────────────────────────────
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Input ─────────────────────────────────────────────────────────────────
    business_input: Mapped[str] = mapped_column(Text, nullable=False)   # raw chat text

    # ── Pipeline artifacts ────────────────────────────────────────────────────
    business_understanding: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # BusinessAgent (Sonnet) JSON

    pdp_research: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # PDPResearcher (Haiku) JSON

    final_blueprint: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # BlueprintGenerator (Sonnet) full output

    # ── Meta ──────────────────────────────────────────────────────────────────
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)

    # ── Pipeline status ───────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending | running | completed | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    tenant: Mapped["Tenant"] = relationship(  # type: ignore[name-defined]
        "Tenant", back_populates="blueprints"
    )
    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="blueprints"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Blueprint id={self.id} status={self.status!r}>"
