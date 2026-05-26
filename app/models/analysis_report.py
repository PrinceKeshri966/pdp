"""
app/models/analysis_report.py
Stores the full output of Mode 1 — complete 10-agent pipeline.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Input ─────────────────────────────────────────────────────────────────
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    competitor_urls: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )  # user-provided competitor URLs

    # ── Phase 1: Scraper + Extractor ─────────────────────────────────────────
    raw_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraper_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    json_structured_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Phase 2: Parallel analysis reports ───────────────────────────────────
    seo_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    aeo_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ux_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    competitor_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    psychology_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Phase 3: Prioritization ───────────────────────────────────────────────
    final_diagnosis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Phase 4: Generation ───────────────────────────────────────────────────
    autofix_report: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    generated_content: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Aggregate scores ──────────────────────────────────────────────────────
    seo_score: Mapped[float | None] = mapped_column(nullable=True)
    overall_health_score: Mapped[float | None] = mapped_column(nullable=True)

    # ── Audit trail ───────────────────────────────────────────────────────────
    agent_logs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
        "Tenant", back_populates="reports"
    )
    created_by: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="reports"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnalysisReport id={self.id} status={self.status!r}>"
