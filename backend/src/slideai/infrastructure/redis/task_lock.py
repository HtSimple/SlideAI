from secrets import token_urlsafe
from typing import Protocol, cast
from uuid import UUID

from redis.asyncio import Redis

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisCommands(Protocol):
    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> bool | None: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> int: ...


class TaskLock:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 60) -> None:
        if ttl_seconds < 5:
            raise ValueError("Task lock TTL must be at least five seconds.")
        self.redis = cast(RedisCommands, redis)
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def key(task_id: UUID | str) -> str:
        return f"slideai:task-lock:{task_id}"

    async def acquire(self, task_id: UUID | str) -> str | None:
        token = token_urlsafe(24)
        acquired = await self.redis.set(self.key(task_id), token, nx=True, ex=self.ttl_seconds)
        return token if acquired else None

    async def renew(self, task_id: UUID | str, token: str) -> bool:
        result = await self.redis.eval(_RENEW_SCRIPT, 1, self.key(task_id), token, self.ttl_seconds)
        return bool(result)

    async def release(self, task_id: UUID | str, token: str) -> bool:
        result = await self.redis.eval(_RELEASE_SCRIPT, 1, self.key(task_id), token)
        return bool(result)
