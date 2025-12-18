import uuid
from datetime import datetime, timezone

import fakeredis
import pytest
from testcontainers.postgres import PostgresContainer

from memstate import AsyncInMemoryStorage, AsyncSQLiteStorage
from memstate.backends.postgres import AsyncPostgresStorage
from memstate.backends.redis import AsyncRedisStorage


@pytest.fixture(params=["inmemory", "sqlite", "redis", "postgres"])
async def storage(request, tmp_path):
    if request.param == "inmemory":
        yield AsyncInMemoryStorage()

    elif request.param == "sqlite":
        db_path = tmp_path / "test.db"
        store = AsyncSQLiteStorage(str(db_path))
        await store.connect()
        yield store
        await store.close()

    elif request.param == "redis":
        yield AsyncRedisStorage(fakeredis.FakeAsyncRedis(decode_responses=True))

    elif request.param == "postgres":
        with PostgresContainer("postgres:18-alpine") as postgres:
            url = postgres.get_connection_url().replace("psycopg2", "psycopg")
            store = AsyncPostgresStorage(url)
            await store.create_tables()
            yield store
            await store.close()


async def test_crud_lifecycle(storage):
    uid = str(uuid.uuid4())
    data = {
        "id": uid,
        "type": "test",
        "payload": {"foo": "bar", "count": 1},
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Create
    await storage.save(data)
    loaded = await storage.load(uid)
    assert loaded == data

    # 2. Update
    data["payload"]["foo"] = "baz"
    data["payload"]["count"] = 2
    await storage.save(data)

    loaded_updated = await storage.load(uid)
    assert loaded_updated["payload"]["foo"] == "baz"
    assert loaded_updated["payload"]["count"] == 2

    # 3. Delete
    await storage.delete(uid)
    assert await storage.load(uid) is None


async def test_query_filters_simple(storage):
    await storage.save(
        {"id": "1", "type": "user", "payload": {"role": "admin"}, "ts": datetime.now(timezone.utc).isoformat()}
    )
    await storage.save(
        {"id": "2", "type": "user", "payload": {"role": "guest"}, "ts": datetime.now(timezone.utc).isoformat()}
    )
    await storage.save(
        {"id": "3", "type": "system", "payload": {"role": "admin"}, "ts": datetime.now(timezone.utc).isoformat()}
    )

    # Filter by Type
    res = await storage.query(type_filter="user")
    assert len(res) == 2
    ids = sorted([r["id"] for r in res])
    assert ids == ["1", "2"]

    # Filter by JSON Field
    res = await storage.query(json_filters={"payload.role": "admin"})
    assert len(res) == 2  # id 1 and 3

    # Combined
    res = await storage.query(type_filter="user", json_filters={"payload.role": "admin"})
    assert len(res) == 1
    assert res[0]["id"] == "1"


async def test_query_filters_nested_and_types(storage):
    await storage.save(
        {"id": "deep_1", "type": "config", "payload": {"settings": {"ui": {"dark_mode": True}, "retries": 5}}}
    )

    # 1. Nested Boolean
    res = await storage.query(json_filters={"payload.settings.ui.dark_mode": True})
    assert len(res) == 1
    assert res[0]["id"] == "deep_1"

    # 2. Nested Integer
    res = await storage.query(json_filters={"payload.settings.retries": 5})
    assert len(res) == 1

    # 3. Miss (Wrong Value)
    res = await storage.query(json_filters={"payload.settings.retries": 999})
    assert len(res) == 0


async def test_transaction_log_pagination(storage):
    for i in range(5):
        await storage.append_tx(
            {"session_id": "session_1", "uuid": f"tx_{i}", "seq": i, "ts": datetime.now().isoformat()}
        )

    # 1. Get All (limit default)
    logs = await storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 5
    assert logs[0]["uuid"] == "tx_4"
    assert logs[-1]["uuid"] == "tx_0"

    # 2. Pagination (Limit)
    logs_limit = await storage.get_tx_log(session_id="session_1", limit=2)
    assert len(logs_limit) == 2
    assert logs_limit[0]["uuid"] == "tx_4"
    assert logs_limit[1]["uuid"] == "tx_3"

    # 3. Pagination (Offset)
    logs_offset = await storage.get_tx_log(session_id="session_1", limit=2, offset=2)
    assert len(logs_offset) == 2
    assert logs_offset[0]["uuid"] == "tx_2"
    assert logs_offset[1]["uuid"] == "tx_1"


async def test_session_cleanup(storage):
    await storage.save({"id": "s1", "type": "chat", "session_id": "session_A", "payload": {}})
    await storage.save({"id": "s2", "type": "chat", "session_id": "session_A", "payload": {}})
    await storage.save({"id": "ltm1", "type": "fact", "payload": {}})
    await storage.save({"id": "s3", "type": "chat", "session_id": "session_B", "payload": {}})

    deleted_ids = await storage.delete_session("session_A")

    assert set(deleted_ids) == {"s1", "s2"}
    assert await storage.load("s1") is None
    assert await storage.load("s2") is None
    assert await storage.load("ltm1") is not None
    assert await storage.load("s3") is not None


async def test_delete_txs(storage):
    for i in range(1, 4):
        await storage.append_tx(
            {"session_id": "session_1", "seq": i, "uuid": f"t{i}", "op": "COMMIT", "ts": datetime.now().isoformat()}
        )

    logs = await storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 3
    assert logs[0]["uuid"] == "t3"

    await storage.delete_txs(["t3"])

    logs = await storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 2
    assert logs[0]["uuid"] == "t2"
    assert logs[1]["uuid"] == "t1"

    await storage.delete_txs(["t1", "t2"])

    logs = await storage.get_tx_log(session_id="session_1", limit=10)
    assert len(logs) == 0


async def test_get_session_facts(storage):
    ts = datetime.now(timezone.utc).isoformat()

    await storage.save({"id": "a1", "type": "msg", "session_id": "session_A", "payload": {"val": 1}, "ts": ts})
    await storage.save({"id": "a2", "type": "msg", "session_id": "session_A", "payload": {"val": 2}, "ts": ts})

    await storage.save({"id": "b1", "type": "msg", "session_id": "session_B", "payload": {"val": 3}, "ts": ts})

    await storage.save({"id": "g1", "type": "config", "payload": {"val": 0}, "ts": ts})

    facts_a = await storage.get_session_facts("session_A")
    assert len(facts_a) == 2
    ids_a = sorted([f["id"] for f in facts_a])
    assert ids_a == ["a1", "a2"]

    facts_b = await storage.get_session_facts("session_B")
    assert len(facts_b) == 1
    assert facts_b[0]["id"] == "b1"

    facts_empty = await storage.get_session_facts("ghost_session")
    assert facts_empty == []
