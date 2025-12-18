# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2025-12-18

### Major: Async Support & Beta Release
This release marks the transition to **Beta**. The API is stable, and MemState is now ready for high-concurrency production workloads (FastAPI).

*   **Full Async Support:** Added `AsyncMemoryStore` and async versions of all backends and hooks.
*   **New Storage Backends:**
    *   **PostgreSQL:** Native support using `SQLAlchemy` + `psycopg` with efficient JSONB querying.
    *   **Redis:** Added `AsyncRedisStorage`.
    *   **SQLite:** Added `AsyncSQLiteStorage` (via `aiosqlite`).
*   **New Vector Integration:** Added **Qdrant** support (Sync & Async) with built-in FastEmbed generation.

### Changed (Architectural Improvements)
*   **Surgical Rollback:** Completely rewrote `rollback` logic to be safe in multi-user environments.
    *   Added `session_id` isolation to transaction logs.
    *   Rollback now removes specific transactions by UUID instead of truncating the log tail, preventing "Groundhog Day" bugs.
*   **Safe Updates:** The `update()` method now enforces **Schema Re-validation**. Applying a patch that breaks the Pydantic schema will now raise `ValidationFailed` instead of corrupting the DB.
*   **Session Optimization:** Added `get_session_facts` to backends to utilize DB indexes for session operations (O(1) vs O(N) previously).

### Added
*   **LangGraph Async:** Added `AsyncMemStateCheckpointer` for non-blocking graph persistence.
*   **DX Improvements:** Added `session_id` argument to `query()` for easier context filtering.
*   **Documentation:** Launched comprehensive documentation site.

### Dependencies
*   Added optional dependencies: `postgres`, `qdrant`, `sqlite-async`.

## [0.3.3] - 2025-12-12

### Added
- **New `commit_model` API:** You can now pass Pydantic instances directly to memory.
  - No more manual dictionary dumping: `mem.commit_model(user)` instead of `mem.commit(Fact(type="user", payload=user.dict()))`.
  - Automatically resolves registered schema types.
  - Supports both INSERT (auto ID) and UPDATE (explicit `fact_id`).

### Documentation
- **README Overhaul:** rewritten to focus on the "Mental Model" of transactional memory and the physical physics of "Data Drift".
- **Refactored Examples:** All examples (`examples/`) updated to use the cleaner `commit_model` syntax.

### Fixed
- **Lifecycle Logic:** Ensured `commit_model` correctly handles updates when `fact_id` is provided (previously defaulted to creating duplicates).

## [0.3.2] - 2025-12-04

### Fixed
- **Critical Atomicity Fix:** The `commit()` method now implements a proper "Compensating Transaction" pattern.
    - Previously, if a vector sync hook (e.g., ChromaDB) failed, the SQL data remained committed, breaking the "ACID-like" promise.
    - Now, if a hook fails, the SQL transaction is automatically rolled back (or restored to the previous state).
- **Singleton Logic:** Fixed a bug where updating a Singleton fact (e.g., "One User Profile") would return early and skip vector synchronization.

### Documentation
- **New Positioning:** Updated README to focus on "Transactional Memory" and "Predictability" rather than generic agent state.
- **Demo:** Added a video demonstration (GIF) showing MemState preventing hallucinations vs Manual Sync.

## [0.3.1] - 2025-12-04

### Changed
- **DX Improvement:** Exposed main classes (`MemoryStore`, `Fact`, `Operation`, etc.) directly in the top-level package.
  - Now you can use: `from memstate import MemoryStore` instead of importing from submodules.
- **Internal:** Switched to dynamic versioning (single source of truth in `pyproject.toml`).

## [0.3.0] - 2025-12-03

### Added
- **RAG Synchronization:** Introduced `ChromaSyncHook` to keep structured state and Vector DBs in perfect sync.
- **Transactional Vector Ops:** Vector embeddings are now atomic — they are only updated/deleted upon `COMMIT`, preventing "ghost data" from draft sessions.
- **Flexible Mapping:** Added support for custom `text_formatter` and `metadata_formatter` to control how Pydantic models map to vector documents.
- New installation extras: `pip install memstate[chromadb]`.

### Changed
- **Positioning:** Rebranded documentation to focus on **ACID-like atomicity** for hybrid memory (SQL + Vector), moving away from the generic "Git for memory" messaging.

## [0.2.0] - 2025-11-26

### Added
- **LangGraph Integration:** Added `MemStateCheckpointer` for persisting agent graphs.
- New installation extras: `pip install memstate[langchain]` (includes `langgraph`).

## [0.1.0] - 2025-11-25

### Added
- Initial release of **MemState**.
- Core transactional memory engine (`MemoryStore`).
- Strict schema validation using Pydantic (`register_schema`).
- Backends: `InMemoryStorage`, `RedisStorage`, `SQLiteStorage` (with JSON1 query support).
- Feature: Time Travel / Rollback (`memory.rollback`).
- Feature: Constraints (`Singleton`, `Immutable`).
