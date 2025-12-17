import pytest
from testcontainers.chroma import ChromaContainer

chromadb = pytest.importorskip("chromadb")
qdrant = pytest.importorskip("qdrant_client")

from memstate import AsyncInMemoryStorage, AsyncMemoryStore, Fact
from memstate.integrations.chroma import AsyncChromaSyncHook
from memstate.integrations.qdrant import AsyncQdrantSyncHook


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


async def test_e2e_memory_store_syncs_to_chroma(chroma_client):
    collection_name = "e2e_test"

    hook = AsyncChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_field="content", metadata_fields=["role"]
    )

    store = AsyncMemoryStore(AsyncInMemoryStorage())
    store.add_hook(hook=hook)

    await store.commit(fact=Fact(type="test", payload={"content": "Integration works!", "role": "system"}))

    coll = await chroma_client.get_collection(collection_name)
    results = await coll.get()

    assert len(results["ids"]) == 1
    assert results["documents"][0] == "Integration works!"
    assert results["metadatas"][0]["role"] == "system"


async def test_e2e_memory_store_syncs_to_qdrant():
    qdrant_client = qdrant.AsyncQdrantClient(":memory:")
    collection_name = "e2e_test"

    hook = AsyncQdrantSyncHook(
        client=qdrant_client, collection_name=collection_name, text_field="content", metadata_fields=["role"]
    )

    store = AsyncMemoryStore(AsyncInMemoryStorage())
    store.add_hook(hook=hook)

    fact_id = await store.commit(fact=Fact(type="test", payload={"content": "Integration works!", "role": "system"}))

    points, _ = await qdrant_client.scroll(collection_name=collection_name, limit=10)

    assert len(points) == 1
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "Integration works!"
    assert point.payload["role"] == "system"
