"""
app/api/routes/reports.py

GET /reports – Fetch paginated history of both AnalysisReports and Blueprints
               for the authenticated user's tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_tenant, get_db_user
from app.core.database import get_db
from app.models.analysis_report import AnalysisReport
from app.models.blueprint import Blueprint
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.reports import (
    AnalysisReportSummary,
    BlueprintSummary,
    ReportsListResponse,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "",
    response_model=ReportsListResponse,
    summary="Fetch analysis and blueprint history for the tenant",
)
async def list_reports(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    db_user: User = Depends(get_db_user),
    tenant: Tenant = Depends(get_db_tenant),
) -> ReportsListResponse:
    offset = (page - 1) * page_size

    # ── AnalysisReports ───────────────────────────────────────────────────────
    report_rows = await db.execute(
        select(AnalysisReport)
        .where(AnalysisReport.tenant_id == tenant.id)
        .order_by(desc(AnalysisReport.created_at))
        .offset(offset)
        .limit(page_size)
    )
    reports = report_rows.scalars().all()

    total_reports_row = await db.execute(
        select(func.count()).select_from(AnalysisReport).where(
            AnalysisReport.tenant_id == tenant.id
        )
    )
    total_reports: int = total_reports_row.scalar_one()

    # ── Blueprints ────────────────────────────────────────────────────────────
    blueprint_rows = await db.execute(
        select(Blueprint)
        .where(Blueprint.tenant_id == tenant.id)
        .order_by(desc(Blueprint.created_at))
        .offset(offset)
        .limit(page_size)
    )
    blueprints = blueprint_rows.scalars().all()

    total_blueprints_row = await db.execute(
        select(func.count()).select_from(Blueprint).where(
            Blueprint.tenant_id == tenant.id
        )
    )
    total_blueprints: int = total_blueprints_row.scalar_one()

    return ReportsListResponse(
        analysis_reports=[AnalysisReportSummary.model_validate(r) for r in reports],
        blueprints=[BlueprintSummary.model_validate(b) for b in blueprints],
        total_analysis=total_reports,
        total_blueprints=total_blueprints,
    )
