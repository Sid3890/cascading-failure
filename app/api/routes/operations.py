"""Operational audit-log API used for prototype oversight."""

from fastapi import APIRouter, Query, Request

from app.db.audit_repository import AuditRepository
from app.schemas.common import AuditEventListResponse

router = APIRouter(prefix="/api/v1", tags=["operations"])


def repository(request: Request) -> AuditRepository:
    return request.app.state.audit_repository


@router.get("/audit-events", response_model=AuditEventListResponse)
async def list_audit_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AuditEventListResponse:
    return repository(request).list_events(limit=limit, offset=offset)
