import uuid

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from memstate import Fact, Operation
from memstate.integrations.qdrant import AsyncQdrantSyncHook


@pytest.fixture
def client():
    return qdrant_client.AsyncQdrantClient(":memory:")


@pytest.fixture
def collection_name():
    return "test_memstate_sync"


@pytest.fixture
def fact_id():
    return str(uuid.uuid4())


async def test_lazy_initialization_creates_collection(client, collection_name):
    hook = AsyncQdrantSyncHook(client=client, collection_name=collection_name)

    collections_before = await client.get_collections()
    assert not any(c.name == collection_name for c in collections_before.collections)

    await hook._ensure_collection()

    collections_after = await client.get_collections()
    assert any(c.name == collection_name for c in collections_after.collections)


async def test_commit_upserts_data(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(client=client, collection_name=collection_name, text_field="content")
    await hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"content": "Hello World"}))

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "Hello World"
    assert point.payload["type"] == "memory"


async def test_promote_updates_data(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(
        client=client, collection_name=collection_name, text_field="text", metadata_fields=["status"]
    )
    await hook._ensure_collection()

    # Pre-seed
    await client.upsert(
        collection_name=collection_name,
        points=[
            qdrant_client.models.PointStruct(
                id=fact_id,
                vector=qdrant_client.models.Document(
                    text="Old",
                    model="sentence-transformers/all-MiniLM-L6-v2",
                ),
                payload={"status": "draft"},
            )
        ],
    )

    # Promote
    await hook(
        op=Operation.PROMOTE, fact_id=fact_id, fact=Fact(type="memory", payload={"text": "New", "status": "committed"})
    )

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "New"
    assert point.payload["status"] == "committed"


async def test_delete_removes_data(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(client=client, collection_name=collection_name)
    await hook._ensure_collection()

    await client.upsert(
        collection_name=collection_name,
        points=[
            qdrant_client.models.PointStruct(
                id=fact_id,
                vector=qdrant_client.models.Document(
                    text="To delete",
                    model="sentence-transformers/all-MiniLM-L6-v2",
                ),
            )
        ],
    )

    await hook(op=Operation.DELETE, fact_id=fact_id, fact=None)

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 0


async def test_discard_session_is_ignored(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(client=client, collection_name=collection_name)
    await hook._ensure_collection()

    await client.upsert(
        collection_name=collection_name,
        points=[
            qdrant_client.models.PointStruct(
                id=fact_id,
                vector=qdrant_client.models.Document(
                    text="Stay",
                    model="sentence-transformers/all-MiniLM-L6-v2",
                ),
            )
        ],
    )

    await hook(op=Operation.DISCARD_SESSION, fact_id=fact_id, fact=None)

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 1


async def test_text_formatter_strategy(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(
        client=client, collection_name=collection_name, text_formatter=lambda d: f"{d['key']}: {d['val']}"
    )
    await hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"key": "A", "val": "B"}))

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "A: B"


async def test_fallback_missing_text_skips_upsert(client, collection_name, fact_id):
    hook = AsyncQdrantSyncHook(client=client, collection_name=collection_name, text_field="missing_field")
    await hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"other": "stuff"}))

    points, _ = await client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 0
