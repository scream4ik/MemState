# MemState — Transactional Memory for AI Agents

**Keeps SQL and Vector DBs in sync. No drift. No ghost data. ACID-like consistency for agent state.**

[![PyPI version](https://img.shields.io/pypi/v/memstate.svg)](https://pypi.org/project/memstate/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/memstate?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/memstate)
[![Python versions](https://img.shields.io/pypi/pyversions/memstate.svg)](https://pypi.org/project/memstate/)
[![License](https://img.shields.io/pypi/l/memstate.svg)](https://github.com/scream4ik/MemState/blob/main/LICENSE)
[![Tests](https://github.com/scream4ik/MemState/actions/workflows/test.yml/badge.svg)](https://github.com/scream4ik/MemState/actions)

---

## Why MemState exists

AI agents usually store memory in two places:

* **SQL** (structured facts)
* **Vector DB** (semantic search context)

These two **drift** easily:

### ❌ Example of real-world corruption

```python
# Step 1: SQL write succeeds
db.update("user_city", "London")

# Step 2: Vector DB update fails (timeout)
vectors.upsert("User lives in London")  # ❌ failed

# Final state:
SQL: London
Vectors: New York
→ Agent retrieves stale context and behaves unpredictably
```

Failures, crashes, retries, malformed payloads — all silently accumulate “ghost vectors” and inconsistent state.

**Vector DBs don't have transactions.
JSON memory has no schema.
Agents drift over time.**

---

## What MemState does

MemState makes all memory operations **atomic**:

```
SQL write + Vector upsert
→ succeed together or rollback together
```

Also provides:

* **Rollback**: undo N steps (SQL + vectors)
* **Type safety**: Pydantic schema validation
* **Append-only Fact Log**: full version history
* **Crash safety**: WAL replay for vector sync

<p align="center">
  <img src="https://raw.githubusercontent.com/scream4ik/MemState/main/assets/docs/demo.gif" width="100%" />
  <br>
  <strong>Demo:</strong> Without MemState → memory gets inconsistent ❌ &nbsp;&nbsp;|&nbsp;&nbsp; With MemState → atomic, type-safe, rollbackable agent state ✅
  <br>
  <em>All demo scripts are available in the <code>examples/</code> folder for reproducibility.</em>
</p>

---

## Minimal example (copy–paste)

```bash
pip install memstate[chromadb]
```

```python
from memstate import MemoryStore, Fact, SQLiteStorage
from memstate.integrations.chroma import ChromaSyncHook
import chromadb

# Storage
sqlite = SQLiteStorage("state.db")
chroma = chromadb.Client()

# Hook: sync vectors atomically with SQL
hook = ChromaSyncHook(
    client=chroma,
    collection_name="memory",
    text_field="content",
    metadata_fields=["role"]
)

mem = MemoryStore(sqlite)
mem.add_hook(hook)

# Atomic commit: SQL + Vectors
mem.commit(Fact(
    type="profile_update",
    payload={"content": "User prefers vegetarian", "role": "preference"}
))

# Rollback: removes SQL row + vector entry
mem.rollback(1)
```

---

## How MemState compares

| Operation                   | Without MemState     | With MemState       |
| --------------------------- | -------------------- | ------------------- |
| Vector DB write fails       | ❌ SQL+Vector diverge | ✔ auto-rollback     |
| Partial workflow crash      | ❌ ghost vectors      | ✔ consistent        |
| LLM outputs malformed JSON  | ❌ corrupt state      | ✔ schema validation |
| Need to undo last N actions | ❌ impossible         | ✔ rollback()        |
| Need deterministic behavior | ❌ drift              | ✔ ACID-like         |

---

## Ideal for

* **Long-running agents**
* **LangGraph projects** needing reliable state
* **RAG systems** where DB data must match embeddings
* **Local-first setups** (SQLite + Chroma/Qdrant/FAISS)

---

## LangGraph integration

```python
from memstate.integrations.langgraph import MemStateCheckpointer

checkpointer = MemStateCheckpointer(memory=mem)
app = workflow.compile(checkpointer=checkpointer)
```

---

## Storage backends

* SQLite (JSON1)
* Redis
* In-memory
* Custom backends via simple interface

Vector sync hooks: ChromaDB (more coming)

---

## Status

**Alpha.** API stable enough for prototypes and local agents.
Semantic Versioning.

---

## License

Licensed under the [Apache 2.0 License](LICENSE).

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
