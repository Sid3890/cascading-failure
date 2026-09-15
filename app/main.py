"""Application entry point."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.analytics import router as analytics_router
from app.api.routes.networks import router as networks_router
from app.api.routes.operations import router as operations_router
from app.api.routes.scenarios import router as scenarios_router
from app.api.routes.system import build_system_router
from app.core.config import Settings, get_settings
from app.db.audit_repository import AuditRepository
from app.db.network_repository import ConflictError, NetworkRepository, ResourceNotFoundError
from app.db.simulation_repository import SimulationRepository
from app.services.analytics_service import AnalyticsService


def error_payload(request: Request, code: str, message: str, field: str | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "field": field},
        "request_id": getattr(request.state, "request_id", "unavailable"),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Versioned contract for modeling infrastructure networks and cascading disruption. "
            "Phase 5 supports simulations, analytics, import/export, and operational safeguards."
        ),
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    repository = NetworkRepository(settings.database_path)
    repository.initialize()
    app.state.network_repository = repository
    simulation_repository = SimulationRepository(settings.database_path, repository)
    simulation_repository.initialize()
    app.state.simulation_repository = simulation_repository
    app.state.analytics_service = AnalyticsService(repository, simulation_repository)
    audit_repository = AuditRepository(settings.database_path)
    audit_repository.initialize()
    app.state.audit_repository = audit_repository

    @app.middleware("http")
    async def attach_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        protected_api = request.url.path.startswith("/api/v1") and request.url.path != "/api/v1/openapi.json"
        if settings.api_key and protected_api and request.method != "OPTIONS":
            if request.headers.get("X-API-Key") != settings.api_key:
                response = JSONResponse(
                    status_code=401,
                    content=error_payload(request, "UNAUTHORIZED", "A valid X-API-Key is required."),
                )
                response.headers["X-Request-ID"] = request_id
                return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if protected_api and request.method in {"POST", "PATCH", "DELETE"}:
            try:
                audit_repository.log(
                    request_id=request_id,
                    actor="api_key" if settings.api_key else "anonymous",
                    action=f"{request.method} {request.url.path}",
                    resource_path=request.url.path,
                    status_code=response.status_code,
                )
            except Exception:
                # Auditing must never turn an otherwise successful planner action into an error.
                pass
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, _: Exception) -> JSONResponse:
        # Detailed exceptions should be logged by the hosting platform; never leak them to clients.
        return JSONResponse(
            status_code=500,
            content=error_payload(request, "INTERNAL_ERROR", "An unexpected error occurred."),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "RESOURCE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(request, code, message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first_error = exc.errors()[0] if exc.errors() else {}
        location = first_error.get("loc", [])
        field = str(location[-1]) if location else None
        return JSONResponse(
            status_code=422,
            content=error_payload(request, "VALIDATION_ERROR", "Request validation failed.", field),
        )

    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=error_payload(request, "RESOURCE_NOT_FOUND", str(exc)),
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content=error_payload(request, "CONFLICT", str(exc)))

    app.include_router(build_system_router(settings))
    app.include_router(networks_router)
    app.include_router(scenarios_router)
    app.include_router(analytics_router)
    app.include_router(operations_router)
    return app


app = create_app()
