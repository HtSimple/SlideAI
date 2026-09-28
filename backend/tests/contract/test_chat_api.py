from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from slideai.api.dependencies_chat import get_chat_service
from slideai.api.main import create_app
from slideai.domain.changes.models import (
    ChangeRequest,
    ChatMessage,
    ChatResult,
    ChatTarget,
    UndoResult,
)
from slideai.domain.evaluation.models import Revision


class RouteChatService:
    def __init__(self, task_id: UUID) -> None:
        self.task_id = task_id
        self.messages: list[ChatMessage] = []
        self.received = None

    async def history(self, task_id: UUID, *, offset=0, limit=50):
        if task_id != self.task_id:
            from slideai.core.errors import DomainError

            raise DomainError("TASK_NOT_FOUND", "Task was not found.")
        return self.messages[offset : offset + limit]

    async def get_change(self, task_id: UUID, change_id: UUID):
        return next(
            (
                item.change_request
                for item in self.messages
                if item.task_id == task_id
                and item.change_request is not None
                and item.change_request.id == change_id
            ),
            None,
        )

    async def send_message(self, task_id: UUID, *, content, expected_task_version, target=None):
        self.received = (task_id, content, expected_task_version, target)
        now = datetime.now(UTC)
        user = ChatMessage(
            task_id=task_id,
            role="user",
            content=content,
            target=target,
            created_at=now,
        )
        change = ChangeRequest(
            task_id=task_id,
            source_message_id=user.id,
            target_type="slide",
            target_ids=[],
            operation="rewrite",
            instruction=content,
            risk_level="local",
            needs_clarification=True,
            clarification_question="要修改哪一页？",
            impact_scope=[],
            status="NEEDS_CLARIFICATION",
            expected_task_version=expected_task_version,
            created_at=now,
        )
        assistant = ChatMessage(
            task_id=task_id,
            role="assistant",
            content="要修改哪一页？",
            change_request=change,
            created_at=now,
        )
        self.messages.extend([user, assistant])
        return ChatResult(
            task_id=task_id,
            status="NEEDS_CLARIFICATION",
            user_message=user,
            assistant_message=assistant,
            change_request=change,
            task_version=expected_task_version,
        )

    async def confirm_change(self, task_id: UUID, *, change_id, expected_task_version):
        raise AssertionError("Clarification requests cannot be confirmed.")

    async def undo(self, task_id: UUID, *, revision_id, expected_task_version):
        revision = Revision(
            task_id=task_id,
            revision_number=1,
            revision_type="UNDO",
            scope=[],
            reason="撤销修改",
            before_slides=[],
            after_slides=[],
            created_at=datetime.now(UTC),
        )
        message = ChatMessage(
            task_id=task_id,
            role="assistant",
            content="已撤销。",
            revision_id=revision.id,
            created_at=datetime.now(UTC),
        )
        return UndoResult(
            task_id=task_id,
            revision=revision,
            task_version=expected_task_version + 1,
            can_undo=False,
            assistant_message=message,
        )


def _client() -> tuple[TestClient, UUID, RouteChatService]:
    task_id = uuid4()
    service = RouteChatService(task_id)
    app = create_app(readiness_probe=lambda: {"postgres": "ok", "redis": "ok"})
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app), task_id, service


def test_chat_api_saves_messages_and_returns_a_clarification_card() -> None:
    client, task_id, service = _client()
    response = client.post(
        f"/api/v1/tasks/{task_id}/chat/messages",
        json={
            "content": "改得更有说服力",
            "expected_task_version": 8,
            "target": {"target_type": "whole_deck", "label": "整份内容"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "NEEDS_CLARIFICATION"
    assert response.json()["assistant_message"]["content"] == "要修改哪一页？"
    assert service.received == (
        task_id,
        "改得更有说服力",
        8,
        ChatTarget(target_type="whole_deck", label="整份内容"),
    )
    history = client.get(f"/api/v1/tasks/{task_id}/chat/messages")
    assert history.status_code == 200
    assert [item["role"] for item in history.json()["items"]] == ["user", "assistant"]


def test_chat_history_route_keeps_task_scope() -> None:
    client, task_id, _ = _client()

    response = client.get(f"/api/v1/tasks/{uuid4()}/chat/messages")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"
