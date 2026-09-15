"""Readiness and API-discovery routes available in Phase 1."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import Settings
from app.schemas.common import ApiMetadataResponse, HealthResponse


def build_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=HealthResponse, summary="Check service health")
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="cascading-failure-api",
            version=settings.version,
            timestamp=datetime.now(UTC),
        )

    @router.get(
        "/api/v1/meta",
        response_model=ApiMetadataResponse,
        summary="Discover implemented API capabilities",
    )
    async def api_metadata() -> ApiMetadataResponse:
        return ApiMetadataResponse(
            api_version="v1",
            implementation_phase=5,
            supported_routes=[
                "GET /health",
                "GET /api/v1/meta",
                "GET/POST /api/v1/networks",
                "GET/PATCH/DELETE /api/v1/networks/{network_id}",
                "POST /api/v1/networks/{network_id}/nodes",
                "POST /api/v1/networks/{network_id}/edges",
                "GET/POST /api/v1/scenarios",
                "POST /api/v1/scenarios/{scenario_id}/runs",
                "GET /api/v1/runs/{run_id}/result",
                "GET /api/v1/networks/{network_id}/criticality",
                "POST /api/v1/scenario-comparisons",
                "POST /api/v1/networks/network-imports",
                "GET /api/v1/networks/{network_id}/export",
                "GET /api/v1/audit-events",
            ],
            planned_resources=[],
        )

    return router
