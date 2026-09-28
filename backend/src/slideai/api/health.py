from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])
ReadinessProbe = Callable[[], dict[str, str] | Awaitable[dict[str, str]]]


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
async def readiness(request: Request) -> JSONResponse:
    probe: ReadinessProbe = request.app.state.readiness_probe
    result = probe()
    if isinstance(result, Awaitable):
        dependencies = await result
    else:
        dependencies = result

    ready = all(value == "ok" for value in dependencies.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "dependencies": dependencies,
        },
    )
