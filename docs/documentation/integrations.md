# Integrations

## LangChain / LangGraph checkpointer

MemState provides a drop-in persistence layer for LangGraph agents. It replaces the default checkpointer to ensure state is stored transactionally and synchronized with your Vector DB.

### Install the requirements

=== "uv"
    ```bash
    uv add memstate[langgraph]
    ```

=== "pip"
    ```bash
    pip install memstate[langgraph]
    ```

### Usage

=== "sync"
    ```python
    from memstate.integrations.langgraph import MemStateCheckpointer
    
    checkpointer = MemStateCheckpointer(memory=mem)
    app = workflow.compile(checkpointer=checkpointer)
    ```

=== "async"
    ```python
    from memstate.integrations.langgraph import AsyncMemStateCheckpointer
    
    checkpointer = AsyncMemStateCheckpointer(memory=mem)
    app = workflow.compile(checkpointer=checkpointer)
    ```

## Qdrant Hook

Automatically syncs committed facts to a Qdrant collection. Supports **FastEmbed** out of the box for local embeddings.

### Install the requirements

=== "uv"
    ```bash
    uv add memstate[qdrant]
    ```

=== "pip"
    ```bash
    pip install memstate[qdrant]
    ```

### Usage

=== "sync"
    ```python
    from memstate import MemoryStore, InMemoryStorage
    from memstate.integrations.qdrant import QdrantSyncHook
    import qdrant_client

    client = qdrant_client.QdrantClient(":memory:")

    hook = QdrantSyncHook(
        client=client,
        collection_name="agent_memory",
        text_field="content",
        metadata_fields=["role"],
    )

    store = MemoryStore(storage=InMemoryStorage(), hooks=[hook])
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    from memstate.integrations.qdrant import AsyncQdrantSyncHook
    import qdrant_client

    async def main():
        client = qdrant_client.AsyncQdrantClient(":memory:")

        hook = AsyncQdrantSyncHook(
            client=client,
            collection_name="agent_memory",
            text_field="content",
            metadata_fields=["role"],
        )

        store = AsyncMemoryStore(storage=AsyncInMemoryStorage(), hooks=[hook])

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Chroma Hook

Automatically syncs committed facts to a ChromaDB collection.

### Install the requirements

=== "uv"
    ```bash
    uv add memstate[chromadb]
    ```

=== "pip"
    ```bash
    pip install memstate[chromadb]
    ```

### Usage

=== "sync"
    ```python
    from memstate import MemoryStore, InMemoryStorage
    from memstate.integrations.chroma import ChromaSyncHook
    import chromadb

    client = chromadb.Client()

    hook = ChromaSyncHook(
        client=client,
        collection_name="agent_memory",
        text_field="content",
        metadata_fields=["role"],
    )

    store = MemoryStore(storage=InMemoryStorage(), hooks=[hook])
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    from memstate.integrations.chroma import AsyncChromaSyncHook
    import chromadb

    async def main():
        client = await chromadb.AsyncHttpClient()

        hook = AsyncChromaSyncHook(
            client=client,
            collection_name="agent_memory",
            text_field="content",
            metadata_fields=["role"],
        )

        store = AsyncMemoryStore(storage=AsyncInMemoryStorage(), hooks=[hook])

    if __name__ == "__main__":
        asyncio.run(main())
    ```
