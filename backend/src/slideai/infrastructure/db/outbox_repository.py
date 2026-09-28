import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from slideai.domain.outbox.models import OutboxEvent
from slideai.infrastructure.db.models import OutboxEventRow

logger = logging.getLogger("slideai.outbox")
OutboxPublisher = Callable[[UUID, str, UUID, dict[str, Any]], None]


class SqlOutboxRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def publish_pending(self, publish: OutboxPublisher, *, limit: int = 50) -> int:
        if limit < 1:
            return 0
        published = 0
        async with self.sessions() as session, session.begin():
            rows = (
                await session.scalars(
                    select(OutboxEventRow)
                    .where(OutboxEventRow.published_at.is_(None))
                    .order_by(OutboxEventRow.created_at, OutboxEventRow.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                event = OutboxEvent(
                    id=row.id,
                    event_type=row.event_type,
                    aggregate_id=row.aggregate_id,
                    payload=row.payload,
                    created_at=row.created_at,
                )
                try:
                    publish(event.id, event.event_type, event.aggregate_id, event.payload)
                except Exception as error:
                    logger.warning(
                        "outbox event publish failed",
                        extra={
                            "event": "outbox.publish_failed",
                            "event_type": event.event_type,
                            "error_type": type(error).__name__,
                        },
                    )
                    break
                row.published_at = datetime.now(UTC)
                published += 1
        return published
