"""Network, node, and edge management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.db.network_repository import NetworkRepository
from app.schemas.network import (
    EdgeUpdateRequest,
    InfrastructureEdge,
    InfrastructureEdgeInput,
    InfrastructureNode,
    InfrastructureNodeInput,
    NetworkCreateRequest,
    NetworkExportResponse,
    NetworkImportRequest,
    NetworkListResponse,
    NetworkResponse,
    NetworkUpdateRequest,
    NodeUpdateRequest,
)

router = APIRouter(prefix="/api/v1/networks", tags=["networks"])


def repository(request: Request) -> NetworkRepository:
    return request.app.state.network_repository


@router.post("", response_model=NetworkResponse, status_code=status.HTTP_201_CREATED)
async def create_network(request: Request, payload: NetworkCreateRequest) -> NetworkResponse:
    return repository(request).create_network(payload)


@router.get("", response_model=NetworkListResponse)
async def list_networks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NetworkListResponse:
    return repository(request).list_networks(limit=limit, offset=offset)


@router.post("/network-imports", response_model=NetworkResponse, status_code=status.HTTP_201_CREATED)
async def import_network(request: Request, payload: NetworkImportRequest) -> NetworkResponse:
    return repository(request).create_network(payload.network)


@router.get("/{network_id}", response_model=NetworkResponse)
async def get_network(request: Request, network_id: UUID) -> NetworkResponse:
    return repository(request).get_network(network_id)


@router.get("/{network_id}/export", response_model=NetworkExportResponse)
async def export_network(request: Request, network_id: UUID) -> NetworkExportResponse:
    return repository(request).export_network(network_id)


@router.patch("/{network_id}", response_model=NetworkResponse)
async def update_network(
    request: Request, network_id: UUID, payload: NetworkUpdateRequest
) -> NetworkResponse:
    return repository(request).update_network(network_id, payload)


@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_network(request: Request, network_id: UUID) -> Response:
    repository(request).delete_network(network_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{network_id}/nodes", response_model=InfrastructureNode, status_code=status.HTTP_201_CREATED)
async def add_node(
    request: Request, network_id: UUID, payload: InfrastructureNodeInput
) -> InfrastructureNode:
    return repository(request).add_node(network_id, payload)


@router.get("/{network_id}/nodes/{node_id}", response_model=InfrastructureNode)
async def get_node(request: Request, network_id: UUID, node_id: UUID) -> InfrastructureNode:
    return repository(request).get_node(network_id, node_id)


@router.patch("/{network_id}/nodes/{node_id}", response_model=InfrastructureNode)
async def update_node(
    request: Request, network_id: UUID, node_id: UUID, payload: NodeUpdateRequest
) -> InfrastructureNode:
    return repository(request).update_node(network_id, node_id, payload)


@router.delete("/{network_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(request: Request, network_id: UUID, node_id: UUID) -> Response:
    repository(request).delete_node(network_id, node_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{network_id}/edges", response_model=InfrastructureEdge, status_code=status.HTTP_201_CREATED)
async def add_edge(
    request: Request, network_id: UUID, payload: InfrastructureEdgeInput
) -> InfrastructureEdge:
    return repository(request).add_edge(network_id, payload)


@router.get("/{network_id}/edges/{edge_id}", response_model=InfrastructureEdge)
async def get_edge(request: Request, network_id: UUID, edge_id: UUID) -> InfrastructureEdge:
    return repository(request).get_edge(network_id, edge_id)


@router.patch("/{network_id}/edges/{edge_id}", response_model=InfrastructureEdge)
async def update_edge(
    request: Request, network_id: UUID, edge_id: UUID, payload: EdgeUpdateRequest
) -> InfrastructureEdge:
    return repository(request).update_edge(network_id, edge_id, payload)


@router.delete("/{network_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(request: Request, network_id: UUID, edge_id: UUID) -> Response:
    repository(request).delete_edge(network_id, edge_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
