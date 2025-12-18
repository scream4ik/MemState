import uuid
from datetime import datetime, timezone

import fakeredis
import pytest
from testcontainers.postgres import PostgresContainer

from memstate import InMemoryStorage, SQLiteStorage
from memstate.backends.postgres import PostgresStorage
from memstate.backends.redis import RedisStorage


@pytest.fixture(params=["inmemory", "sqlite", "redis", "postgres"])
def storage(request, tmp_path):
    if request.param == "inmemory":
        yield InMemoryStorage()

    elif request.param == "sqlite":
        db_path = tmp_path / "test.db"
        yield SQLiteStorage(str(db_path))

    elif request.param == "redis":
        yield RedisStorage(fakeredis.FakeRedis(decode_responses=True))

    elif request.param == "postgres":
        with PostgresContainer("postgres:18-alpine") as postgres:
            url = postgres.get_connection_url().replace("psycopg2", "psycopg")
            yield PostgresStorage(url)


def test_crud_lifecycle(storage):
    uid = str(uuid.uuid4())
    data = {
        "id": uid,
        "type": "test",
        "payload": {"foo": "bar", "count": 1},
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Create
    storage.save(data)
    loaded = storage.load(uid)
    assert loaded == data

    # 2. Update
    data["payload"]["foo"] = "baz"
    data["payload"]["count"] = 2
    storage.save(data)

    loaded_updated = storage.load(uid)
    assert loaded_updated["payload"]["foo"] == "baz"
    assert loaded_updated["payload"]["count"] == 2

    # 3. Delete
    storage.delete(uid)
    assert storage.load(uid) is None


def test_query_filters_simple(storage):
    storage.save(
        {"id": "1", "type": "user", "payload": {"role": "admin"}, "ts": datetime.now(timezone.utc).isoformat()}
    )
    storage.save(
        {"id": "2", "type": "user", "payload": {"role": "guest"}, "ts": datetime.now(timezone.utc).isoformat()}
    )
    storage.save(
        {"id": "3", "type": "system", "payload": {"role": "admin"}, "ts": datetime.now(timezone.utc).isoformat()}
    )

    # Filter by Type
    res = storage.query(type_filter="user")
    assert len(res) == 2
    ids = sorted([r["id"] for r in res])
    assert ids == ["1", "2"]

    # Filter by JSON Field
    res = storage.query(json_filters={"payload.role": "admin"})
    assert len(res) == 2  # id 1 and 3

    # Combined
    res = storage.query(type_filter="user", json_filters={"payload.role": "admin"})
    assert len(res) == 1
    assert res[0]["id"] == "1"


def test_query_filters_nested_and_types(storage):
    storage.save({"id": "deep_1", "type": "config", "payload": {"settings": {"ui": {"dark_mode": True}, "retries": 5}}})

    # 1. Nested Boolean
    res = storage.query(json_filters={"payload.settings.ui.dark_mode": True})
    assert len(res) == 1
    assert res[0]["id"] == "deep_1"

    # 2. Nested Integer
    res = storage.query(json_filters={"payload.settings.retries": 5})
    assert len(res) == 1

    # 3. Miss (Wrong Value)
    res = storage.query(json_filters={"payload.settings.retries": 999})
    assert len(res) == 0


def test_transaction_log_pagination(storage):
    for i in range(5):
        storage.append_tx({"session_id": "session_1", "uuid": f"tx_{i}", "seq": i, "ts": datetime.now().isoformat()})

    # 1. Get All (limit default)
    logs = storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 5
    assert logs[0]["uuid"] == "tx_4"
    assert logs[-1]["uuid"] == "tx_0"

    # 2. Pagination (Limit)
    logs_limit = storage.get_tx_log(session_id="session_1", limit=2)
    assert len(logs_limit) == 2
    assert logs_limit[0]["uuid"] == "tx_4"
    assert logs_limit[1]["uuid"] == "tx_3"

    # 3. Pagination (Offset)
    logs_offset = storage.get_tx_log(session_id="session_1", limit=2, offset=2)
    assert len(logs_offset) == 2
    assert logs_offset[0]["uuid"] == "tx_2"
    assert logs_offset[1]["uuid"] == "tx_1"


def test_session_cleanup(storage):
    storage.save({"id": "s1", "type": "chat", "session_id": "session_A", "payload": {}})
    storage.save({"id": "s2", "type": "chat", "session_id": "session_A", "payload": {}})
    storage.save({"id": "ltm1", "type": "fact", "payload": {}})
    storage.save({"id": "s3", "type": "chat", "session_id": "session_B", "payload": {}})

    deleted_ids = storage.delete_session("session_A")

    assert set(deleted_ids) == {"s1", "s2"}
    assert storage.load("s1") is None
    assert storage.load("s2") is None
    assert storage.load("ltm1") is not None
    assert storage.load("s3") is not None


def test_delete_txs(storage):
    for i in range(1, 4):
        storage.append_tx(
            {"session_id": "session_1", "seq": i, "uuid": f"t{i}", "op": "COMMIT", "ts": datetime.now().isoformat()}
        )

    logs = storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 3
    assert logs[0]["uuid"] == "t3"

    storage.delete_txs(["t3"])

    logs = storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 2
    assert logs[0]["uuid"] == "t2"
    assert logs[1]["uuid"] == "t1"

    storage.delete_txs(["t1", "t2"])

    logs = storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 0


def test_get_session_facts(storage):
    ts = datetime.now(timezone.utc).isoformat()

    storage.save({"id": "a1", "type": "msg", "session_id": "session_A", "payload": {"val": 1}, "ts": ts})
    storage.save({"id": "a2", "type": "msg", "session_id": "session_A", "payload": {"val": 2}, "ts": ts})

    storage.save({"id": "b1", "type": "msg", "session_id": "session_B", "payload": {"val": 3}, "ts": ts})

    storage.save({"id": "g1", "type": "config", "payload": {"val": 0}, "ts": ts})

    facts_a = storage.get_session_facts("session_A")
    assert len(facts_a) == 2
    ids_a = sorted([f["id"] for f in facts_a])
    assert ids_a == ["a1", "a2"]

    facts_b = storage.get_session_facts("session_B")
    assert len(facts_b) == 1
    assert facts_b[0]["id"] == "b1"

    facts_empty = storage.get_session_facts("ghost_session")
    assert facts_empty == []
