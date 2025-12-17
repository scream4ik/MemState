import pytest
from pydantic import BaseModel

from memstate import AsyncInMemoryStorage, AsyncMemoryStore, MemoryStoreError, Operation
from memstate.exceptions import HookError, ValidationFailed


class UserProfile(BaseModel):
    username: str
    age: int
    tags: list[str] = []


@pytest.fixture
def store():
    s = AsyncMemoryStore(AsyncInMemoryStorage())
    s.register_schema("user", UserProfile)
    return s


async def test_update_happy_path(store):
    # 1. Create
    user = UserProfile(username="neo", age=25, tags=["one"])
    fid = await store.commit_model(user)

    # 2. Update
    await store.update(fid, {"payload": {"age": 26}})

    # 3. Check
    updated = await store.get(fid)
    assert updated["payload"]["age"] == 26
    assert updated["payload"]["username"] == "neo"
    assert updated["payload"]["tags"] == ["one"]


async def test_update_non_existent_fact(store):
    with pytest.raises(MemoryStoreError) as excinfo:
        await store.update("non-existent-id", {"payload": {"age": 99}})

    assert "Fact not found" in str(excinfo.value)


async def test_update_enforces_schema_validation(store):
    fid = await store.commit_model(UserProfile(username="neo", age=25))

    with pytest.raises(ValidationFailed):
        await store.update(fid, {"payload": {"age": "i am not a number"}})

    current = await store.get(fid)
    assert current["payload"]["age"] == 25


async def test_update_atomic_rollback_on_hook_failure(store):
    fid = await store.commit_model(UserProfile(username="neo", age=25))

    def failing_hook(op, fid, data):
        if op == Operation.UPDATE:
            raise Exception("Vector DB Connection Timeout")

    store.add_hook(failing_hook)

    with pytest.raises(HookError):
        await store.update(fid, {"payload": {"age": 99}})

    current = await store.get(fid)
    assert current["payload"]["age"] == 25


async def test_update_shallow_merge_behavior(store):
    fid = await store.commit_model(UserProfile(username="neo", age=25, tags=["a", "b"]))

    await store.update(fid, {"payload": {"tags": ["c"]}})

    current = await store.get(fid)
    assert current["payload"]["tags"] == ["c"]
    assert current["payload"]["username"] == "neo"
