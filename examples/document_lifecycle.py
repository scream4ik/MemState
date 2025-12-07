import os
import shutil

import chromadb

from memstate import Fact, MemoryStore
from memstate.backends.sqlite import SQLiteStorage
from memstate.integrations.chroma import ChromaSyncHook


def clean_environment():
    """Removes old database files for a clean run."""
    if os.path.exists("lifecycle_demo.db"):
        os.remove("lifecycle_demo.db")
    if os.path.exists("chroma_db_demo"):
        shutil.rmtree("chroma_db_demo")


def print_state(step_name, fact_id, sql_store, chroma_collection):
    """Helper to fetch and compare data from both DBs."""
    print(f"\n--- CHECKING STATE: {step_name} ---")

    # 1. Check SQL
    sql_data = sql_store.load(fact_id)
    print(f"[SQLite] ID: {fact_id}")
    print(f"         Payload: {sql_data['payload']}")

    # 2. Check Vector DB
    vector_data = chroma_collection.get(ids=[fact_id])
    if vector_data["ids"]:
        print(f"[Chroma] ID: {vector_data['ids'][0]}")
        print(f"         Document (Embedding Source): '{vector_data['documents'][0]}'")
        print(f"         Metadata: {vector_data['metadatas'][0]}")
    else:
        print(f"[Chroma] ❌ Not Found!")


# --- MAIN DEMO ---


def run_demo():
    clean_environment()
    print(f"🚀 Starting Document Lifecycle Demo (SQL + Chroma Sync)\n")

    # 1. Setup Infra
    sqlite = SQLiteStorage("lifecycle_demo.db")

    # Use persistent Chroma to simulate real disk usage
    chroma_client = chromadb.PersistentClient(path="chroma_db_demo")

    # 2. Configure Sync Hook
    # We want to sync the 'content' field as the vector, and 'status' as metadata
    hook = ChromaSyncHook(
        client=chroma_client, collection_name="docs_memory", text_field="content", metadata_fields=["status", "author"]
    )

    memory = MemoryStore(sqlite)
    memory.add_hook(hook)
    collection = chroma_client.get_collection("docs_memory")

    # =========================================================================
    # STEP 1: CREATE (INSERT)
    # =========================================================================
    print(f"1️⃣  Creating new document...")

    fact = Fact(
        type="doc",
        payload={"content": "Project Alpha is currently in planning phase.", "status": "draft", "author": "Alice"},
    )
    doc_id = memory.commit(fact)

    print_state("AFTER INSERT", doc_id, sqlite, collection)

    # =========================================================================
    # STEP 2: UPDATE (MODIFY)
    # =========================================================================
    print(f"\n2️⃣  Updating document (content + metadata)...")

    # We use the SAME fact ID to perform an update
    memory.commit(
        Fact(
            id=doc_id,
            type="doc",
            payload={
                "content": "Project Alpha has been CANCELLED.",  # Content changed
                "status": "archived",  # Metadata changed
                "author": "Alice",
            },
        )
    )

    print_state("AFTER UPDATE", doc_id, sqlite, collection)

    # =========================================================================
    # STEP 3: DELETE (ROLLBACK/REMOVE)
    # =========================================================================
    print(f"\n3️⃣  Deleting document...")

    memory.delete(doc_id)

    # Manual verification
    print(f"\n--- CHECKING STATE: AFTER DELETE ---")

    sql_check = sqlite.load(doc_id)
    chroma_check = collection.get(ids=[doc_id])

    if sql_check is None:
        print(f"[SQLite] ✅ Deleted (None)")
    else:
        print(f"[SQLite] ❌ Still exists!")

    if not chroma_check["ids"]:
        print(f"[Chroma] ✅ Deleted (Empty)")
    else:
        print(f"[Chroma] ❌ Still exists!")

    print(f"\n✨ Demo Complete: SQL and Vector DB stayed perfectly in sync.")
    clean_environment()


if __name__ == "__main__":
    run_demo()
