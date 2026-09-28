from celery import Celery
from celery.signals import setup_logging

from slideai.core.config import get_settings
from slideai.core.logging import configure_logging

settings = get_settings()


@setup_logging.connect  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def configure_worker_logging(**_: object) -> None:
    configure_logging(settings.log_level, "slideai-worker")


celery_app = Celery(
    "slideai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "slideai.workers.file_tasks",
        "slideai.workers.outbox_tasks",
        "slideai.workers.workflow_tasks",
    ],
)
celery_app.conf.update(  # pyright: ignore[reportUnknownMemberType]
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "publish-slideai-outbox": {
            "task": "slideai.workers.publish_outbox",
            "schedule": 5.0,
        }
    },
)


@celery_app.task(name="slideai.workers.healthcheck")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
def healthcheck() -> str:
    return "ok"
