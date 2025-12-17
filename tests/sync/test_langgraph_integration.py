import pytest

langgraph = pytest.importorskip("langgraph")

from memstate import InMemoryStorage, MemoryStore
from memstate.integrations.langgraph import MemStateCheckpointer


@pytest.fixture
def memory():
    return MemoryStore(InMemoryStorage())


@pytest.fixture
def checkpointer(memory):
    return MemStateCheckpointer(memory=memory)


def create_config(thread_id: str):
    return {"configurable": {"thread_id": thread_id}}


def create_checkpoint(ts: str, content: str):
    return {
        "v": 1,
        "id": ts,
        "ts": ts,
        "channel_values": {"messages": [content]},
        "channel_versions": {},
        "versions_seen": {},
        "pending_sends": [],
    }


def create_metadata():
    return {"source": "test", "step": 1, "writes": {}, "parents": {}}


def test_put_and_get_tuple(checkpointer):
    thread_id = "t1"
    config = create_config(thread_id)

    cp_1 = create_checkpoint("ts-1", "Hello")
    checkpointer.put(config, cp_1, create_metadata(), {})

    tuple_result = checkpointer.get_tuple(config)

    assert tuple_result is not None
    assert tuple_result.checkpoint["id"] == "ts-1"
    assert tuple_result.checkpoint["channel_values"]["messages"] == ["Hello"]
    assert tuple_result.config["configurable"]["thread_id"] == thread_id


def test_get_tuple_returns_latest(checkpointer):
    config = create_config("t1")

    checkpointer.put(config, create_checkpoint("ts-1", "v1"), create_metadata(), {})
    checkpointer.put(config, create_checkpoint("ts-2", "v2"), create_metadata(), {})
    checkpointer.put(config, create_checkpoint("ts-3", "v3"), create_metadata(), {})

    result = checkpointer.get_tuple(config)

    assert result.checkpoint["id"] == "ts-3"
    assert result.checkpoint["channel_values"]["messages"] == ["v3"]


def test_time_travel(checkpointer):
    config = create_config("t1")

    checkpointer.put(config, create_checkpoint("ts-1", "v1"), create_metadata(), {})
    checkpointer.put(config, create_checkpoint("ts-2", "v2"), create_metadata(), {})

    historical_config = {"configurable": {"thread_id": "t1", "thread_ts": "ts-1"}}

    result = checkpointer.get_tuple(historical_config)

    assert result is not None
    assert result.checkpoint["id"] == "ts-1"
    assert result.checkpoint["channel_values"]["messages"] == ["v1"]


def test_list_history(checkpointer):
    config = create_config("t1")

    for i in range(5):
        cp = create_checkpoint(f"ts-{i}", f"msg-{i}")
        checkpointer.put(config, cp, create_metadata(), {})

    history = list(checkpointer.list(config))

    assert len(history) == 5
    assert history[0].checkpoint["id"] == "ts-4"
    assert history[-1].checkpoint["id"] == "ts-0"


def test_thread_isolation(checkpointer):
    config_a = create_config("thread-A")
    config_b = create_config("thread-B")

    checkpointer.put(config_a, create_checkpoint("ts-A", "Data A"), create_metadata(), {})

    result = checkpointer.get_tuple(config_b)

    assert result is None


def test_put_writes(checkpointer, memory):
    thread_id = "thread-w"
    config = create_config(thread_id)

    writes = [("channel_a", "value_a"), ("channel_b", {"complex": "value"})]
    task_id = "task-123"
    task_path = "graph:subgraph:node_a"

    checkpointer.put_writes(config, writes, task_id, task_path)

    facts = memory.query(typename="langgraph_write")
    assert len(facts) == 2

    facts.sort(key=lambda x: x["payload"]["idx"])

    f1 = facts[0]["payload"]
    assert f1["channel"] == "channel_a"
    assert f1["value"] == "value_a"
    assert f1["task_id"] == task_id
    assert f1["task_path"] == task_path
    assert f1["thread_id"] == thread_id

    assert facts[0]["session_id"] == thread_id


def test_delete_thread_clears_everything(checkpointer, memory):
    t_del = "thread-delete"
    conf_del = create_config(t_del)

    t_keep = "thread-keep"
    conf_keep = create_config(t_keep)

    checkpointer.put(conf_del, create_checkpoint("ts-1", "A"), create_metadata(), {})
    checkpointer.put_writes(conf_del, [("k", "v"), ("k2", "v2")], "task-1", "")
    checkpointer.put(conf_keep, create_checkpoint("ts-2", "B"), create_metadata(), {})

    assert len(memory.query(filters={"session_id": t_del})) == 3  # 1 ckpt + 2 writes
    assert len(memory.query(filters={"session_id": t_keep})) == 1

    checkpointer.delete_thread(t_del)

    assert len(memory.query(filters={"session_id": t_del})) == 0

    assert len(memory.query(filters={"session_id": t_keep})) == 1
    stored_keep = memory.query(filters={"session_id": t_keep})[0]
    assert stored_keep["payload"]["checkpoint"]["id"] == "ts-2"
