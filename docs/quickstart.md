# Quickstart

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

=== "uv"
    ```bash
    uv add memstate
    ```

=== "pip"
    ```bash
    pip install memstate
    ```

## Usage

Let's build a simple memory for an agent. In this scenario, the user states a preference, then accidentally contradicts themselves, and we use **rollback** to undo the mistake instantly.

=== "sync"
    ```python
    from pydantic import BaseModel
    from memstate import MemoryStore, InMemoryStorage

    # 1. Define schema
    class UserPref(BaseModel):
        content: str
        role: str

    # 2. Init memory
    store = MemoryStore(storage=InMemoryStorage())
    store.register_schema("preference", UserPref)

    # 3. Commit correct data
    fact_id = store.commit_model(
        model=UserPref(content="I am vegetarian", role="preference"), session_id="session_1"
    )
    print("Current state:", store.get(fact_id))

    # 4. Agent makes a mistake (writes wrong data)
    print("--- Making a mistake... ---")
    store.commit_model(
        model=UserPref(content="I love steak"), fact_id=fact_id, session_id="session_1"
    )
    print("Current state:", store.get(fact_id))

    # 5. Undo!
    store.rollback(steps=1, session_id="session_1")
    print("--- Rolled back! ---")

    # Verify: The last transaction is the vegetarian one
    print("Restored state:", store.get(fact_id))
    ```

=== "async"
    ```python
    import asyncio
    from pydantic import BaseModel
    from memstate import AsyncMemoryStore, AsyncInMemoryStorage
    
    # 1. Define schema
    class UserPref(BaseModel):
        content: str
        role: str
    
    async def main():
        # 2. Init memory
        store = AsyncMemoryStore(storage=AsyncInMemoryStorage())
        store.register_schema("preference", UserPref)

        # 3. Commit correct data
        fact_id = await store.commit_model(
            model=UserPref(content="I am vegetarian", role="preference"), session_id="session_1"
        )
        print("Current state:", await store.get(fact_id))
    
        # 4. Agent makes a mistake (writes wrong data)
        print("--- Making a mistake... ---")
        await store.commit_model(
            model=UserPref(content="I love steak"), fact_id=fact_id, session_id="session_1"
        )
        print("Current state:", await store.get(fact_id))
    
        # 5. Undo!
        await store.rollback(steps=1, session_id="session_1")
        print("--- Rolled back! ---")
    
        # Verify: The last transaction is the vegetarian one
        print("Restored state:", await store.get(fact_id))

    if __name__ == "__main__":
        asyncio.run(main())
    ```

### What's next?

This example uses in-memory storage. In a real-world agent, you will want to sync this data with a **Vector Database** (for RAG) and persist it to **Postgres/SQLite**.

Check out the [Documentation](documentation/index.md) section to see how to enable Atomic RAG Sync.
