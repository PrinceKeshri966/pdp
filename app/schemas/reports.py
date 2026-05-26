"""
app/schemas/reports.py
Response schemas for the /reports history endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AnalysisReportSummary(BaseModel):
    id: UUID
    source_url: str
    status: str
    seo_score: float | None
    overall_score: float | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class BlueprintSummary(BaseModel):
    id: UUID
    title: str | None
    status: str
    version: int
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ReportsListResponse(BaseModel):
    analysis_reports: list[AnalysisReportSummary]
    blueprints: list[BlueprintSummary]
    total_analysis: int
    total_blueprints: int
