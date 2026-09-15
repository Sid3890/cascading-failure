"""Stable result DTOs for simulation and resilience analytics (Phases 3–4)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class StepImpact(BaseModel):
    step: int = Field(ge=0)
    newly_failed_node_ids: list[UUID]
    newly_failed_edge_ids: list[UUID]
    affected_demand: float = Field(ge=0)
    network_service_ratio: float = Field(ge=0, le=1)


class SimulationResultResponse(BaseModel):
    run_id: UUID
    final_status: Literal["completed", "failed"]
    failed_node_ids: list[UUID]
    failed_edge_ids: list[UUID]
    affected_demand: float = Field(ge=0)
    service_loss_ratio: float = Field(ge=0, le=1)
    cascade_steps: list[StepImpact]


class AssetCriticality(BaseModel):
    asset_id: UUID
    asset_kind: Literal["node", "edge"]
    asset_name: str
    criticality_score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    rationale: str


class CriticalityResponse(BaseModel):
    network_id: UUID
    metric: Literal["failure_impact", "betweenness", "load_ratio"]
    assets: list[AssetCriticality]


class ScenarioComparisonRequest(BaseModel):
    scenario_ids: list[UUID] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def require_distinct_scenarios(self) -> "ScenarioComparisonRequest":
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must not contain duplicates")
        return self


class ScenarioComparisonItem(BaseModel):
    scenario_id: UUID
    run_id: UUID
    rank: int = Field(ge=1)
    failed_node_count: int = Field(ge=0)
    failed_edge_count: int = Field(ge=0)
    affected_demand: float = Field(ge=0)
    service_loss_ratio: float = Field(ge=0, le=1)
    cascade_step_count: int = Field(ge=0)


class ScenarioComparisonResponse(BaseModel):
    network_id: UUID
    ranking_metric: Literal["service_loss_ratio"] = "service_loss_ratio"
    least_impact_scenario_id: UUID | None
    evaluated_at: datetime
    scenarios: list[ScenarioComparisonItem]
