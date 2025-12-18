"""
Qdrant integration.
"""

from typing import Any, Callable

from memstate.constants import Operation
from memstate.schemas import Fact
from memstate.types import AsyncMemoryHook, MemoryHook

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

    This class provides a lightweight wrapper around the FastEmbed library to
    generate embeddings for text inputs. The encoder initializes with a specific
    pre-trained model from FastEmbed and can be invoked to generate a numerical
    vector representation of the provided text.

    Attributes:
        model (TextEmbedding): Instance of the FastEmbed TextEmbedding model used to generate embeddings.
    """

    def __init__(
        self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", options: dict[str, Any] | None = None
    ):
        """
        Initializes the embedding model using the specified `model_name` and optional `options`
        dictionary. The class leverages the FastEmbed library for handling text embeddings.

        If the FastEmbed library is not installed on the system, an ImportError is raised,
        advising the user to install the library or provide a custom embedding function.

        Args:
            model_name (str): The name of the model to be used for text embeddings.
                Defaults to "sentence-transformers/all-MiniLM-L6-v2".
            options (dict[str, Any] | None): A dictionary of options for configuring the embedding model.
                If not provided, an empty dictionary is used.

        Raises:
            ImportError: If the FastEmbed library is not installed on the system, this exception
                is raised, advising the use of `pip install fastembed` or providing a custom embedding function.
        """
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise ImportError(
                "FastEmbed is not installed. " "Install it via `pip install fastembed` or pass a custom `embedding_fn`."
            )
        self.model = TextEmbedding(model_name, **(options or {}))

    def __call__(self, text: str) -> list[float]:
        """
        Computes and returns a list of float values representing the embedding of the
        provided text using the model.

        Args:
            text (str): The input string to be embedded.

        Returns:
            A list of float values representing the text embedding.
        """
        return list(self.model.embed(text))[0].tolist()


class QdrantSyncHook(MemoryHook):
    """
    Handles synchronization of memory updates with a Qdrant collection by managing
    CRUD operations on vector embeddings and metadata. Designed for real-time updates
    and integration with Qdrant database collections.

    The class provides support for maintaining vector embeddings, setting up collection
    parameters, formatting metadata, and handling various operations such as inserts,
    updates, deletions, and session discards. Additionally, it supports embedding functions
    and configurable distance metrics for vector similarity functionality.

    Example:
        ```python
        encoder = FastEmbedEncoder(model_name="BAAI/bge-small-en-v1.5", options={"cuda": True})
        hook = QdrantSyncHook(client, "memory", embedding_fn=encoder)
        resp = openai.embeddings.create(input=text, model="text-embedding-3-small")
        openai_embedder = resp.data[0].embedding
        hook = QdrantSyncHook(client, "memory", embedding_fn=openai_embedder)
        ```

    Attributes:
        client (QdrantClient): Client instance for interacting with the Qdrant database.
        collection_name (str): Name of the Qdrant collection to synchronize with.
        embedding_fn (EmbeddingFunction | None): Function responsible for generating vector embeddings,
            defaulting to FastEmbedEncoder if not provided.
        target_types (set[str] | None): Set of target types that define which operations are supported
            for synchronization. Defaults to an empty set.
        distance (models.Distance): Metric to compute vector similarity in Qdrant, e.g., COSINE, EUCLIDEAN.
        metadata_fields (list[str] | None): List of fields to include in the metadata payload.
        metadata_formatter (MetadataFormatter | None): Formatter function for structuring metadata. Optional.
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
        Auto-detects vector size by running a dummy embedding and ensures the collection exists.

        Returns:
            None
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
        """
        Generates metadata from the input data using a formatter or a predefined set of fields.

        If a metadata formatter is defined, it will process the input data.
        If no formatter is defined, it will extract specific fields from the input
        data and format their values. Only string, integer, float, and boolean
        types are preserved; other types will be converted to strings.

        Args:
            data (dict[str, Any]): A dictionary containing the input data to retrieve metadata from.

        Returns:
            A dictionary containing the generated metadata. This dictionary can
                be empty if no metadata fields or formatter are provided.
        """
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

    def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        if op == Operation.DELETE:
            self.client.delete(collection_name=self.collection_name, points_selector=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not fact or (self.target_types and fact.type not in self.target_types):
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            text = self._extract_text(fact.payload)
            if not text.strip():
                return

            vector = self.embedding_fn(text)

            meta = {"type": fact.type, "source": fact.source or "", "ts": str(fact.ts), "document": text}
            user_meta = self._get_metadata(data=fact.payload)
            meta.update(user_meta)

            self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=fact_id, vector=vector, payload=meta)],
            )


class AsyncQdrantSyncHook(AsyncMemoryHook):
    """
    Handles synchronization of memory updates with a Qdrant collection by managing
    CRUD operations on vector embeddings and metadata. Designed for real-time updates
    and integration with Qdrant database collections.

    The class provides support for maintaining vector embeddings, setting up collection
    parameters, formatting metadata, and handling various operations such as inserts,
    updates, deletions, and session discards. Additionally, it supports embedding functions
    and configurable distance metrics for vector similarity functionality.

    Attributes:
        client (AsyncQdrantClient): Client instance for interacting with the Qdrant database.
        collection_name (str): Name of the Qdrant collection to synchronize with.
        embedding_fn (EmbeddingFunction | None): Function responsible for generating vector embeddings,
            defaulting to FastEmbedEncoder if not provided.
        target_types (set[str] | None): Set of target types that define which operations are supported
            for synchronization. Defaults to an empty set.
        distance (models.Distance): Metric to compute vector similarity in Qdrant, e.g., COSINE, EUCLIDEAN.
        metadata_fields (list[str] | None): List of fields to include in the metadata payload.
        metadata_formatter (MetadataFormatter | None): Formatter function for structuring metadata. Optional.
    """

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
        """
        Async initialization checks.

        Returns:
            None
        """
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
        """
        Generates metadata from the input data using a formatter or a predefined set of fields.

        If a metadata formatter is defined, it will process the input data.
        If no formatter is defined, it will extract specific fields from the input
        data and format their values. Only string, integer, float, and boolean
        types are preserved; other types will be converted to strings.

        Args:
            data (dict[str, Any]): A dictionary containing the input data to retrieve metadata from.

        Returns:
            A dictionary containing the generated metadata. This dictionary can
                be empty if no metadata fields or formatter are provided.
        """
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

    async def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Asynchronously executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        await self._ensure_collection()

        if op == Operation.DELETE:
            await self.client.delete(collection_name=self.collection_name, points_selector=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not fact or (self.target_types and fact.type not in self.target_types):
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            text = self._extract_text(fact.payload)
            if not text.strip():
                return

            vector = self.embedding_fn(text)

            meta = {"type": fact.type, "source": fact.source or "", "ts": str(fact.ts), "document": text}
            meta.update(self._get_metadata(data=fact.payload))

            # Upsert async
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=fact_id, vector=vector, payload=meta)],
            )
