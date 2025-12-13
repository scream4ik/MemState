import pytest

chromadb = pytest.importorskip("chromadb")
qdrant_client = pytest.importorskip("qdrant_client")

from memstate import Fact, InMemoryStorage, MemoryStore
from memstate.integrations.chroma import ChromaSyncHook
from memstate.integrations.qdrant import QdrantSyncHook


def test_e2e_memory_store_syncs_to_chroma():
    chroma_client = chromadb.Client()
    collection_name = "e2e_test"

    hook = ChromaSyncHook(
        client=chroma_client, collection_name=collection_name, text_field="content", metadata_fields=["role"]
    )

    store = MemoryStore(InMemoryStorage())
    store.add_hook(hook=hook)

    store.commit(fact=Fact(type="test", payload={"content": "Integration works!", "role": "system"}))

    coll = chroma_client.get_collection(collection_name)
    results = coll.get()

    assert len(results["ids"]) == 1
    assert results["documents"][0] == "Integration works!"
    assert results["metadatas"][0]["role"] == "system"


def test_e2e_memory_store_syncs_to_qdrand():
    client = qdrant_client.QdrantClient(":memory:")
    collection_name = "e2e_test"

    hook = QdrantSyncHook(
        client=client, collection_name=collection_name, text_field="content", metadata_fields=["role"]
    )

    store = MemoryStore(InMemoryStorage())
    store.add_hook(hook=hook)

    fact_id = store.commit(fact=Fact(type="test", payload={"content": "Integration works!", "role": "system"}))

    points, _ = client.scroll(collection_name=collection_name, limit=10)

    assert len(points) == 1
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "Integration works!"
    assert point.payload["role"] == "system"
