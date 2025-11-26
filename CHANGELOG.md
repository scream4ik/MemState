# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
