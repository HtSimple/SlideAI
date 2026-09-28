import logging

from fastapi.testclient import TestClient

from slideai.api.main import create_app
from slideai.core.config import Settings
from slideai.core.errors import DomainError
from slideai.core.logging import JsonFormatter


def test_liveness_does_not_require_dependencies() -> None:
    def dependencies_must_not_be_checked() -> dict[str, str]:
        raise AssertionError("liveness must not probe dependencies")

    client = TestClient(create_app(readiness_probe=dependencies_must_not_be_checked))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_dependency_failure() -> None:
    client = TestClient(
        create_app(
            readiness_probe=lambda: {
                "postgres": "unavailable",
                "redis": "ok",
                "configuration": "ok",
            }
        )
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {
            "postgres": "unavailable",
            "redis": "ok",
            "configuration": "ok",
        },
    }


def test_domain_error_uses_stable_envelope_and_request_id() -> None:
    app = create_app()

    @app.get("/test/domain-error")
    def raise_domain_error() -> None:
        raise DomainError(
            code="TASK_NOT_FOUND",
            message="Task was not found.",
            details={"task_id": "missing-task"},
        )

    client = TestClient(app)
    response = client.get("/test/domain-error", headers={"X-Request-ID": "request-test-123"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "request-test-123"
    assert response.json() == {
        "error": {
            "code": "TASK_NOT_FOUND",
            "message": "Task was not found.",
            "details": {"task_id": "missing-task"},
            "request_id": "request-test-123",
        }
    }


def test_cors_only_exposes_configured_frontend_origins() -> None:
    client = TestClient(
        create_app(
            Settings(cors_origins="http://allowed.example", _env_file=None),
            readiness_probe=lambda: {"postgres": "ok", "redis": "ok", "chroma": "ok"},
        )
    )
    headers = {
        "Origin": "http://allowed.example",
        "Access-Control-Request-Method": "GET",
    }

    allowed = client.options("/api/v1/tasks", headers=headers)
    blocked = client.options(
        "/api/v1/tasks",
        headers={**headers, "Origin": "http://untrusted.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://allowed.example"
    assert "access-control-allow-origin" not in blocked.headers


def test_json_logs_exclude_secrets_prompts_and_exception_text() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        "slideai.security",
        logging.ERROR,
        __file__,
        1,
        "provider key=%s document=%s",
        ("secret-token-123", "private customer report"),
        ValueError("Authorization: Bearer leaked-secret"),
    )
    record.api_key = "secret-token-123"
    record.prompt = "private customer report"

    output = formatter.format(record)

    assert "secret-token-123" not in output
    assert "private customer report" not in output
    assert "leaked-secret" not in output
