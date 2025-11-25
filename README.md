# 🧠 MemState: The "Git" for AI Agent Memory

**Stop building agents on JSON blobs and hope.**
MemState is a transactional, typed, and reversible state management layer for LLM Agents.

It replaces "Context Stuffing" and "Vector Soup" with a deterministic **Source of Truth**.

---

## ⚡ Why MemState?

Most agent memory systems today are just wrappers around Vector DBs. This leads to:
*   **Hallucinations:** The agent retrieves two contradictory facts (e.g., "User likes cats" vs "User hates cats") and guesses.
*   **State Corruption:** No validation. Agents overwrite critical data (like IDs or balances) with garbage.
*   **No Undo Button:** If an agent makes a mistake, you can't roll back the state. You have to wipe the memory.

**MemState is different.** It treats Agent Memory like a Database, not a text dump.

## ✨ Key Features

*   **🛡️ Type-Safe:** Uses `Pydantic` schemas. If an agent tries to save a string into an `age: int` field, it fails *before* corruption happens.
*   **⏪ Time Travel:** Every change is a transaction. You can `rollback(steps=1)` to undo an agent's mistake instantly.
*   **🔒 Constraints:** Enforce logic like "One User Profile per Email" (`Singleton`). No more duplicate profiles.
*   **🔌 Hybrid Hooks:** Use MemState as the Source of Truth and automatically sync to Vector DBs (Chroma, Qdrant) via hooks.
*   **🔍 JSON Querying:** Fast, structured search (`WHERE role = 'admin'`) via SQLite JSON1 extension. No need to embed everything.

---

## 🚀 Quick Start

### Installation
```bash
# Clone the repo
git clone https://github.com/scream4ik/MemState.git
cd MemState

# Create a virtual environment
uv venv

# Install dependencies
uv sync
```

### Usage

```python
from memstate.storage import MemoryStore, Fact, Constraint
from memstate.backends.sqlite import SQLiteStorage
from pydantic import BaseModel

# 1. Define what your agent is allowed to remember
class UserProfile(BaseModel):
    username: str
    level: int = 1

# 2. Initialize Storage (SQLite)
storage = SQLiteStorage("agent_brain.db")
memory = MemoryStore(storage)

# 3. Register Schema with Rules
# Rule: "username" must be unique. If it exists, UPDATE it (don't duplicate).
memory.register_schema("user", UserProfile, Constraint(singleton_key="username"))

# 4. Commit a Fact (Transactional)
memory.commit(
    Fact(type="user", payload={"username": "neo", "level": 99}),
    actor="Agent_Smith"
)

# 5. Agent makes a mistake? Rollback!
memory.update(fact_id="...", patch={"payload": {"level": 0}})  # Oops
print("Before rollback:", memory.query(typename="user")[0]['payload'])

memory.rollback(1)
print("After rollback:", memory.query(typename="user")[0]['payload'])
# Level is back to 99.
```

---

## 💡 Use Cases

### 1. Financial & Legal Bots (Compliance)
**Problem:** An LLM hallucinates a loan interest rate.
**Solution:** Use `Immutable` constraints for signed contracts. Use `Transaction Logs` to audit exactly *when* and *why* a fact was changed.

### 2. RPGs & Interactive Fiction
**Problem:** The player picked up a key, used it, then lost it. The LLM forgets the door is now unlocked.
**Solution:** Use MemState to track the World State (`door_status: open`). If the player dies, use `rollback()` to reset the state to the last checkpoint perfectly.

### 3. Form Filling (Slot Filling)
**Problem:** User corrects themselves ("My car is a BMW... wait, no, an Audi"). Vector DBs return both.
**Solution:** Use `Singleton` constraint on `car_model`. The correction automatically overwrites the old fact. The agent only sees the latest truth.

---

## 📂 Demos

Check the `examples/` folder for runnable scripts:

1.  **`examples/main_demo.py`**
    *   Full tour: Schemas, Singletons, Hallucination Correction via Rollback.

2.  **`examples/rag_hook_demo.py`**
    *   **Hybrid Memory Pattern.**
    *   Shows how to use MemState as the "Master DB" that automatically syncs text to a mock Vector DB for RAG.
    *   Demonstrates automatic cleanup: Delete a fact in SQL -> It vanishes from Vectors.

---

## 🛠 Status
**Alpha / MVP.**
Ready for local development.

Supports: `InMemoryStorage`, `RedisStorage`, `SQLiteStorage`.

Planned: `PostgresStorage`.

---

## 📄 License

Licensed under the [Apache 2.0 License](LICENSE).

---

## 🤝 Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## ⭐️ Like the idea?

Star the repo and share feedback — we’re building in the open.
