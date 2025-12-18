import pytest

chromadb = pytest.importorskip("chromadb")

from memstate import Fact, Operation
from memstate.integrations.chroma import ChromaSyncHook


@pytest.fixture
def chroma_client():
    return chromadb.Client()


@pytest.fixture
def collection_name():
    return "test_memstate_sync"


def test_initialization_creates_collection(chroma_client, collection_name):
    ChromaSyncHook(client=chroma_client, collection_name=collection_name)
    collections = chroma_client.list_collections()
    assert any(c.name == collection_name for c in collections)


def test_commit_upserts_data(chroma_client, collection_name):
    hook = ChromaSyncHook(client=chroma_client, collection_name=collection_name, text_field="content")
    hook(op=Operation.COMMIT, fact_id="fact_1", fact=Fact(type="memory", payload={"content": "Hello World"}))

    coll = chroma_client.get_collection(collection_name)
    result = coll.get(ids=["fact_1"])
    assert result["documents"][0] == "Hello World"
    assert result["metadatas"][0]["type"] == "memory"


def test_promote_updates_data(chroma_client, collection_name):
    hook = ChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_field="text", metadata_fields=["status"]
    )
    coll = chroma_client.get_collection(collection_name)

    # Pre-seed
    coll.add(ids=["fact_1"], documents=["Old"], metadatas=[{"status": "draft"}])

    # Promote
    hook(
        op=Operation.PROMOTE, fact_id="fact_1", fact=Fact(type="memory", payload={"text": "New", "status": "committed"})
    )

    result = coll.get(ids=["fact_1"])
    assert result["documents"][0] == "New"
    assert result["metadatas"][0]["status"] == "committed"


def test_delete_removes_data(chroma_client, collection_name):
    hook = ChromaSyncHook(client=chroma_client, collection_name=collection_name)
    coll = chroma_client.get_collection(collection_name)

    coll.add(ids=["del_1"], documents=["To delete"])

    hook(op=Operation.DELETE, fact_id="del_1", fact=None)

    result = coll.get(ids=["del_1"])
    assert len(result["ids"]) == 0


def test_discard_session_is_ignored(chroma_client, collection_name):
    hook = ChromaSyncHook(client=chroma_client, collection_name=collection_name)
    coll = chroma_client.get_collection(collection_name)

    coll.add(ids=["safe_1"], documents=["Stay"])

    hook(op=Operation.DISCARD_SESSION, fact_id="safe_1", fact=None)

    result = coll.get(ids=["safe_1"])
    assert len(result["ids"]) == 1


def test_text_formatter_strategy(chroma_client, collection_name):
    hook = ChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_formatter=lambda d: f"{d['key']}: {d['val']}"
    )
    hook(op=Operation.COMMIT, fact_id="fmt_1", fact=Fact(type="memory", payload={"key": "A", "val": "B"}))

    coll = chroma_client.get_collection(collection_name)
    assert coll.get(ids=["fmt_1"])["documents"][0] == "A: B"


def test_fallback_missing_text_skips_upsert(chroma_client, collection_name):
    hook = ChromaSyncHook(client=chroma_client, collection_name=collection_name, text_field="missing_field")
    hook(op=Operation.COMMIT, fact_id="bad_1", fact=Fact(type="memory", payload={"other": "stuff"}))

    coll = chroma_client.get_collection(collection_name)
    result = coll.get(ids=["bad_1"])
    assert len(result["ids"]) == 0
