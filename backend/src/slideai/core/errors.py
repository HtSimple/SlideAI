from dataclasses import dataclass, field
from typing import Any

_HTTP_STATUS_BY_CODE = {
    "TASK_NOT_FOUND": 404,
    "FILE_NOT_FOUND": 404,
    "VERSION_CONFLICT": 409,
    "TASK_CONFLICT": 409,
    "VALIDATION_ERROR": 422,
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
