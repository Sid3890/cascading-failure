"""Failure scenario and simulation-run endpoints."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.db.simulation_repository import SimulationRepository
from app.schemas.analysis import SimulationResultResponse
from app.schemas.scenario import (
    ScenarioCreateRequest,
    ScenarioListResponse,
    ScenarioResponse,
    SimulationRunResponse,
)

router = APIRouter(prefix="/api/v1", tags=["scenarios"])


def repository(request: Request) -> SimulationRepository:
    return request.app.state.simulation_repository


@router.post("/scenarios", response_model=ScenarioResponse, status_code=status.HTTP_201_CREATED)
async def create_scenario(request: Request, payload: ScenarioCreateRequest) -> ScenarioResponse:
    return repository(request).create_scenario(payload)


@router.get("/scenarios", response_model=ScenarioListResponse)
async def list_scenarios(
    request: Request,
    network_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ScenarioListResponse:
    return repository(request).list_scenarios(network_id=network_id, limit=limit, offset=offset)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
async def get_scenario(request: Request, scenario_id: UUID) -> ScenarioResponse:
    return repository(request).get_scenario(scenario_id)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(request: Request, scenario_id: UUID) -> Response:
    repository(request).delete_scenario(scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/scenarios/{scenario_id}/runs",
    response_model=SimulationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_simulation_run(request: Request, scenario_id: UUID) -> SimulationRunResponse:
    return repository(request).create_run(scenario_id)


@router.get("/runs/{run_id}", response_model=SimulationRunResponse)
async def get_simulation_run(request: Request, run_id: UUID) -> SimulationRunResponse:
    return repository(request).get_run(run_id)


@router.get("/runs/{run_id}/result", response_model=SimulationResultResponse)
async def get_simulation_result(request: Request, run_id: UUID) -> SimulationResultResponse:
    return repository(request).get_result(run_id)
