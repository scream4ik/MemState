import fakeredis
import pytest

from memstate import InMemoryStorage, SQLiteStorage
from memstate.backends.redis import RedisStorage


@pytest.fixture(params=["inmemory", "sqlite", "redis"])
def storage(request, tmp_path):
    if request.param == "inmemory":
        return InMemoryStorage()

    elif request.param == "sqlite":
        db_path = tmp_path / "test.db"
        return SQLiteStorage(str(db_path))

    elif request.param == "redis":
        return RedisStorage(fakeredis.FakeRedis(decode_responses=True))


def test_crud_lifecycle(storage):
    data = {"id": "1", "type": "test", "payload": {"foo": "bar"}, "ts": "2023-01-01"}

    storage.save(data)
    loaded = storage.load("1")
    assert loaded == data

    data["payload"]["foo"] = "baz"
    storage.save(data)
    loaded_updated = storage.load("1")
    assert loaded_updated["payload"]["foo"] == "baz"

    storage.delete("1")
    assert storage.load("1") is None


def test_query_filters(storage):
    storage.save({"id": "1", "type": "A", "payload": {"x": 10}, "ts": "2023-01-01"})
    storage.save({"id": "2", "type": "A", "payload": {"x": 20}, "ts": "2023-01-01"})
    storage.save({"id": "3", "type": "B", "payload": {"x": 10}, "ts": "2023-01-01"})

    res = storage.query(type_filter="A")
    assert len(res) == 2

    res = storage.query(json_filters={"payload.x": 10})
    assert len(res) == 2  # id=1 and id=3


def test_transaction_log(storage):
    tx1 = {"uuid": "t1", "ts": "2023-01-01", "op": "COMMIT"}
    tx2 = {"uuid": "t2", "ts": "2023-01-02", "op": "UPDATE"}

    storage.append_tx(tx1)
    storage.append_tx(tx2)

    logs = storage.get_tx_log(limit=10)
    assert logs[0]["uuid"] == "t2"
    assert logs[1]["uuid"] == "t1"
