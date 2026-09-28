from dataclasses import dataclass
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
_ACQUIRE_SCRIPT = """
if redis.call('exists', KEYS[1]) ~= 0 then
    return 0
end
local current = tonumber(redis.call('get', KEYS[2]) or '0')
local minimum = tonumber(ARGV[3]) or 0
if current < minimum then
    current = minimum
end
local generation = current + 1
redis.call('set', KEYS[2], generation)
local token = ARGV[1] .. ':' .. tostring(generation)
redis.call('set', KEYS[1], token, 'EX', ARGV[2])
return generation
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisCommands(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> int: ...


@dataclass(frozen=True)
class TaskLease:
    token: str
    generation: int


class TaskLock:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 60) -> None:
        if ttl_seconds < 5:
            raise ValueError("Task lock TTL must be at least five seconds.")
        self.redis = cast(RedisCommands, redis)
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def key(task_id: UUID | str) -> str:
        return f"slideai:task-lock:{task_id}"

    @staticmethod
    def generation_key(task_id: UUID | str) -> str:
        return f"slideai:task-fence:{task_id}"

    async def acquire(
        self, task_id: UUID | str, *, minimum_generation: int = 0
    ) -> TaskLease | None:
        nonce = token_urlsafe(24)
        generation = await self.redis.eval(
            _ACQUIRE_SCRIPT,
            2,
            self.key(task_id),
            self.generation_key(task_id),
            nonce,
            self.ttl_seconds,
            minimum_generation,
        )
        if generation <= 0:
            return None
        return TaskLease(f"{nonce}:{generation}", generation)

    async def renew(self, task_id: UUID | str, token: str | TaskLease) -> bool:
        value = token.token if isinstance(token, TaskLease) else token
        result = await self.redis.eval(_RENEW_SCRIPT, 1, self.key(task_id), value, self.ttl_seconds)
        return bool(result)

    async def release(self, task_id: UUID | str, token: str | TaskLease) -> bool:
        value = token.token if isinstance(token, TaskLease) else token
        result = await self.redis.eval(_RELEASE_SCRIPT, 1, self.key(task_id), value)
        return bool(result)
