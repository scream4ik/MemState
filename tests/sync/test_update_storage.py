import pytest
from pydantic import BaseModel

from memstate import InMemoryStorage, MemoryStore, MemoryStoreError, Operation
from memstate.exceptions import HookError, ValidationFailed


class UserProfile(BaseModel):
    username: str
    age: int
    tags: list[str] = []


@pytest.fixture
def store():
    s = MemoryStore(InMemoryStorage())
    s.register_schema("user", UserProfile)
    return s


def test_update_happy_path(store):
    # 1. Create
    user = UserProfile(username="neo", age=25, tags=["one"])
    fid = store.commit_model(user)

    # 2. Update
    store.update(fid, {"payload": {"age": 26}})

    # 3. Check
    updated = store.get(fid)
    assert updated["payload"]["age"] == 26
    assert updated["payload"]["username"] == "neo"
    assert updated["payload"]["tags"] == ["one"]


def test_update_non_existent_fact(store):
    with pytest.raises(MemoryStoreError) as excinfo:
        store.update("non-existent-id", {"payload": {"age": 99}})

    assert "Fact not found" in str(excinfo.value)


def test_update_enforces_schema_validation(store):
    fid = store.commit_model(UserProfile(username="neo", age=25))

    with pytest.raises(ValidationFailed):
        store.update(fid, {"payload": {"age": "i am not a number"}})

    current = store.get(fid)
    assert current["payload"]["age"] == 25


def test_update_atomic_rollback_on_hook_failure(store):
    fid = store.commit_model(UserProfile(username="neo", age=25))

    def failing_hook(op, fid, data):
        if op == Operation.UPDATE:
            raise Exception("Vector DB Connection Timeout")

    store.add_hook(failing_hook)

    with pytest.raises(HookError):
        store.update(fid, {"payload": {"age": 99}})

    current = store.get(fid)
    assert current["payload"]["age"] == 25


def test_update_shallow_merge_behavior(store):
    fid = store.commit_model(UserProfile(username="neo", age=25, tags=["a", "b"]))

    store.update(fid, {"payload": {"tags": ["c"]}})

    current = store.get(fid)
    assert current["payload"]["tags"] == ["c"]
    assert current["payload"]["username"] == "neo"
