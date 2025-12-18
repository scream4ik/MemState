"""
Chomadb integration.
"""

from typing import Any, Callable

from memstate.constants import Operation
from memstate.schemas import Fact
from memstate.types import AsyncMemoryHook, MemoryHook

try:
    from chromadb import EmbeddingFunction
    from chromadb.api import AsyncClientAPI, ClientAPI, Embeddable
    from chromadb.api.models.AsyncCollection import AsyncCollection
except ImportError:
    raise ImportError("pip install chromadb")

TextFormatter = Callable[[dict[str, Any]], str]
MetadataFormatter = Callable[[dict[str, Any]], dict[str, Any]]


class ChromaSyncHook(MemoryHook):
    """
    Handles synchronization of memory data with Chroma collections by integrating
    fact operations and data transformations.

    This class is responsible for managing connections to a Chroma collection via
    a Chroma client, extracting and formatting text and metadata as per the provided
    configuration, and performing operations like deletion or upserting of facts
    based on various triggers or operations. It also provides flexibility in defining
    target data types, metadata extraction, text processing, and overall data
    synchronization rules.

    Attributes:
        client (ClientAPI): The Chroma client instance used for collection access and management.
        collection_name (str): The name of the Chroma collection to be synchronized.
        embedding_fn (EmbeddingFunction | None): Optional function for generating embeddings from text.
        target_types (set[str]): A set of fact types allowed for synchronization. If empty, all types are allowed.
        text_field (str | None): Field name of text in fact.
        text_formatter (TextFormatter | None): Optional custom function for extracting text. Overrides `text_field` if provided.
        metadata_fields (list[str]): The list of metadata fields to extract from the fact
            payload. Used if no metadata formatter is provided.
        metadata_formatter (MetadataFormatter | None): Optional custom function for extracting metadata.
            Overrides `metadata_fields` if provided.
    """

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
                    if isinstance(val, (str, int, float, bool)):
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
            self.collection.delete(ids=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not fact or (self.target_types and fact.type not in self.target_types):
            return

        text = self._extract_text(fact.payload)

        if not text.strip():
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            meta = {"type": fact.type, "source": fact.source or "", "ts": str(fact.ts)}
            metadata = self._get_metadata(data=fact.payload)
            meta.update(metadata)

            self.collection.upsert(ids=[fact_id], documents=[text], metadatas=[meta])


class AsyncChromaSyncHook(AsyncMemoryHook):
    """
    Handles synchronization of memory data with Chroma collections by integrating
    fact operations and data transformations.

    This class is responsible for managing connections to a Chroma collection via
    AsyncClientAPI, extracting and formatting text and metadata as per the provided
    configuration, and performing operations like deletion or upserting of facts
    based on various triggers or operations. It also provides flexibility in defining
    target data types, metadata extraction, text processing, and overall data
    synchronization rules.

    Example:
        ```python
        client = await chromadb.AsyncHttpClient()
        hook = AsyncChromaSyncHook(client, "my_collection", text_field="content")
        store = AsyncMemoryStore(AsyncInMemoryStorage(), hooks=[hook])
        await store.commit_model(...)
        ```

    Attributes:
        client (AsyncClientAPI): The Chroma client instance used for collection access and management.
        collection_name (str): The name of the Chroma collection to be synchronized.
        embedding_fn (EmbeddingFunction | None): Optional function for generating embeddings from text.
        target_types (set[str]): A set of fact types allowed for synchronization. If empty, all types are allowed.
        text_field (str | None): Field name of text in fact.
        text_formatter (TextFormatter | None): Optional custom function for extracting text. Overrides `text_field` if provided.
        metadata_fields (list[str]): The list of metadata fields to extract from the fact
            payload. Used if no metadata formatter is provided.
        metadata_formatter (MetadataFormatter | None): Optional custom function for extracting metadata.
            Overrides `metadata_fields` if provided.
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
        """
        Lazy loader for the async collection.

        Returns:
            The async collection.
        """
        if self._collection is None:
            self._collection = await self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_fn,
            )
        return self._collection

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
                    if isinstance(val, (str, int, float, bool)):
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
        collection = await self._get_collection()

        if op == Operation.DELETE:
            await collection.delete(ids=[fact_id])
            return

        if op == Operation.DISCARD_SESSION:
            return

        if not fact or (self.target_types and fact.type not in self.target_types):
            return

        text = self._extract_text(fact.payload)

        if not text.strip():
            return

        if op in (Operation.COMMIT, Operation.UPDATE, Operation.COMMIT_EPHEMERAL, Operation.PROMOTE):
            meta = {"type": fact.type, "source": fact.source or "", "ts": str(fact.ts)}
            metadata = self._get_metadata(data=fact.payload)
            meta.update(metadata)

            await collection.upsert(ids=[fact_id], documents=[text], metadatas=[meta])
