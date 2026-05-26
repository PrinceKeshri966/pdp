"""
app/api/routes/analyze.py

POST /analyze/pdp      – Mode 1: Full 10-agent pipeline
POST /analyze/business – Mode 2: Blueprint generation
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mode1_graph import run_mode1
from app.agents.mode2_graph import run_mode2
from app.api.dependencies import get_db_tenant, get_db_user
from app.core.database import get_db
from app.models.analysis_report import AnalysisReport
from app.models.blueprint import Blueprint
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.analyze import (
    AnalyzeBusinessRequest,
    AnalyzeBusinessResponse,
    AnalyzePDPRequest,
    AnalyzePDPResponse,
)

router = APIRouter(prefix="/analyze", tags=["Analyze"])


# ── Mode 1: Full Pipeline ─────────────────────────────────────────────────────
@router.post(
    "/pdp",
    response_model=AnalyzePDPResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mode 1 – Full PDP analysis (SEO + AEO + UX + Competitor + Psychology + Fixes)",
)
async def analyze_pdp(
    body: AnalyzePDPRequest,
    db: AsyncSession = Depends(get_db),
    db_user: User = Depends(get_db_user),
    tenant: Tenant = Depends(get_db_tenant),
) -> AnalyzePDPResponse:
    # ── Create DB record immediately so client has an ID ──────────────────────
    report = AnalysisReport(
        tenant_id=tenant.id,
        user_id=db_user.id,
        source_url=body.url,
        competitor_urls=body.competitor_urls,
        status="running",
    )
    db.add(report)
    await db.flush()

    try:
        final_state = await run_mode1(
            url=body.url,
            tenant_id=str(tenant.id),
            user_id=str(db_user.id),
            competitor_urls=body.competitor_urls,
        )
    except Exception as exc:
        report.status = "failed"
        report.error_message = str(exc)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {exc}",
        )

    # ── Persist all results ───────────────────────────────────────────────────
    report.status = final_state.get("status", "completed")
    report.raw_markdown = final_state.get("markdown_content")
    report.scraper_method = final_state.get("scraper_method")
    report.json_structured_data = final_state.get("json_structured_data") or {}

    # Phase 2
    report.seo_report = final_state.get("seo_report") or {}
    report.aeo_report = final_state.get("aeo_report") or {}
    report.ux_report = final_state.get("ux_report") or {}
    report.competitor_report = final_state.get("competitor_report") or {}
    report.psychology_report = final_state.get("psychology_report") or {}

    # Phase 3
    report.final_diagnosis = final_state.get("final_diagnosis") or {}

    # Phase 4
    report.autofix_report = final_state.get("autofix_report") or {}
    report.generated_content = final_state.get("generated_content") or {}

    # Scores
    report.seo_score = report.seo_report.get("overall_seo_score")
    report.overall_health_score = report.final_diagnosis.get("overall_health_score")

    # Audit
    report.agent_logs = final_state.get("agent_reports", [])
    report.total_tokens = sum(
        (r.get("input_tokens", 0) or 0) + (r.get("output_tokens", 0) or 0)
        for r in final_state.get("agent_reports", [])
    ) or None
    report.error_message = "; ".join(final_state.get("errors", [])) or None

    if report.status == "completed":
        report.completed_at = datetime.now(timezone.utc)

    await db.flush()

    return AnalyzePDPResponse(
        report_id=report.id,
        status=report.status,
        overall_health_score=report.overall_health_score,
        seo_score=report.seo_score,
        source_url=body.url,
        json_structured_data=report.json_structured_data,
        seo_report=report.seo_report,
        aeo_report=report.aeo_report,
        ux_report=report.ux_report,
        competitor_report=report.competitor_report,
        psychology_report=report.psychology_report,
        final_diagnosis=report.final_diagnosis,
        autofix_report=report.autofix_report,
        generated_content=report.generated_content,
        agent_reports=final_state.get("agent_reports", []),
        errors=final_state.get("errors", []),
    )


# ── Mode 2: Business Brief → PDP Blueprint ───────────────────────────────────
@router.post(
    "/business",
    response_model=AnalyzeBusinessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mode 2 – Generate a PDP Blueprint from a business brief",
)
async def analyze_business(
    body: AnalyzeBusinessRequest,
    db: AsyncSession = Depends(get_db),
    db_user: User = Depends(get_db_user),
    tenant: Tenant = Depends(get_db_tenant),
) -> AnalyzeBusinessResponse:
    blueprint = Blueprint(
        tenant_id=tenant.id,
        user_id=db_user.id,
        business_input=body.business_input,
        status="running",
    )
    db.add(blueprint)
    await db.flush()

    try:
        final_state = await run_mode2(
            business_input=body.business_input,
            tenant_id=str(tenant.id),
            user_id=str(db_user.id),
        )
    except Exception as exc:
        blueprint.status = "failed"
        blueprint.error_message = str(exc)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {exc}",
        )

    blueprint.status = final_state.get("status", "completed")
    blueprint.business_understanding = final_state.get("business_understanding") or {}
    blueprint.pdp_research = final_state.get("pdp_research") or {}
    blueprint.final_blueprint = final_state.get("final_blueprint") or {}
    blueprint.title = (
        blueprint.final_blueprint.get("blueprint_title") if blueprint.final_blueprint else None
    )
    blueprint.error_message = "; ".join(final_state.get("errors", [])) or None
    if blueprint.status == "completed":
        blueprint.completed_at = datetime.now(timezone.utc)

    await db.flush()

    return AnalyzeBusinessResponse(
        blueprint_id=blueprint.id,
        status=blueprint.status,
        title=blueprint.title,
        business_understanding=blueprint.business_understanding,
        pdp_research=blueprint.pdp_research,
        final_blueprint=blueprint.final_blueprint,
        agent_reports=final_state.get("agent_reports", []),
        errors=final_state.get("errors", []),
    )
