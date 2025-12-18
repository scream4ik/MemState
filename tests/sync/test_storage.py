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

    assert id1 == id2
    assert memory.get(id1)["payload"]["age"] == 25


def test_immutable_constraint_conflict(memory):
    memory.register_schema("config", Config, Constraint(singleton_key="key", immutable=True))

    memory.commit(Fact(type="config", payload={"key": "api_url", "value": "http://v1"}))

    with pytest.raises(ConflictError) as excinfo:
        memory.commit(Fact(type="config", payload={"key": "api_url", "value": "http://v2"}))

    assert "Immutable constraint violation" in str(excinfo.value)


def test_delete_non_existent_fact(memory):
    with pytest.raises(MemoryStoreError):
        memory.delete(session_id="session_1", fact_id="ghost-id")


def test_rollback(memory):
    memory.register_schema("user", User)

    fid = memory.commit(fact=Fact(type="user", payload={"name": "Neo", "age": 10}), session_id="session_1")

    memory.update(fid, {"payload": {"age": 99}})
    assert memory.get(fid)["payload"]["age"] == 99

    memory.rollback(session_id="session_1", steps=1)

    fact = memory.get(fid)
    assert fact["payload"]["age"] == 10

    logs = memory.storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 1
    assert logs[0]["op"] == "COMMIT"


def test_hooks_called(memory):
    mock_hook = Mock()
    memory.add_hook(mock_hook)

    fid = memory.commit(fact=Fact(type="user", payload={"name": "HookTester", "age": 30}), session_id="session_1")

    mock_hook.assert_called_with("COMMIT", fid, ANY)

    memory.update(fid, {"payload": {"age": 31}})
    mock_hook.assert_called_with("UPDATE", fid, ANY)

    memory.delete(session_id="session_1", fact_id=fid)
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


def test_commit_model_success(memory):
    schema_name = "user_v1"
    memory.register_schema(schema_name, User)

    user = User(name="Survivor", age=50)

    fact_id = memory.commit_model(user, actor="system", session_id="session_1")

    saved_fact = memory.storage.load(fact_id)

    assert saved_fact is not None
    assert saved_fact["type"] == schema_name
    assert saved_fact["payload"] == {"name": "Survivor", "age": 50}

    assert saved_fact["session_id"] == "session_1"


def test_commit_model_raises_on_unregistered(memory):
    unknown = User(name="Survivor", age=50)

    with pytest.raises(MemoryStoreError, match="is not registered"):
        memory.commit_model(unknown)


def test_commit_model_create_vs_update(memory):
    memory.register_schema("user", User)

    user = User(name="Survivor", age=50)
    fid = memory.commit_model(user)

    assert fid is not None
    data_v1 = memory.storage.load(fid)
    assert data_v1["payload"]["name"] == "Survivor"
    assert data_v1["payload"]["age"] == 50

    user_v2 = User(name="Survivor", age=55)

    fid_updated = memory.commit_model(user_v2, fact_id=fid)

    assert fid_updated == fid

    data_v2 = memory.storage.load(fid)
    assert data_v2["payload"]["name"] == "Survivor"
    assert data_v2["payload"]["age"] == 55

    all_facts = memory.storage.query(type_filter="user")
    assert len(all_facts) == 1


def test_commit_model_without_id_creates_duplicate(memory):
    memory.register_schema("user", User)
    user = User(name="Survivor", age=50)

    id1 = memory.commit_model(user)
    id2 = memory.commit_model(user)

    assert id1 != id2
    all_facts = memory.storage.query(type_filter="user")
    assert len(all_facts) == 2
