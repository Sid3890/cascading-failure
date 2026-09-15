"""Schemas shared by all API routes."""

from datetime import datetime

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """A machine-readable API error."""

    code: str = Field(examples=["RESOURCE_NOT_FOUND"])
    message: str = Field(examples=["The requested network does not exist."])
    field: str | None = Field(default=None, examples=["network_id"])


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str = Field(examples=["e51d5b8c-7608-4a32-84f4-c0918df00b24"])


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str = Field(examples=["cascading-failure-api"])
    version: str = Field(examples=["0.1.0"])
    timestamp: datetime


class ApiMetadataResponse(BaseModel):
    api_version: str = Field(examples=["v1"])
    implementation_phase: int = Field(examples=[1])
    supported_routes: list[str] = Field(
        examples=[["GET /health", "GET /api/v1/meta"]]
    )
    planned_resources: list[str] = Field(
        examples=[["networks", "scenarios", "simulation-runs", "analytics"]]
    )


class AuditEvent(BaseModel):
    id: str
    occurred_at: datetime
    request_id: str
    actor: str
    action: str
    resource_path: str
    status_code: int


class AuditEventListResponse(BaseModel):
    items: list[AuditEvent]
    total: int = Field(ge=0)
