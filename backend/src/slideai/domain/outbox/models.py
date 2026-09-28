from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OutboxEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    event_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    created_at: datetime
