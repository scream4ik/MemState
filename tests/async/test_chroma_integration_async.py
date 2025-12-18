import pytest
from testcontainers.chroma import ChromaContainer

chromadb = pytest.importorskip("chromadb")

from memstate import Fact, Operation
from memstate.integrations.chroma import AsyncChromaSyncHook


@pytest.fixture
def chroma_server():
    with ChromaContainer("chromadb/chroma:latest") as chroma:
        config = chroma.get_config()
        url = f"{config['host']}:{config['port']}"
        yield url


@pytest.fixture
async def chroma_client(chroma_server):
    host, port = chroma_server.split(":")
    client = await chromadb.AsyncHttpClient(host=host, port=int(port))
    return client


@pytest.fixture
def collection_name():
    return "test_memstate_sync"


async def test_lazy_initialization_creates_collection(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(client=chroma_client, collection_name=collection_name)

    collections_before = await chroma_client.list_collections()
    assert not any(c.name == collection_name for c in collections_before)

    await hook._get_collection()

    collections_after = await chroma_client.list_collections()
    assert any(c.name == collection_name for c in collections_after)


async def test_commit_upserts_data(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(client=chroma_client, collection_name=collection_name, text_field="content")
    await hook(op=Operation.COMMIT, fact_id="fact_1", fact=Fact(type="memory", payload={"content": "Hello World"}))

    coll = await chroma_client.get_collection(collection_name)
    result = await coll.get(ids=["fact_1"])
    assert result["documents"][0] == "Hello World"
    assert result["metadatas"][0]["type"] == "memory"


async def test_promote_updates_data(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_field="text", metadata_fields=["status"]
    )
    coll = await chroma_client.get_or_create_collection(collection_name)

    # Pre-seed
    await coll.add(ids=["fact_1"], documents=["Old"], metadatas=[{"status": "draft"}])

    # Promote
    await hook(
        op=Operation.PROMOTE, fact_id="fact_1", fact=Fact(type="memory", payload={"text": "New", "status": "committed"})
    )

    result = await coll.get(ids=["fact_1"])
    assert result["documents"][0] == "New"
    assert result["metadatas"][0]["status"] == "committed"


async def test_delete_removes_data(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(client=chroma_client, collection_name=collection_name)
    coll = await chroma_client.get_or_create_collection(collection_name)

    await coll.add(ids=["del_1"], documents=["To delete"])

    await hook(op=Operation.DELETE, fact_id="del_1", fact=None)

    result = await coll.get(ids=["del_1"])
    assert len(result["ids"]) == 0


async def test_discard_session_is_ignored(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(client=chroma_client, collection_name=collection_name)
    coll = await chroma_client.get_or_create_collection(collection_name)

    await coll.add(ids=["safe_1"], documents=["Stay"])

    await hook(op=Operation.DISCARD_SESSION, fact_id="safe_1", fact=None)

    result = await coll.get(ids=["safe_1"])
    assert len(result["ids"]) == 1


async def test_text_formatter_strategy(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_formatter=lambda d: f"{d['key']}: {d['val']}"
    )
    await hook(op=Operation.COMMIT, fact_id="fmt_1", fact=Fact(type="memory", payload={"key": "A", "val": "B"}))

    coll = await chroma_client.get_collection(collection_name)
    result = await coll.get(ids=["fmt_1"])
    assert result["documents"][0] == "A: B"


async def test_fallback_missing_text_skips_upsert(chroma_client, collection_name):
    hook = AsyncChromaSyncHook(client=chroma_client, collection_name=collection_name, text_field="missing_field")
    await hook(op=Operation.COMMIT, fact_id="bad_1", fact=Fact(type="memory", payload={"other": "stuff"}))

    coll = await chroma_client.get_collection(collection_name)
    result = await coll.get(ids=["bad_1"])
    assert len(result["ids"]) == 0
