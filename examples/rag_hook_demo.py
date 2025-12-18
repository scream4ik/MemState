import os
import sys
from typing import Dict, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic import BaseModel

from memstate import Fact, InMemoryStorage, MemoryStore


class KnowledgeBase(BaseModel):
    content: str


class UserPref(BaseModel):
    theme: str


# --- Simulated Vector Store ---
# In real life, this would use OpenAI Embeddings and Qdrant/Chroma


class MockVectorDB:
    def __init__(self):
        self.index: Dict[str, str] = {}  # id -> text content
        print("🔵 [VectorDB] Initialized (Empty)")

    def upsert(self, doc_id: str, text: str):
        # Here we would do: vector = openai.embed(text) -> pinecone.upsert(vector)
        self.index[doc_id] = text.lower()
        print(f"🔵 [VectorDB] Indexed doc {doc_id}: '{text[:30]}...'")

    def delete(self, doc_id: str):
        if doc_id in self.index:
            del self.index[doc_id]
            print(f"🔵 [VectorDB] Deleted doc {doc_id}")

    def search(self, query: str) -> List[str]:
        # Emulating semantic search (dumb substring search)
        print(f"🔎 [VectorDB] Searching for: '{query}'...")
        results = []
        q = query.lower()
        for doc_id, text in self.index.items():
            if q in text:
                results.append(doc_id)
        return results


# --- 2. The Hook (The glue Between SQL and Vectors) ---


class RAGSyncHook:
    def __init__(self, vector_db: MockVectorDB):
        self.vector_db = vector_db
        # We are only interested in facts of the "knowledge_base" type.
        self.target_types = {"knowledge_base", "chat_log"}

    def __call__(self, op: str, fact_id: str, data: Fact | None):
        # data is the state of the fact. If DELETE, this is the state BEFORE deletion.

        # Type checking (do not vectorize system data)
        if not data or data.type not in self.target_types:
            return

        # Processing of deletion
        if op == "DELETE":
            self.vector_db.delete(fact_id)
            return

        # Text extraction for vectorization
        payload = data.payload
        # Trying to find a text field
        text_content = payload.get("content") or payload.get("message") or payload.get("summary")

        if not text_content:
            return

        # Upsert (Insert or Update - for a vector database, this is the same thing)
        if op in ("COMMIT", "UPDATE", "COMMIT_EPHEMERAL"):
            self.vector_db.upsert(fact_id, text_content)


# --- 3. Main scenario ---


def main():
    # Initialization
    vector_db = MockVectorDB()  # Our "Pinecone"
    hook = RAGSyncHook(vector_db)  # Our "Synchronizer"

    storage = InMemoryStorage()  # Our "Postgres"
    memory = MemoryStore(storage)  # Our "Brain"
    memory.register_schema("knowledge_base", KnowledgeBase)
    memory.register_schema("user_pref", UserPref)

    # Add hook
    memory.add_hook(hook)

    print("\n--- Phase 1: Ingestion ---")
    # We simply commit the facts to MemState. The hook will automatically transfer them to Vectors.

    doc1 = KnowledgeBase(content="The moon is made of rock and dust.")
    doc2 = KnowledgeBase(content="Mars is known as the Red Planet due to iron oxide.")
    doc3 = UserPref(theme="dark")  # This should NOT be in vectors (filter by type)

    memory.commit_model(model=doc1, session_id="session_1")
    doc2_id = memory.commit_model(model=doc2, session_id="session_1")
    memory.commit_model(model=doc3, session_id="session_1")

    print("\n--- Phase 2: RAG Search (Emulation) ---")
    # User asks: "Tell me about the red planet"
    user_query = "Red Planet"

    # Searching for IDs in a vector database
    found_ids = vector_db.search(user_query)

    if found_ids:
        print(f"✅ Found relevant IDs: {found_ids}")
        # Loading complete, reliable data from MemState (SQL)
        # A vector database may return old garbage, but SQL will always return what is relevant.
        for fid in found_ids:
            fact = memory.get(fid)
            print(f"   -> Retrieved content: {fact['payload']['content']}")
            print(f"   -> Metadata (Timestamp): {fact['ts']}")
    else:
        print("❌ Nothing found.")

    print("\n--- Phase 3: Data Correction (Correction of facts) ---")
    # Let's say we realized that the information about Mars is incomplete.
    # We update ONLY MemState.

    print("🛠 Updating Mars fact in SQL...")
    memory.update(doc2_id, {"payload": {"content": "Mars is the Red Planet and has two moons: Phobos and Deimos."}})

    # Check if the vector index has been updated AUTOMATICALLY?
    print("🔎 Searching again for 'Phobos'...")
    found_ids = vector_db.search("Phobos")  # This word didn't exist before.

    if found_ids:
        print(f"✅ Magic! Found ID via new keyword: {found_ids[0]}")
    else:
        print(f"❌ Sync failed.")

    print("\n--- Phase 4: Forgetting (Deletion) ---")
    # Deleting a fact from the database
    print("🗑 Deleting Mars fact...")
    memory.delete(session_id="session_1", fact_id=doc2_id)

    # Checking the search
    found_ids = vector_db.search("Mars")
    if not found_ids:
        print("✅ Clean. Fact removed from Vector DB automatically.")
    else:
        print("❌ Ghost data remains!")


if __name__ == "__main__":
    main()
