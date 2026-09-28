from uuid import UUID


class CeleryFileQueue:
    def enqueue_processing(self, task_id: UUID, file_id: UUID) -> None:
        from slideai.workers.celery_app import celery_app

        celery_app.send_task(  # pyright: ignore[reportUnknownMemberType]
            "slideai.workers.process_source_file", args=[str(task_id), str(file_id)]
        )

    def enqueue_cleanup(self, task_id: UUID, file_id: UUID) -> None:
        from slideai.workers.celery_app import celery_app

        celery_app.send_task(  # pyright: ignore[reportUnknownMemberType]
            "slideai.workers.cleanup_deleted_file", args=[str(task_id), str(file_id)]
        )
