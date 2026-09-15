"""Request and response DTOs for infrastructure network management."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

AssetType = Literal[
    "road_segment", "bridge", "hospital", "power_substation", "water_pump", "telecom_tower", "other"
]
NodeStatus = Literal["operational", "degraded", "failed"]
RelationType = Literal["physical", "dependency", "flow", "geographic"]
AttributeValue = str | int | float | bool


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90, examples=[12.9716])
    longitude: float = Field(ge=-180, le=180, examples=[77.5946])


class InfrastructureNodeInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=100, examples=["BRG-014"])
    name: str = Field(min_length=1, max_length=200, examples=["Kaveri Bridge"])
    asset_type: AssetType
    capacity: float = Field(gt=0, examples=[2200])
    baseline_load: float = Field(ge=0, examples=[1350])
    location: GeoPoint | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)


class InfrastructureNode(InfrastructureNodeInput):
    id: UUID
    status: NodeStatus = "operational"


class NodeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    asset_type: AssetType | None = None
    capacity: float | None = Field(default=None, gt=0)
    baseline_load: float | None = Field(default=None, ge=0)
    location: GeoPoint | None = None
    attributes: dict[str, AttributeValue] | None = None
    status: NodeStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> "NodeUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class EdgeProperties(BaseModel):
    relation_type: RelationType
    capacity: float | None = Field(default=None, gt=0, examples=[1800])
    baseline_flow: float | None = Field(default=None, ge=0, examples=[900])
    dependency_strength: float | None = Field(default=None, ge=0, le=1, examples=[0.75])
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)


class InfrastructureEdgeInput(EdgeProperties):
    source_node_id: UUID
    target_node_id: UUID


class NetworkEdgeDraftInput(EdgeProperties):
    """Create-time edge reference; uses node external IDs before UUIDs exist."""

    source_external_id: str = Field(min_length=1, max_length=100)
    target_external_id: str = Field(min_length=1, max_length=100)


class InfrastructureEdge(InfrastructureEdgeInput):
    id: UUID


class EdgeUpdateRequest(BaseModel):
    relation_type: RelationType | None = None
    capacity: float | None = Field(default=None, gt=0)
    baseline_flow: float | None = Field(default=None, ge=0)
    dependency_strength: float | None = Field(default=None, ge=0, le=1)
    attributes: dict[str, AttributeValue] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "EdgeUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class NetworkCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Central Bengaluru mobility network"])
    description: str | None = Field(default=None, max_length=2000)
    geographic_scope: str | None = Field(default=None, max_length=200, examples=["Bengaluru CBD"])
    nodes: list[InfrastructureNodeInput] = Field(default_factory=list)
    edges: list[NetworkEdgeDraftInput] = Field(default_factory=list)


class NetworkUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    geographic_scope: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_change(self) -> "NetworkUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class NetworkResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    geographic_scope: str | None
    nodes: list[InfrastructureNode]
    edges: list[InfrastructureEdge]
    created_at: datetime
    updated_at: datetime


class NetworkSummary(BaseModel):
    id: UUID
    name: str
    description: str | None
    geographic_scope: str | None
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class NetworkListResponse(BaseModel):
    items: list[NetworkSummary]
    total: int = Field(ge=0)


class NetworkExportResponse(BaseModel):
    format: Literal["cascading-failure-network/v1"] = "cascading-failure-network/v1"
    exported_at: datetime
    network: NetworkCreateRequest


class NetworkImportRequest(BaseModel):
    format: Literal["cascading-failure-network/v1"]
    network: NetworkCreateRequest
