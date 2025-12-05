# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2025-12-04

### Fixed
- **Critical Atomicity Fix:** The `commit()` method now implements a proper "Compensating Transaction" pattern.
    - Previously, if a vector sync hook (e.g., ChromaDB) failed, the SQL data remained committed, breaking the "ACID-like" promise.
    - Now, if a hook fails, the SQL transaction is automatically rolled back (or restored to the previous state).
- **Singleton Logic:** Fixed a bug where updating a Singleton fact (e.g., "One User Profile") would return early and skip vector synchronization.

### Documentation 📚
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
