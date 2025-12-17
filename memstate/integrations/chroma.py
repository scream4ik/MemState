from typing import Any, Callable

from memstate.constants import Operation
from memstate.schemas import Fact

try:
    from chromadb import EmbeddingFunction
    from chromadb.api import AsyncClientAPI, ClientAPI, Embeddable
    from chromadb.api.models.AsyncCollection import AsyncCollection
except ImportError:
    raise ImportError("pip install chromadb")

TextFormatter = Callable[[dict[str, Any]], str]
MetadataFormatter = Callable[[dict[str, Any]], dict[str, Any]]


class ChromaSyncHook:
    def __init__(
        self,
        client: ClientAPI,
        collection_name: str,
        embedding_fn: EmbeddingFunction[Embeddable] | None = None,
        target_types: set[str] | None = None,
        text_field: str | None = None,
        text_formatter: TextFormatter | None = None,
        metadata_fields: list[str] | None = None,
        metadata_formatter: MetadataFormatter | None = None,
    ):
        """
        :param client: Initialized Chroma Client.
        :param collection_name: collection name.
        :param embedding_fn: Function (text -> vector). If None, Chroma uses default.
        :param target_types: Types of facts for synchronization (to avoid garbage).
        :param text_field: Field name of text in fact.
        :param text_formatter: Function.
        :param metadata_fields: Fields of metadata in fact.
        :param metadata_formatter: Function.
        """
        self.client = client
        self.collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
        )
        self.target_types = target_types or set()

        if text_formatter is not None:
            self._extract_text = text_formatter
        elif text_field:
            self._extract_text = lambda data: str(data.get(text_field, ""))
        else:
            self._extract_text = lambda data: str(data)

        self.metadata_fields = metadata_fields or []
        self.metadata_formatter = metadata_formatter

    def _get_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.metadata_formatter is not None:
            return self.metadata_formatter(data)

        if self.metadata_fields:
            meta = {}
            for field in self.metadata_fields:
                val = data.get(field)
                if val is not None:
                    if isinstance(val, (str, int, float, bool)):
                        meta[field] = val
                    else:
                        meta[field] = str(val)
            return meta

        return {}

    def __call__(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        if op == Operation.DELETE:
            self.collection.delete(ids=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not data or (self.target_types and data.type not in self.target_types):
            return

        text = self._extract_text(data.payload)

        if not text.strip():
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            meta = {"type": data.type, "source": data.source or "", "ts": str(data.ts)}
            metadata = self._get_metadata(data=data.payload)
            meta.update(metadata)

            self.collection.upsert(ids=[fact_id], documents=[text], metadatas=[meta])


class AsyncChromaSyncHook:
    """
    async def main():
        # 1. Async Chroma Client
        client = await chromadb.AsyncHttpClient()

        # 2. Async Hook
        hook = AsyncChromaSyncHook(client, "my_collection", text_field="content")

        # 3. Async Store
        store = AsyncMemoryStore(AsyncInMemoryStorage(), hooks=[hook])

        # 4. Async Commit
        await store.commit_model(...)

    asyncio.run(main())
    """

    def __init__(
        self,
        client: AsyncClientAPI,
        collection_name: str,
        embedding_fn: EmbeddingFunction[Embeddable] | None = None,
        target_types: set[str] | None = None,
        text_field: str | None = None,
        text_formatter: TextFormatter | None = None,
        metadata_fields: list[str] | None = None,
        metadata_formatter: MetadataFormatter | None = None,
    ):
        self.client = client
        self.collection_name = collection_name
        self.embedding_fn = embedding_fn

        self._collection: AsyncCollection | None = None

        self.target_types = target_types or set()

        if text_formatter is not None:
            self._extract_text = text_formatter
        elif text_field:
            self._extract_text = lambda data: str(data.get(text_field, ""))
        else:
            self._extract_text = lambda data: str(data)

        self.metadata_fields = metadata_fields or []
        self.metadata_formatter = metadata_formatter

    async def _get_collection(self) -> AsyncCollection:
        """Lazy loader for the async collection."""
        if self._collection is None:
            self._collection = await self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
            )
        return self._collection

    def _get_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.metadata_formatter is not None:
            return self.metadata_formatter(data)

        if self.metadata_fields:
            meta = {}
            for field in self.metadata_fields:
                val = data.get(field)
                if val is not None:
                    if isinstance(val, (str, int, float, bool)):
                        meta[field] = val
                    else:
                        meta[field] = str(val)
            return meta
        return {}

    async def __call__(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        collection = await self._get_collection()

        if op == Operation.DELETE:
            await collection.delete(ids=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not data or (self.target_types and data.type not in self.target_types):
            return

        text = self._extract_text(data.payload)

        if not text.strip():
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            meta = {"type": data.type, "source": data.source or "", "ts": str(data.ts)}
            metadata = self._get_metadata(data=data.payload)
            meta.update(metadata)

            await collection.upsert(ids=[fact_id], documents=[text], metadatas=[meta])
