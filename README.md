# MemState - Transactional Memory for AI Agents

[![PyPI version](https://img.shields.io/pypi/v/memstate.svg)](https://pypi.org/project/memstate/)
[![Python versions](https://img.shields.io/pypi/pyversions/memstate.svg)](https://pypi.org/project/memstate/)
[![License](https://img.shields.io/pypi/l/memstate.svg)](https://github.com/scream4ik/MemState/blob/main/LICENSE)
[![Tests](https://github.com/scream4ik/MemState/actions/workflows/test.yml/badge.svg)](https://github.com/scream4ik/MemState/actions)

**ACID-like consistency layer for agent state.**
Ensures Structured Data (SQL) and Semantic Data (Vector Embeddings) stay synchronized, reversible, and type-safe.

<p align="center">
  <img src="https://raw.githubusercontent.com/scream4ik/MemState/main/assets/docs/demo.gif" width="100%" />
  <br>
  <strong>Demo:</strong> Without MemState → memory gets inconsistent ❌ &nbsp;&nbsp;|&nbsp;&nbsp; With MemState → atomic, type-safe, rollbackable agent state ✅
  <br>
  <em>All demo scripts are available in the <code>examples/</code> folder for reproducibility.</em>
</p>

---

## The Problem: Agent State Corruption

In most frameworks, agent state is treated as a second-class citizen:
*   Scattered JSON blobs.
*   Ad-hoc RAG embeddings that drift from the source of truth.
*   Inconsistent partial updates during failures.
*   No rollback mechanisms.

This leads to **Data Drift**: The SQL database says one thing, the Vector DB says another. The agent becomes unpredictable and hallucinates because its memory is fractured.

**Agents need reliable state. Not a document dump.**

---

## MemState: A Consistency Layer

MemState treats agent memory as a transactional system, offering database semantics for application logic:

*   **⚛️ Atomicity** — SQL and Vector DB changes succeed or rollback together.
*   **🛡️ Isolation** — Intermediate steps in a workflow never leak to the main memory.
*   **⏪ Rollback** — Revert any number of committed steps instantly.
*   **🔒 Schema Safety** — Pydantic validation prevents data corruption at runtime.

It is the missing architecture between your Agent Logic and your Storage.

---

## Quick Example

```bash
pip install memstate[chromadb]
```

```python
from memstate import MemoryStore, Fact, SQLiteStorage
from memstate.integrations.chroma import ChromaSyncHook
import chromadb

# 1. Setup Storage
sqlite = SQLiteStorage("state.db")
chroma = chromadb.Client()

# 2. Define Transactional Sync
# This hook binds the Vector DB to the Atomic Lifecycle of the MemoryStore
hook = ChromaSyncHook(
    client=chroma,
    collection_name="agent_memory",
    text_field="content",
    metadata_fields=["role", "topic"]
)

memory = MemoryStore(sqlite)
memory.add_hook(hook=hook)

# 3. Atomic Write
# Persists to SQLite AND upserts to ChromaDB.
# If either fails, both are rolled back.
memory.commit(Fact(
    payload={
        "content": "User prefers vegetarian options",
        "role": "profile"
    }
))

# 4. Rollback
# Restores SQLite state AND deletes the vector from ChromaDB.
memory.rollback(1)
```

---

## Why this matters

Standard tooling stores memory as a single opaque document. This breaks for:
*   **Long-running agents** where state accumulates errors.
*   **Multi-step workflows** requiring intermediate checkpoints.
*   **Compliance/Audit systems** needing a ledger of changes.
*   **Hybrid Search** where structured state and RAG context must match.

MemState introduces **determinism** to your agent's behavior.

---

## Integrates with LangGraph

Drop-in replacement for the default checkpointer.
Your graph state becomes structured, queryable, and transaction-safe.

```python
from memstate.integrations.langgraph import MemStateCheckpointer

checkpointer = MemStateCheckpointer(memory=memory)
app = workflow.compile(checkpointer=checkpointer)
```

---

## Key Capabilities

*   **Hybrid Transactional Storage** (SQL + Vectors)
*   **Pydantic Schema Enforcement**
*   **Fact-based Versioning** (Append-only Log)
*   **Multi-step Atomic Commits**
*   **Pluggable Backends:** SQLite (JSON1), Redis, In-Memory

---

## Status

**Alpha.** The API is stable enough for building reliable agent prototypes.
We follow Semantic Versioning.

---

## 📄 License

Licensed under the [Apache 2.0 License](LICENSE).

---

## 🤝 Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
