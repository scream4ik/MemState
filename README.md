# MemState - Transactional Memory for AI Agents

**Agents hallucinate because their memory drifts.**
SQL says one thing, the Vector DB says another. MemState keeps them in sync, always.

> **Mental Model:** MemState extends **database transactions** to your Vector DB.<br>
> One unit. One commit. One rollback.

[![PyPI version](https://img.shields.io/pypi/v/memstate.svg)](https://pypi.org/project/memstate/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/memstate?period=total&units=INTERNATIONAL_SYSTEM&left_color=GREY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/memstate)
[![Python versions](https://img.shields.io/pypi/pyversions/memstate.svg)](https://pypi.org/project/memstate/)
[![License](https://img.shields.io/pypi/l/memstate.svg)](https://github.com/scream4ik/MemState/blob/main/LICENSE)
[![Tests](https://github.com/scream4ik/MemState/actions/workflows/test.yml/badge.svg)](https://github.com/scream4ik/MemState/actions)

<p align="center">
  <img src="https://raw.githubusercontent.com/scream4ik/MemState/main/assets/docs/demo.gif" width="100%" />
  <br>
  <strong>Demo:</strong> Without MemState → memory gets inconsistent ❌ &nbsp;&nbsp;|&nbsp;&nbsp; With MemState → atomic, type-safe, rollbackable agent state ✅
  <br>
  <em>All demo scripts are available in the <code>examples/</code> folder for reproducibility.</em>
</p>

---

## Quick Start

```bash
pip install memstate[chromadb]
```

```python
from memstate import MemoryStore, Fact, SQLiteStorage, HookError
from memstate.integrations.chroma import ChromaSyncHook
import chromadb

# Storage
sqlite = SQLiteStorage("agent_memory.db")
chroma = chromadb.Client()

# Hook: sync vectors atomically with SQL
mem = MemoryStore(sqlite)
mem.add_hook(ChromaSyncHook(chroma, "agent_memory", text_field="content", metadata_fields=["role"]))

# Multi-step agent workflow
# Each commit is atomic: if vector DB fails, SQL write is automatically rolled back
mem.commit(Fact(
    type="profile_update",
    payload={"content": "User prefers vegetarian", "role": "preference"}
))

# Attempt a task that may fail
try:
    mem.commit(Fact(
        type="shopping_list",
        payload={"content": "Generate shopping list based on plan", "role": "task"}
    ))
except HookError as e:
    print("Commit failed, operation rolled back automatically:", e)

# Optional manual rollback of previous step
# mem.rollback(1)  # uncomment if you want to undo the last saved fact
```

That's it. Your agent memory is now transactional.

---

## LangGraph integration

```python
from memstate.integrations.langgraph import MemStateCheckpointer

checkpointer = MemStateCheckpointer(memory=mem)
app = workflow.compile(checkpointer=checkpointer)
```

---

## Why MemState exists

### The Problem

AI agents usually store memory in **two places**:

* **SQL**: structured facts (preferences, task history)
* **Vector DB**: semantic search (embeddings for RAG)

These two stores **drift easily**. Even small failures create inconsistency:

```python
# Step 1: SQL write succeeds
db.update("user_city", "London")

# Step 2: Vector DB update fails
vectors.upsert("User lives in London")  # ❌ failed

# Final state:
# SQL: London
# Vectors: New York (stale embedding)
```

**Result:** ghost vectors, inconsistent state, unpredictable agent behavior.<br>
Drift accumulates silently, agents continue retrieving outdated or mismatched memory.

---

### Why this happens

Real-world agent pipelines create drift **even with correct code**, because:

* Vector DB upserts are **not atomic**
* Retried writes can produce **duplicates or stale embeddings**
* Async ingestion leads to **race conditions**
* LLM outputs often contain **non-schema JSON**
* Embedding model/version changes create **semantic mismatch**
* SQL writes succeed while vector DB fails, partial updates persist

These issues are **invisible until retrieval fails**, making debugging extremely difficult.
MemState prevents this by enforcing **atomic memory operations**: if any part fails, the whole operation is rolled back.

---

## The Solution

MemState makes memory operations **atomic**:

```
SQL write + Vector upsert
→ succeed together or rollback together
```

## Key features

* **Atomic commits**: SQL and Vector DB stay in sync
* **Rollback**: undo N steps across SQL and vectors
* **Type safety**: Pydantic validation prevents malformed JSON
* **Append-only Fact Log**: full versioned history
* **Crash-safe atomicity**: if a vector DB write fails, the entire memory operation (SQL + vector) is **rolled back**.  
  No partial writes, no ghost embeddings, no inconsistent checkpoints.

---

## Proof: Benchmark under failure

1000 memory updates with **10% random vector DB failures**:

| METRIC                 | MANUAL SYNC | MEMSTATE |
| ---------------------- | ----------- | -------- |
| SQL Records            | 1000        | 900      |
| Vector Records         | 910         | 900      |
| **DATA DRIFT**         | **90**      | **0**    |
| **INCONSISTENCY RATE** | **9.0%**    | **0.0%** |

**Why 900 instead of 1000?**
MemState refuses partial writes.<br>
If vector sync fails, SQL is rolled back automatically.

Manual sync produces silent drift.<br>
Drift compounds over time, stale embeddings keep being retrieved forever.

Full benchmark script: [`benchmarks/`](benchmarks/)

---

## Ideal for

* Long-running agents
* LangGraph workflows
* RAG systems requiring strict DB <-> embedding consistency
* Local-first / offline-first setups (SQLite/Redis + Chroma/Qdrant/FAISS)
* Deterministic, debuggable agentic pipelines

---

## Storage backends

All backends participate in the same atomic commit cycle:

* SQLite (JSON1)
* Redis
* In-memory
* Custom backends via simple interface

Vector sync hooks: ChromaDB (more coming)

---

## When you don't need it

* Your agent is fully stateless
* You store everything in a single SQL table
* You never update embeddings after creation

If your pipelines depend on RAG or long-term state, consistency **is** required - most teams realize this only when debugging unpredictable retrieval.

---

## Status

**Early Access.**
Production-ready for local agents and prototypes. API is stable (Semantic Versioning).

Community contributions welcome.

---

## Install

```bash
pip install memstate[chromadb]
```

⭐ **[Star the repo](https://github.com/scream4ik/MemState)**
🐛 **[Report issues](https://github.com/scream4ik/MemState/issues)**

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
