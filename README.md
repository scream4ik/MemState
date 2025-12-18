# MemState — Transactional Memory for AI Agents

**Agents hallucinate because their memory drifts.**
SQL says one thing, the Vector DB says another. MemState keeps them in sync, always.

> **Mental Model:** MemState extends **database transactions** to your Vector DB.<br>
> One unit. One commit. One rollback.

[![PyPI version](https://img.shields.io/pypi/v/memstate.svg)](https://pypi.org/project/memstate/)
[![Python versions](https://img.shields.io/pypi/pyversions/memstate.svg)](https://pypi.org/project/memstate/)
[![License](https://img.shields.io/pypi/l/memstate.svg)](https://github.com/scream4ik/MemState/blob/main/LICENSE)
[![Tests](https://github.com/scream4ik/MemState/actions/workflows/test.yml/badge.svg)](https://github.com/scream4ik/MemState/actions)

---

**Documentation**: <a href="https://scream4ik.github.io/MemState/" target="_blank">https://scream4ik.github.io/MemState/</a>

**Source Code**: <a href="https://github.com/scream4ik/MemState" target="_blank">https://github.com/scream4ik/MemState</a>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/scream4ik/MemState/main/assets/docs/demo.gif" width="100%" alt="MemState Demo" />
</p>

---

## ⚡ Quick Start

```bash
pip install memstate[chromadb]
```

```python
from pydantic import BaseModel
from memstate import MemoryStore, SQLiteStorage, HookError
from memstate.integrations.chroma import ChromaSyncHook
import chromadb

# 1. Define Data Schema
class UserPref(BaseModel):
    content: str
    role: str

# 2. Setup Storage (Local)
sqlite = SQLiteStorage("agent_memory.db")
chroma = chromadb.Client()

# 3. Initialize with Sync Hook
mem = MemoryStore(sqlite)
mem.add_hook(ChromaSyncHook(chroma, "agent_memory", text_field="content", metadata_fields=["role"]))
mem.register_schema("preference", UserPref)

# 4. Atomic Commit
# Validates Pydantic model -> Writes SQL -> Upserts Vector
try:
    mem.commit_model(model=UserPref(content="User prefers vegetarian", role="preference"))
except HookError as e:
    print("Commit failed, SQL rolled back automatically:", e)

# 5. Undo (if needed)
# mem.rollback(1)
```

👉 **[See full Documentation & Examples](https://scream4ik.github.io/MemState/)**

---

## The Problem

AI agents usually store memory in **two places**: SQL (structured facts) and Vector DB (semantic search).

These two stores **drift** easily. If a network request to the Vector DB fails, or the agent crashes mid-operation, you end up with **"Split-Brain" memory**:
*   **SQL:** "User lives in London"
*   **Vector DB:** "User lives in New York" (Stale embedding)

**Result:** The agent retrieves wrong context and hallucinates.

## The Solution

MemState acts as a **Transactional Layer**. It ensures that every memory operation is **Atomic**:

*   **Atomic Commits:** SQL and Vector DB stay in sync. If one fails, both rollback.
*   **Type Safety:** Pydantic validation prevents LLMs from corrupting your JSON schema.
*   **Time Travel:** Undo N steps with `rollback(n)`. Useful for user corrections.

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

## Ecosystem

| Category | Supported |
| :--- | :--- |
| **Storage Backends** | SQLite, PostgreSQL (JSONB), Redis, In-Memory |
| **Vector Hooks** | ChromaDB, Qdrant (more coming) |
| **Frameworks** | **LangGraph** (Native Checkpointer), LangChain |
| **Runtime** | Sync & **Async** (FastAPI ready) |

### LangGraph Integration

```python
from memstate.integrations.langgraph import MemStateCheckpointer

checkpointer = MemStateCheckpointer(memory=mem)
app = workflow.compile(checkpointer=checkpointer)
```

---

## Status

**Beta.** The API is stable. Suitable for production agents that require high reliability.

**[Read the Docs](https://scream4ik.github.io/MemState/)** | **[Report an Issue](https://github.com/scream4ik/MemState/issues)**

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
