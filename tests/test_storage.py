from unittest.mock import ANY, Mock

import pytest
from pydantic import BaseModel

from memstate import (
    ConflictError,
    Constraint,
    Fact,
    HookError,
    InMemoryStorage,
    MemoryStore,
    MemoryStoreError,
    ValidationFailed,
)


class User(BaseModel):
    name: str
    age: int


class Config(BaseModel):
    key: str
    value: str


@pytest.fixture
def memory():
    return MemoryStore(InMemoryStorage())


def test_validation_failure(memory):
    memory.register_schema("user", User)

    with pytest.raises(ValidationFailed):
        memory.commit(Fact(type="user", payload={"name": "Bob", "age": "not-a-number"}))


def test_singleton_constraint(memory):
    memory.register_schema("user", User, Constraint(singleton_key="name"))

    id1 = memory.commit(Fact(type="user", payload={"name": "Alice", "age": 20}))
    id2 = memory.commit(Fact(type="user", payload={"name": "Alice", "age": 25}))

    assert id1 == id2  # ID должен сохраниться
    assert memory.get(id1)["payload"]["age"] == 25  # Данные обновились


def test_immutable_constraint_conflict(memory):
    memory.register_schema("config", Config, Constraint(singleton_key="key", immutable=True))

    memory.commit(Fact(type="config", payload={"key": "api_url", "value": "http://v1"}))

    with pytest.raises(ConflictError) as excinfo:
        memory.commit(Fact(type="config", payload={"key": "api_url", "value": "http://v2"}))

    assert "Immutable constraint violation" in str(excinfo.value)


def test_update_non_existent_fact(memory):
    with pytest.raises(MemoryStoreError) as excinfo:
        memory.update("non-existent-id", {"payload": {"age": 99}})

    assert "Fact not found" in str(excinfo.value)


def test_delete_non_existent_fact(memory):
    with pytest.raises(MemoryStoreError):
        memory.delete("ghost-id")


def test_rollback(memory):
    memory.register_schema("user", User)

    fid = memory.commit(Fact(type="user", payload={"name": "Neo", "age": 10}))

    memory.update(fid, {"payload": {"age": 99}})
    assert memory.get(fid)["payload"]["age"] == 99

    memory.rollback(1)

    fact = memory.get(fid)
    assert fact["payload"]["age"] == 10


def test_hooks_called(memory):
    mock_hook = Mock()
    memory.add_hook(mock_hook)

    fid = memory.commit(Fact(type="user", payload={"name": "HookTester", "age": 30}))

    mock_hook.assert_called_with("COMMIT", fid, ANY)

    memory.update(fid, {"payload": {"age": 31}})
    mock_hook.assert_called_with("UPDATE", fid, ANY)

    memory.delete(fid)
    mock_hook.assert_called_with("DELETE", fid, ANY)


def test_hook_failure_raises_error(memory):
    def crashing_hook(op, fid, data):
        raise ValueError("Vector DB is dead")

    memory.add_hook(crashing_hook)

    with pytest.raises(HookError):
        memory.commit(Fact(type="user", payload={"name": "Survivor", "age": 50}))

    facts = memory.query(filters={"payload.name": "Survivor"})
    assert len(facts) == 0


def test_ephemeral_session_discard(memory):
    session_id = "sess-1"

    memory.commit(Fact(type="note", payload={"text": "temp"}, session_id=session_id), ephemeral=True)

    deleted_count = memory.discard_session(session_id)
    assert deleted_count == 1

    remaining = memory.query(filters={"session_id": session_id})
    assert len(remaining) == 0
