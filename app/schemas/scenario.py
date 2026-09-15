"""Stable DTOs for failure scenarios and simulation requests (Phase 3)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

FailureMode = Literal["partial_capacity_loss", "complete_failure"]
TargetKind = Literal["node", "edge"]
RunStatus = Literal["queued", "running", "completed", "failed"]


class FailureEvent(BaseModel):
    target_kind: TargetKind
    target_id: UUID
    mode: FailureMode
    severity: float = Field(ge=0, le=1, examples=[1.0])
    start_step: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_complete_failure_severity(self) -> "FailureEvent":
        if self.mode == "complete_failure" and self.severity != 1:
            raise ValueError("complete_failure requires severity of 1")
        return self


class SimulationParameters(BaseModel):
    max_steps: int = Field(default=20, ge=1, le=500)
    overload_threshold: float = Field(default=1.0, gt=0)
    redistribution_strategy: Literal["proportional", "shortest_path"] = "proportional"


class ScenarioCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Kaveri Bridge closure"])
    network_id: UUID
    failure_events: list[FailureEvent] = Field(min_length=1)
    parameters: SimulationParameters = Field(default_factory=SimulationParameters)


class ScenarioResponse(ScenarioCreateRequest):
    id: UUID
    created_at: datetime


class ScenarioListResponse(BaseModel):
    items: list[ScenarioResponse]
    total: int = Field(ge=0)


class SimulationRunResponse(BaseModel):
    id: UUID
    scenario_id: UUID
    status: RunStatus
    submitted_at: datetime
    completed_at: datetime | None = None
