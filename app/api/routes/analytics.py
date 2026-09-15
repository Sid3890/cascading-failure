"""Planner-facing resilience analytics endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.schemas.analysis import (
    CriticalityResponse,
    ScenarioComparisonRequest,
    ScenarioComparisonResponse,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1", tags=["analytics"])


def service(request: Request) -> AnalyticsService:
    return request.app.state.analytics_service


@router.get("/networks/{network_id}/criticality", response_model=CriticalityResponse)
async def get_criticality(
    request: Request,
    network_id: UUID,
    metric: Literal["failure_impact", "betweenness", "load_ratio"] = "failure_impact",
    limit: int = Query(default=25, ge=1, le=1000),
) -> CriticalityResponse:
    return service(request).criticality(network_id, metric, limit)


@router.post("/scenario-comparisons", response_model=ScenarioComparisonResponse)
async def compare_scenarios(
    request: Request, payload: ScenarioComparisonRequest
) -> ScenarioComparisonResponse:
    return service(request).compare_scenarios(payload)
