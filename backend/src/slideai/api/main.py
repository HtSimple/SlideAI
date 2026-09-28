import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from slideai.api.health import ReadinessProbe
from slideai.api.health import router as health_router
from slideai.api.v1.tasks import router as tasks_router
from slideai.application.models.gateway import ModelGateway, OpenAICompatibleProvider
from slideai.application.tasks.service import TaskService
from slideai.core.config import Settings, get_settings
from slideai.core.errors import DomainError
from slideai.core.logging import configure_logging, request_id_context
from slideai.domain.models.catalog import ModelCatalog
from slideai.infrastructure.db.session import create_engine
from slideai.infrastructure.db.task_repository import SqlTaskRepository
from slideai.infrastructure.redis.task_lock import TaskLock

logger = logging.getLogger("slideai.api")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


async def _dependency_probe(engine: AsyncEngine, redis_client: Redis) -> dict[str, str]:
    dependencies = {"postgres": "unavailable", "redis": "unavailable", "configuration": "ok"}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        dependencies["postgres"] = "ok"
    except Exception:
        logger.warning("readiness dependency failed", extra={"event": "readiness.postgres_failed"})

    try:
        await redis_client.ping()  # pyright: ignore[reportUnknownMemberType]
        dependencies["redis"] = "ok"
    except Exception:
        logger.warning("readiness dependency failed", extra={"event": "readiness.redis_failed"})

    return dependencies


def _error_body(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | list[dict[str, Any]] | None,
    request_id: str,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def create_app(
    settings: Settings | None = None,
    *,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    configured = settings or get_settings()
    configure_logging(configured.log_level, configured.service_name)
    engine = create_engine(configured)
    redis_client = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        configured.redis_url, decode_responses=True
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    task_repository = SqlTaskRepository(session_factory)
    model_catalog = ModelCatalog.from_yaml(configured.model_catalog_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await engine.dispose()
        await redis_client.aclose()

    app = FastAPI(
        title="SlideAI API",
        description="Local presentation text generation workbench API.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.readiness_probe = readiness_probe or (lambda: _dependency_probe(engine, redis_client))
    app.state.settings = configured
    app.state.task_repository = task_repository
    app.state.task_service = TaskService(task_repository, model_catalog=model_catalog)
    app.state.model_catalog = model_catalog
    app.state.model_gateway = ModelGateway(
        model_catalog=model_catalog,
        providers={"openai_compatible": OpenAICompatibleProvider()},
        audit_writer=task_repository.record_model_call,
        retries=configured.model_retry_count,
    )
    app.state.task_lock = TaskLock(redis_client)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "If-Match"],
        expose_headers=["X-Request-ID", "ETag"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        incoming_id = request.headers.get("X-Request-ID", "")
        request_id = incoming_id if _REQUEST_ID_PATTERN.fullmatch(incoming_id) else str(uuid4())
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_context.reset(context_token)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=error.http_status,
            content=_error_body(
                code=error.code,
                message=error.message,
                details=error.details,
                request_id=request_id,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                details=details,
                request_id=request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        logger.error(
            "request failed",
            extra={
                "event": "api.unhandled_error",
                "error_code": "INTERNAL_ERROR",
                "exception_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=500,
            content=_error_body(
                code="INTERNAL_ERROR",
                message="An unexpected server error occurred.",
                details=None,
                request_id=request_id,
            ),
        )

    app.include_router(health_router)
    app.include_router(tasks_router)
    return app


app = create_app()
