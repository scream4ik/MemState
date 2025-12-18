# Backends

MemState separates logic from storage. You can start with `InMemoryStorage` for testing and switch to `PostgresStorage` or `RedisStorage` for production without changing your agent logic.

**Pro Tip: Dependency Injection**

MemState fully supports **Dependency Injection**. For all backends (Postgres, Redis, SQLite), you can pass an existing connection object instead of a connection string.

## PostgreSQL

Uses `SQLAlchemy` + `psycopg`. It supports JSONB for efficient querying.

### Install the requirements

=== "uv"
    ```bash
    uv add memstate[postgres]
    ```

=== "pip"
    ```bash
    pip install memstate[postgres]
    ```

### Initialize the storage

=== "sync"
    ```python
    from memstate import MemoryStore
    from memstate.backends.postgres import PostgresStorage

    url = "postgresql+psycopg://user:pass@localhost:5432/db_name"
    storage = PostgresStorage(url)
    store = MemoryStore(storage=storage)
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore
    from memstate.backends.postgres import AsyncPostgresStorage
    
    async def main():
        url = "postgresql+psycopg://user:pass@localhost:5432/db_name"
        storage = AsyncPostgresStorage(url)
        # Important: You must create tables explicitly in async mode
        await store.create_tables()

        store = AsyncMemoryStore(storage=storage)

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Redis

Stores facts as JSON strings and maintains sets for efficient indexing.

### Install the requirements

=== "uv"
    ```bash
    uv add memstate[redis]
    ```

=== "pip"
    ```bash
    pip install memstate[redis]
    ```

### Initialize the storage

=== "sync"
    ```python
    from memstate import MemoryStore
    from memstate.backends.redis import RedisStorage

    storage = RedisStorage("redis://localhost:6379/0")
    store = MemoryStore(storage=storage)
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore
    from memstate.backends.redis import AsyncRedisStorage
    
    async def main():
        storage = AsyncRedisStorage("redis://localhost:6379/0")
        store = AsyncMemoryStore(storage=storage)

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## SQLite

The default, zero-config backend. Uses the JSON1 extension for querying.

### Install the requirements

For synchronous use, SQLite is built-in.

For **async** use, you need `aiosqlite`.

=== "uv"
    ```bash
    uv add memstate[sqlite-async]
    ```

=== "pip"
    ```bash
    pip install memstate[sqlite-async]
    ```

### Initialize the storage

=== "sync"
    ```python
    from memstate import MemoryStore, SQLiteStorage

    storage = SQLiteStorage("memory.db")
    store = MemoryStore(storage=storage)
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore, AsyncSQLiteStorage
    
    async def main():
        storage = AsyncSQLiteStorage("memory.db")
        # Important: Connect explicitly
        await storage.connect()

        store = AsyncMemoryStore(storage=storage)

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## In-memory

Non-persistent storage. Best for testing and prototyping.

### Initialize the storage

=== "sync"
    ```python
    from memstate import MemoryStore, InMemoryStorage

    storage = InMemoryStorage()
    store = MemoryStore(storage=storage)
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    
    async def main():
        storage = AsyncInMemoryStorage()
        store = AsyncMemoryStore(storage=storage)

    if __name__ == "__main__":
        asyncio.run(main())
    ```
