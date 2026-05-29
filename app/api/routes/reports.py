"""
app/api/routes/reports.py

GET /reports – Fetch paginated history of both AnalysisReports and Blueprints
               for the authenticated user's tenant.

List queries load summary columns only (no JSONB blobs / raw markdown) for
sub-100ms responses on typical tenants.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_tenant, get_db_user
from app.core.database import get_db
from app.models.analysis_report import AnalysisReport
from app.models.blueprint import Blueprint
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.analyze import AnalyzeBusinessResponse, AnalyzePDPResponse
from app.schemas.reports import (
    AnalysisReportSummary,
    BlueprintSummary,
    ReportsListResponse,
)

router = APIRouter(prefix="/reports", tags=["Reports"])

_REPORT_LIST_COLUMNS = (
    AnalysisReport.id,
    AnalysisReport.source_url,
    AnalysisReport.status,
    AnalysisReport.seo_score,
    AnalysisReport.overall_health_score,
    AnalysisReport.created_at,
    AnalysisReport.completed_at,
)

_BLUEPRINT_LIST_COLUMNS = (
    Blueprint.id,
    Blueprint.title,
    func.left(Blueprint.business_input, 512).label("business_input"),
    Blueprint.status,
    Blueprint.version,
    Blueprint.created_at,
    Blueprint.completed_at,
)


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

    report_filter = (
        AnalysisReport.tenant_id == tenant.id,
        AnalysisReport.user_id == db_user.id,
    )
    blueprint_filter = (
        Blueprint.tenant_id == tenant.id,
        Blueprint.user_id == db_user.id,
    )

    report_total_col = func.count(AnalysisReport.id).over().label("_total")
    report_rows = (
        await db.execute(
            select(*_REPORT_LIST_COLUMNS, report_total_col)
            .where(*report_filter)
            .order_by(desc(AnalysisReport.created_at))
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    blueprint_total_col = func.count(Blueprint.id).over().label("_total")
    blueprint_rows = (
        await db.execute(
            select(*_BLUEPRINT_LIST_COLUMNS, blueprint_total_col)
            .where(*blueprint_filter)
            .order_by(desc(Blueprint.created_at))
            .offset(offset)
            .limit(page_size)
        )
    ).all()

    total_reports = int(report_rows[0]._total) if report_rows else 0
    total_blueprints = int(blueprint_rows[0]._total) if blueprint_rows else 0

    return ReportsListResponse(
        analysis_reports=[
            AnalysisReportSummary(
                id=row.id,
                source_url=row.source_url,
                status=row.status,
                seo_score=row.seo_score,
                overall_health_score=row.overall_health_score,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in report_rows
        ],
        blueprints=[
            BlueprintSummary(
                id=row.id,
                title=row.title,
                business_input=row.business_input,
                status=row.status,
                version=row.version,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in blueprint_rows
        ],
        total_analysis=total_reports,
        total_blueprints=total_blueprints,
    )


@router.get(
    "/analysis/{report_id}",
    response_model=AnalyzePDPResponse,
    summary="Fetch a single Mode 1 analysis report by ID",
)
async def get_analysis_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    db_user: User = Depends(get_db_user),
    tenant: Tenant = Depends(get_db_tenant),
) -> AnalyzePDPResponse:
    result = await db.execute(
        select(AnalysisReport).where(
            AnalysisReport.id == report_id,
            AnalysisReport.tenant_id == tenant.id,
            AnalysisReport.user_id == db_user.id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    from app.api.routes.analyze import _mode1_response

    return _mode1_response(report, {}, report.source_url or "")


@router.get(
    "/blueprint/{blueprint_id}",
    response_model=AnalyzeBusinessResponse,
    summary="Fetch a single Mode 2 blueprint by ID",
)
async def get_blueprint(
    blueprint_id: UUID,
    db: AsyncSession = Depends(get_db),
    db_user: User = Depends(get_db_user),
    tenant: Tenant = Depends(get_db_tenant),
) -> AnalyzeBusinessResponse:
    result = await db.execute(
        select(Blueprint).where(
            Blueprint.id == blueprint_id,
            Blueprint.tenant_id == tenant.id,
            Blueprint.user_id == db_user.id,
        )
    )
    bp = result.scalar_one_or_none()
    if bp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blueprint not found")
    return AnalyzeBusinessResponse(
        blueprint_id=bp.id,
        status=bp.status,
        title=bp.title,
        business_input=bp.business_input,
        business_understanding=bp.business_understanding or {},
        pdp_research=bp.pdp_research or {},
        final_blueprint=bp.final_blueprint or {},
        agent_reports=[],
        errors=[bp.error_message] if bp.error_message else [],
    )
