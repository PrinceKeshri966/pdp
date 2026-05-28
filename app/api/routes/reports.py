"""
app/api/routes/reports.py

GET /reports – Fetch paginated history of both AnalysisReports and Blueprints
               for the authenticated user's tenant.
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
        .where(
            AnalysisReport.tenant_id == tenant.id,
            AnalysisReport.user_id == db_user.id,
        )
        .order_by(desc(AnalysisReport.created_at))
        .offset(offset)
        .limit(page_size)
    )
    reports = report_rows.scalars().all()

    total_reports_row = await db.execute(
        select(func.count()).select_from(AnalysisReport).where(
            AnalysisReport.tenant_id == tenant.id,
            AnalysisReport.user_id == db_user.id,
        )
    )
    total_reports: int = total_reports_row.scalar_one()

    # ── Blueprints ────────────────────────────────────────────────────────────
    blueprint_rows = await db.execute(
        select(Blueprint)
        .where(
            Blueprint.tenant_id == tenant.id,
            Blueprint.user_id == db_user.id,
        )
        .order_by(desc(Blueprint.created_at))
        .offset(offset)
        .limit(page_size)
    )
    blueprints = blueprint_rows.scalars().all()

    total_blueprints_row = await db.execute(
        select(func.count()).select_from(Blueprint).where(
            Blueprint.tenant_id == tenant.id,
            Blueprint.user_id == db_user.id,
        )
    )
    total_blueprints: int = total_blueprints_row.scalar_one()

    return ReportsListResponse(
        analysis_reports=[AnalysisReportSummary.model_validate(r) for r in reports],
        blueprints=[BlueprintSummary.model_validate(b) for b in blueprints],
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
    jsd = report.json_structured_data or {}
    return AnalyzePDPResponse(
        report_id=report.id,
        status=report.status,
        overall_health_score=report.overall_health_score,
        seo_score=report.seo_score,
        source_url=report.source_url,
        json_structured_data=jsd,
        dom_technical_seo=jsd.get("_dom_technical_seo") or {},
        seo_report=report.seo_report or {},
        aeo_report=report.aeo_report or {},
        ux_report=report.ux_report or {},
        competitor_report=report.competitor_report or {},
        psychology_report=report.psychology_report or {},
        final_diagnosis=report.final_diagnosis or {},
        autofix_report=report.autofix_report or {},
        generated_content=report.generated_content or {},
        audit_reliability=jsd.get("_audit_reliability") or {},
        run_analytics=jsd.get("_run_analytics") or {},
        agent_reports=report.agent_logs or [],
        errors=[report.error_message] if report.error_message else [],
    )


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
