# Core concept

## Storage

MemState separates the logic from the storage. It supports several backends: In-memory (for testing), SQLite, Redis, and PostgreSQL.

_To learn how to configure specific backends, please refer to the [backends documentation](backends.md)_

You must initialize a storage backend before creating the `MemoryStore`.

=== "sync"
    ```python
    from memstate import MemoryStore, InMemoryStorage

    store = MemoryStore(storage=InMemoryStorage())
    ```

=== "async"
    ```python
    import asyncio
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    
    async def main():
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Schema registry

MemState enforces **Type Safety**. You must register Pydantic models to define what your agent is allowed to remember. This prevents the agent from storing "hallucinated" structures or malformed JSON.

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    store = MemoryStore(storage=InMemoryStorage())
    store.register_schema(typename="preference", model=UserPref)
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())
        store.register_schema(typename="preference", model=UserPref)

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Constraint (The "Magic" Layer)

This is one of the most powerful features of MemState.


**Why do we need this?**

LLMs are stateless and often forget context. An agent might try to create a "User Profile" fact, forgetting that one already exists.

* **Without Constraints:** You end up with 5 duplicate profiles in your DB.
* **With Constraints:** MemState detects the duplicate and automatically converts the **Insert** into an **Update**.

You can define:

1. `singleton_key`: A field that must be unique (e.g., `user_id` or `role`). If a fact with this key exists, MemState updates it instead of creating a new one.
2. `immutable`: If `True`, forbids changes to this fact. Useful for audit logs or system prompts.

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str

    store = MemoryStore(storage=InMemoryStorage())
    store.register_schema(
        typename="preference",
        model=UserPref,
        constraint=Constraint(singleton_key="role", immutable=False),
    )
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())
        store.register_schema(
            typename="preference",
            model=UserPref,
            constraint=Constraint(singleton_key="role", immutable=False),
        )

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Commit

When your agent generates data, you commit it. Thanks to the `commit_model` helper, you can pass Pydantic objects directly.

If a `singleton_key` constraint is active, MemState checks if the fact exists:

* **Not found:** Creates a new ID (INSERT).
* **Found:** Preserves the old ID and updates the payload (UPDATE).

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str

    store = MemoryStore(storage=InMemoryStorage())
    store.register_schema(
        typename="preference",
        model=UserPref,
        constraint=Constraint(singleton_key="role", immutable=False),
    )

    fact_id = store.commit_model(
        model=UserPref(content="I am vegetarian", role="preference"),
        session_id="session_1",
    )
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())
        store.register_schema(
            typename="preference",
            model=UserPref,
            constraint=Constraint(singleton_key="role", immutable=False),
        )

        fact_id = await store.commit_model(
            model=UserPref(content="I am vegetarian", role="preference"),
            session_id="session_1",
        )

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Rollback (Time Travel)

This is the ACID guarantee. If an agent makes a mistake, or a user changes their mind, you can revert the state to a previous point in time.

What happens during rollback:

1. **SQL/Storage:** The data is reverted to the previous state (or deleted if it was new).
2. **Vector DB:** The hooks are notified to update/delete embeddings to match the restored state.

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str

    store = MemoryStore(storage=InMemoryStorage())
    store.register_schema(
        typename="preference",
        model=UserPref,
        constraint=Constraint(singleton_key="role", immutable=False),
    )

    fact_id = store.commit_model(
        model=UserPref(content="I am vegetarian", role="preference"),
        session_id="session_1",
    )

    store.rollback(steps=1, session_id="session_1")
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage, Constraint
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())
        store.register_schema(
            typename="preference",
            model=UserPref,
            constraint=Constraint(singleton_key="role", immutable=False),
        )

        fact_id = await store.commit_model(
            model=UserPref(content="I am vegetarian", role="preference"),
            session_id="session_1",
        )

        await store.rollback(steps=1, session_id="session_1")

    if __name__ == "__main__":
        asyncio.run(main())
    ```

## Hooks

Hooks connect MemState to external systems like Vector Databases (Chroma, Qdrant).

They are part of the transaction: if a hook fails (e.g., network error), MemState **rolls back the SQL change** to prevent data drift.


_To read more about integrations please refer to the [integrations documentation](integrations.md)_

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage, Constraint, HookError
    from memstate.integrations.chroma import ChromaSyncHook
    import chromadb
    
    class UserPref(BaseModel):
        content: str
        role: str

    client = chromadb.Client()

    hook = ChromaSyncHook(
        client=client,
        collection_name="agent_memory",
        text_field="content",
        metadata_fields=["role"],
    )

    store = MemoryStore(storage=InMemoryStorage(), hooks=[hook])
    store.register_schema(
        typename="preference",
        model=UserPref,
        constraint=Constraint(singleton_key="role", immutable=False),
    )

    try:
        fact_id = store.commit_model(
            model=UserPref(content="I am vegetarian", role="preference"),
            session_id="session_1",
        )
    except HookError as e:
        print("Commit failed, operation rolled back automatically:", e)

    store.rollback(steps=1, session_id="session_1")
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage, Constraint, HookError
    from memstate.integrations.chroma import AsyncChromaSyncHook
    import chromadb
    
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        client = await chromadb.AsyncHttpClient()

        hook = AsyncChromaSyncHook(
            client=client,
            collection_name="agent_memory",
            text_field="content",
            metadata_fields=["role"],
        )

        store = AsyncMemoryStore(storage=AsyncInMemoryStorage(), hooks=[hook])
        store.register_schema(
            typename="preference",
            model=UserPref,
            constraint=Constraint(singleton_key="role", immutable=False),
        )

        try:
            fact_id = await store.commit_model(
                model=UserPref(content="I am vegetarian", role="preference"),
                session_id="session_1",
            )
        except HookError as e:
            print("Commit failed, operation rolled back automatically:", e)

        await store.rollback(steps=1, session_id="session_1")

    if __name__ == "__main__":
        asyncio.run(main())
    ```
