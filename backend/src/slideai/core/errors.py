from dataclasses import dataclass, field
from typing import Any

_HTTP_STATUS_BY_CODE = {
    "TASK_NOT_FOUND": 404,
    "FILE_NOT_FOUND": 404,
    "VERSION_CONFLICT": 409,
    "TASK_CONFLICT": 409,
    "VALIDATION_ERROR": 422,
    "MODEL_AUTHENTICATION_ERROR": 502,
    "MODEL_PROVIDER_ERROR": 502,
    "MODEL_NOT_AVAILABLE": 422,
    "FILE_TOO_LARGE": 413,
    "FILE_TYPE_MISMATCH": 415,
    "FILE_LIMIT_REACHED": 409,
    "FILE_DUPLICATE": 409,
    "FILE_CONFLICT": 409,
    "FILE_CLEANUP_UNAVAILABLE": 503,
    "FILE_QUEUE_UNAVAILABLE": 503,
    "WORKFLOW_QUEUE_UNAVAILABLE": 503,
    "FILES_NOT_READY": 409,
    "REQUIREMENT_INCOMPLETE": 422,
    "OUTLINE_INVALID": 422,
    "CONTENT_NOT_READY": 409,
    "SLIDE_BATCH_INVALID": 422,
    "SLIDE_PAGE_SEQUENCE_INVALID": 422,
    "SLIDE_PLAN_CONFLICT": 409,
    "TASK_SCOPE_VIOLATION": 409,
    "VECTOR_STORE_UNAVAILABLE": 503,
    "VECTOR_SEARCH_FAILED": 503,
    "EMBEDDING_CONFIGURATION_INVALID": 503,
    "EMBEDDING_PROVIDER_ERROR": 502,
}


@dataclass(eq=False)
class DomainError(Exception):
    code: str
    message: str
    details: dict[str, Any] | list[dict[str, Any]] | None = None
    status_code: int | None = None
    _resolved_status_code: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        self._resolved_status_code = self.status_code or _HTTP_STATUS_BY_CODE.get(self.code, 400)

    @property
    def http_status(self) -> int:
        return self._resolved_status_code


class ModelTransientError(Exception):
    def __init__(self, message: str, *, error_type: str = "transient") -> None:
        super().__init__(message)
        self.error_type = error_type


class ModelAuthenticationError(Exception):
    pass


class ModelPermanentError(Exception):
    def __init__(self, message: str, *, error_type: str = "provider_error") -> None:
        super().__init__(message)
        self.error_type = error_type


class ModelOutputValidationError(Exception):
    pass
