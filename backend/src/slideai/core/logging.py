import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
task_id_context: ContextVar[str | None] = ContextVar("task_id", default=None)
run_id_context: ContextVar[str | None] = ContextVar("run_id", default=None)
workflow_node_context: ContextVar[str | None] = ContextVar("workflow_node", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "slideai-api"),
            "request_id": request_id_context.get(),
            "task_id": task_id_context.get(),
            "run_id": run_id_context.get(),
            "workflow_node": workflow_node_context.get(),
            "event": getattr(record, "event", "log"),
            "duration_ms": getattr(record, "duration_ms", None),
            "error_code": getattr(record, "error_code", None),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO", service: str = "slideai-api") -> None:
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_ServiceFilter(service))
    root.addHandler(handler)
    root.setLevel(level.upper())

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "celery",
        "celery.worker",
        "celery.app.trace",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class _ServiceFilter(logging.Filter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "service"):
            record.service = self._service
        return True
