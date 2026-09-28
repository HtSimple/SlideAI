import json
from hashlib import sha256
from typing import Any

from slideai.application.models.gateway import ModelGateway
from slideai.domain.changes.models import ChangeIntent, ChatTarget
from slideai.domain.content.models import SlideContent
from slideai.domain.tasks.models import TaskRecord


class GatewayChangeParser:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def parse(
        self,
        *,
        task: TaskRecord,
        content: str,
        target: ChatTarget | None,
        slides: list[SlideContent],
    ) -> ChangeIntent:
        outline = task.outline
        payload: dict[str, Any] = {
            "user_message": content,
            "selected_target": target.model_dump(mode="json") if target else None,
            "outline": outline.model_dump(mode="json") if outline else None,
            "slides": [
                {
                    "id": str(slide.id),
                    "page_number": slide.page_number,
                    "section_id": slide.section_id,
                    "outline_item_id": slide.outline_item_id,
                    "title": slide.title,
                }
                for slide in slides
            ],
        }
        result = await self.gateway.invoke_structured(
            task_id=task.id,
            node="parse_change",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "把用户消息解析成 ChangeIntent。目标必须来自给定 task 上下文；"
                        "缺少明确目标或替换内容时设置 needs_clarification 并提出一个具体问题。"
                        "不得提出上下文中不存在的目标 ID。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            output_schema=ChangeIntent,
            preference=task.model_preference,
            complexity=task.complexity,
            idempotency_key=(
                f"{task.id}:chat:{task.version}:parse:{sha256(content.encode()).hexdigest()[:16]}"
            ),
        )
        return result.output
