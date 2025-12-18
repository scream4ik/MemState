import uuid

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from memstate import Fact, Operation
from memstate.integrations.qdrant import QdrantSyncHook


@pytest.fixture
def client():
    return qdrant_client.QdrantClient(":memory:")


@pytest.fixture
def collection_name():
    return "test_memstate_sync"


@pytest.fixture
def fact_id():
    return str(uuid.uuid4())


def test_initialization_creates_collection(client, collection_name):
    QdrantSyncHook(client=client, collection_name=collection_name)
    collections = client.get_collections()
    assert any(c.name == collection_name for c in collections.collections)


def test_commit_upserts_data(client, collection_name, fact_id):
    hook = QdrantSyncHook(client=client, collection_name=collection_name, text_field="content")
    hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"content": "Hello World"}))

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "Hello World"
    assert point.payload["type"] == "memory"


def test_promote_updates_data(client, collection_name, fact_id):
    hook = QdrantSyncHook(client=client, collection_name=collection_name, text_field="text", metadata_fields=["status"])

    # Pre-seed
    client.upsert(
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
    hook(
        op=Operation.PROMOTE, fact_id=fact_id, fact=Fact(type="memory", payload={"text": "New", "status": "committed"})
    )

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "New"
    assert point.payload["status"] == "committed"


def test_delete_removes_data(client, collection_name, fact_id):
    hook = QdrantSyncHook(client=client, collection_name=collection_name)

    client.upsert(
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

    hook(op=Operation.DELETE, fact_id=fact_id, fact=None)

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 0


def test_discard_session_is_ignored(client, collection_name, fact_id):
    hook = QdrantSyncHook(client=client, collection_name=collection_name)

    client.upsert(
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

    hook(op=Operation.DISCARD_SESSION, fact_id=fact_id, fact=None)

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 1


def test_text_formatter_strategy(client, collection_name, fact_id):
    hook = QdrantSyncHook(
        client=client, collection_name=collection_name, text_formatter=lambda d: f"{d['key']}: {d['val']}"
    )
    hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"key": "A", "val": "B"}))

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    point = points[0]
    assert point.id == fact_id
    assert point.payload["document"] == "A: B"


def test_fallback_missing_text_skips_upsert(client, collection_name, fact_id):
    hook = QdrantSyncHook(client=client, collection_name=collection_name, text_field="missing_field")
    hook(op=Operation.COMMIT, fact_id=fact_id, fact=Fact(type="memory", payload={"other": "stuff"}))

    points, _ = client.scroll(collection_name=collection_name, limit=10)
    assert len(points) == 0
