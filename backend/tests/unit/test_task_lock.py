from uuid import uuid4

import pytest

from slideai.infrastructure.redis.task_lock import TaskLock


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> bool:
        if nx and name in self.values:
            return False
        self.values[name] = value
        self.expirations[name] = ex
        return True

    async def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> int:
        if numkeys == 2:
            lock_key, generation_key, nonce, ttl, minimum = keys_and_args
            lock_key = str(lock_key)
            generation_key = str(generation_key)
            if lock_key in self.values:
                return 0
            generation = max(int(self.values.get(generation_key, "0")), int(minimum)) + 1
            self.values[generation_key] = str(generation)
            self.values[lock_key] = f"{nonce}:{generation}"
            self.expirations[lock_key] = int(ttl)
            return generation
        assert numkeys == 1
        key, token, *args = keys_and_args
        if self.values.get(str(key)) != str(token):
            return 0
        if "expire" in script:
            self.expirations[str(key)] = int(args[0])
        else:
            del self.values[str(key)]
        return 1


@pytest.mark.asyncio
async def test_task_lock_renews_and_releases_only_the_current_owner() -> None:
    redis = MemoryRedis()
    lock = TaskLock(redis, ttl_seconds=12)  # type: ignore[arg-type]
    task_id = uuid4()

    owner = await lock.acquire(task_id)
    assert owner is not None
    assert await lock.acquire(task_id) is None
    assert await lock.renew(task_id, "another-owner") is False
    assert await lock.renew(task_id, owner) is True
    assert redis.expirations[lock.key(task_id)] == 12
    assert await lock.release(task_id, "another-owner") is False
    assert await lock.release(task_id, owner) is True
    successor = await lock.acquire(task_id, minimum_generation=owner.generation)
    assert successor is not None
    assert successor.generation > owner.generation
