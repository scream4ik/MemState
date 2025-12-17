from typing import Any, Callable

from memstate.constants import Operation
from memstate.schemas import Fact

try:
    from qdrant_client import AsyncQdrantClient, QdrantClient, models
except ImportError:
    raise ImportError("To use QdrantSyncHook, run: pip install qdrant-client")

TextFormatter = Callable[[dict[str, Any]], str]
MetadataFormatter = Callable[[dict[str, Any]], dict[str, Any]]
EmbeddingFunction = Callable[[str], list[float]]


class FastEmbedEncoder:
    """
    Default embedding implementation using FastEmbed.
    Used if no custom embedding_fn is provided.
    """

    def __init__(
        self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", options: dict[str, Any] | None = None
    ):
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise ImportError(
                "FastEmbed is not installed. " "Install it via `pip install fastembed` or pass a custom `embedding_fn`."
            )
        self.model = TextEmbedding(model_name, **(options or {}))

    def __call__(self, text: str) -> list[float]:
        return list(self.model.embed(text))[0].tolist()


class QdrantSyncHook:
    """
    encoder = FastEmbedEncoder(
        model_name="BAAI/bge-small-en-v1.5",
        options={"cuda": True}
    )
    hook = QdrantSyncHook(client, "memory", embedding_fn=encoder)

    resp = openai.embeddings.create(input=text, model="text-embedding-3-small")
    openai_embedder = resp.data[0].embedding
    hook = QdrantSyncHook(client, "memory", embedding_fn=openai_embedder)
    """

    def __init__(
        self,
        client: QdrantClient,
        collection_name: str,
        embedding_fn: EmbeddingFunction | None = None,
        target_types: set[str] | None = None,
        text_field: str | None = None,
        text_formatter: TextFormatter | None = None,
        metadata_fields: list[str] | None = None,
        metadata_formatter: MetadataFormatter | None = None,
        distance: models.Distance = models.Distance.COSINE,
    ) -> None:
        self.client = client
        self.collection_name = collection_name

        self.embedding_fn = embedding_fn or FastEmbedEncoder()

        self.target_types = target_types or set()
        self.distance = distance

        if text_formatter is not None:
            self._extract_text = text_formatter
        elif text_field:
            self._extract_text = lambda data: str(data.get(text_field, ""))
        else:
            self._extract_text = lambda data: str(data)

        self.metadata_fields = metadata_fields or []
        self.metadata_formatter = metadata_formatter

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """
        Auto-detects vector size by running a dummy embedding
        and ensures the collection exists.
        """
        try:
            dummy_vec = self.embedding_fn("test")
            vector_size = len(dummy_vec)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize embedding function: {e}")

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=self.distance),
            )
        else:
            coll_info = self.client.get_collection(self.collection_name)
            config = coll_info.config.params.vectors

            existing_size = None
            if isinstance(config, models.VectorParams):
                existing_size = config.size
            elif isinstance(config, dict) and "" in config:  # Default unnamed vector
                existing_size = config[""].size

            if existing_size and existing_size != vector_size:
                raise ValueError(
                    f"Collection '{self.collection_name}' expects vector size {existing_size}, "
                    f"but your embedding function produces {vector_size}. "
                    "Mismatch detected."
                )

    def _get_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.metadata_formatter is not None:
            return self.metadata_formatter(data)

        if self.metadata_fields:
            meta = {}
            for field in self.metadata_fields:
                val = data.get(field)
                if val is not None:
                    if isinstance(val, (str, int, float, bool, list)):
                        meta[field] = val
                    else:
                        meta[field] = str(val)
            return meta

        return {}

    def __call__(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        if op == Operation.DELETE:
            self.client.delete(collection_name=self.collection_name, points_selector=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not data or (self.target_types and data.type not in self.target_types):
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            text = self._extract_text(data.payload)
            if not text.strip():
                return

            vector = self.embedding_fn(text)

            meta = {"type": data.type, "source": data.source or "", "ts": str(data.ts), "document": text}
            user_meta = self._get_metadata(data=data.payload)
            meta.update(user_meta)

            self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=fact_id, vector=vector, payload=meta)],
            )


class AsyncQdrantSyncHook:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str,
        embedding_fn: EmbeddingFunction | None = None,
        target_types: set[str] | None = None,
        text_field: str | None = None,
        text_formatter: TextFormatter | None = None,
        metadata_fields: list[str] | None = None,
        metadata_formatter: MetadataFormatter | None = None,
        distance: models.Distance = models.Distance.COSINE,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.embedding_fn = embedding_fn or FastEmbedEncoder()
        self.target_types = target_types or set()
        self.distance = distance

        self._collection_checked = False

        if text_formatter is not None:
            self._extract_text = text_formatter
        elif text_field:
            self._extract_text = lambda data: str(data.get(text_field, ""))
        else:
            self._extract_text = lambda data: str(data)

        self.metadata_fields = metadata_fields or []
        self.metadata_formatter = metadata_formatter

    async def _ensure_collection(self) -> None:
        """Async initialization checks."""
        if self._collection_checked:
            return

        try:
            dummy_vec = self.embedding_fn("test")
            vector_size = len(dummy_vec)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize embedding function: {e}")

        # AWAIT check
        if not await self.client.collection_exists(self.collection_name):
            # AWAIT create
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=self.distance),
            )
        else:
            # AWAIT get info
            coll_info = await self.client.get_collection(self.collection_name)
            config = coll_info.config.params.vectors

            existing_size = None
            if isinstance(config, models.VectorParams):
                existing_size = config.size
            elif isinstance(config, dict) and "" in config:
                existing_size = config[""].size

            if existing_size and existing_size != vector_size:
                raise ValueError(
                    f"Collection '{self.collection_name}' mismatch: existing size {existing_size}, new size {vector_size}."
                )

        self._collection_checked = True

    def _get_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.metadata_formatter is not None:
            return self.metadata_formatter(data)
        if self.metadata_fields:
            meta = {}
            for field in self.metadata_fields:
                val = data.get(field)
                if val is not None:
                    if isinstance(val, (str, int, float, bool, list)):
                        meta[field] = val
                    else:
                        meta[field] = str(val)
            return meta
        return {}

    async def __call__(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        await self._ensure_collection()

        if op == Operation.DELETE:
            await self.client.delete(collection_name=self.collection_name, points_selector=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not data or (self.target_types and data.type not in self.target_types):
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            text = self._extract_text(data.payload)
            if not text.strip():
                return

            vector = self.embedding_fn(text)

            meta = {"type": data.type, "source": data.source or "", "ts": str(data.ts), "document": text}
            meta.update(self._get_metadata(data=data.payload))

            # Upsert async
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=fact_id, vector=vector, payload=meta)],
            )
