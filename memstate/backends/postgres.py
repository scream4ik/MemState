from typing import Any

try:
    from sqlalchemy import (
        Column,
        ColumnElement,
        Integer,
        MetaData,
        String,
        Table,
        create_engine,
        delete,
        desc,
        func,
        select,
    )
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
except ImportError:
    raise ImportError("Run `pip install postgres[binary]` to use Postgres backend.")

from memstate.backends.base import AsyncStorageBackend, StorageBackend


class PostgresStorage(StorageBackend):
    def __init__(self, engine_or_url: str | Engine, table_prefix: str = "memstate") -> None:
        if isinstance(engine_or_url, str):
            self._engine = create_engine(engine_or_url, future=True)
        else:
            self._engine = engine_or_url

        self._metadata = MetaData()
        self._table_prefix = table_prefix

        # --- Define Tables ---
        self._facts_table = Table(
            f"{table_prefix}_facts",
            self._metadata,
            Column("id", String, primary_key=True),
            Column("doc", JSONB, nullable=False),  # Используем JSONB для индексации
        )

        self._log_table = Table(
            f"{table_prefix}_log",
            self._metadata,
            Column("seq", Integer, primary_key=True, autoincrement=True),
            Column("entry", JSONB, nullable=False),
        )

        with self._engine.begin() as conn:
            self._metadata.create_all(conn)

    def load(self, id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            stmt = select(self._facts_table.c.doc).where(self._facts_table.c.id == id)
            row = conn.execute(stmt).first()
            if row:
                return row[0]  # SQLAlchemy deserializes JSONB automatically
            return None

    def save(self, fact_data: dict[str, Any]) -> None:
        # Postgres Native Upsert (INSERT ... ON CONFLICT DO UPDATE)
        stmt = pg_insert(self._facts_table).values(id=fact_data["id"], doc=fact_data)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["id"], set_={"doc": stmt.excluded.doc}  # Conflict over PK
        )

        with self._engine.begin() as conn:
            conn.execute(upsert_stmt)

    def delete(self, id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(self._facts_table).where(self._facts_table.c.id == id))

    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:

        stmt = select(self._facts_table.c.doc)

        # 1. Filter by type (fact)
        if type_filter:
            # Postgres JSONB access: doc->>'type'
            stmt = stmt.where(self._facts_table.c.doc["type"].astext == type_filter)

        # 2. JSON filters (the hardest part)
        # We expect keys of type "payload.user.id"
        if json_filters:
            for key, value in json_filters.items():
                # Split the path: payload.role -> ['payload', 'role']
                path_parts = key.split(".")

                # Building a JSONB access chain
                json_col: ColumnElement[Any] = self._facts_table.c.doc

                # Go deeper to the last key
                for part in path_parts[:-1]:
                    json_col = json_col[part]

                # Compare the last key
                # Important: cast value to JSONB so that types (int/bool/str) work
                # Or use the @> (contains) operator for reliability

                # Simple option (SQLAlchemy automatically casts types when comparing JSONB)
                stmt = stmt.where(json_col[path_parts[-1]] == func.to_jsonb(value))

        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
            return [r[0] for r in rows]

    def append_tx(self, tx_data: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._log_table.insert().values(entry=tx_data))

    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        stmt = select(self._log_table.c.entry).order_by(desc(self._log_table.c.seq)).limit(limit).offset(offset)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
            return [r[0] for r in rows]

    def delete_session(self, session_id: str) -> list[str]:
        del_stmt = (
            delete(self._facts_table)
            .where(self._facts_table.c.doc["session_id"].astext == session_id)
            .returning(self._facts_table.c.id)
        )

        with self._engine.begin() as conn:
            result = conn.execute(del_stmt)
            return [r[0] for r in result.all()]

    def remove_last_tx(self, count: int) -> None:
        if count <= 0:
            return

        subquery = select(self._log_table.c.seq).order_by(desc(self._log_table.c.seq)).limit(count).scalar_subquery()

        stmt = delete(self._log_table).where(self._log_table.c.seq.in_(subquery))

        with self._engine.begin() as conn:
            conn.execute(stmt)

    def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        stmt = select(self._facts_table.c.doc).where(self._facts_table.c.doc["session_id"].astext == session_id)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
            return [r[0] for r in rows]

    def close(self) -> None:
        self._engine.dispose()


class AsyncPostgresStorage(AsyncStorageBackend):
    """
    store = AsyncPostgresStorage(...)
    await store.create_tables()
    """

    def __init__(self, engine_or_url: str | AsyncEngine, table_prefix: str = "memstate") -> None:
        if isinstance(engine_or_url, str):
            self._engine = create_async_engine(engine_or_url, future=True)
        else:
            self._engine = engine_or_url

        self._metadata = MetaData()
        self._table_prefix = table_prefix

        self._facts_table = Table(
            f"{table_prefix}_facts",
            self._metadata,
            Column("id", String, primary_key=True),
            Column("doc", JSONB, nullable=False),
        )

        self._log_table = Table(
            f"{table_prefix}_log",
            self._metadata,
            Column("seq", Integer, primary_key=True, autoincrement=True),
            Column("entry", JSONB, nullable=False),
        )

    async def create_tables(self) -> None:
        """Helper to create tables asynchronously (uses run_sync)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)

    async def load(self, id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            stmt = select(self._facts_table.c.doc).where(self._facts_table.c.id == id)
            result = await conn.execute(stmt)
            row = result.first()
            if row:
                return row[0]
            return None

    async def save(self, fact_data: dict[str, Any]) -> None:
        stmt = pg_insert(self._facts_table).values(id=fact_data["id"], doc=fact_data)
        upsert_stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"doc": stmt.excluded.doc})
        async with self._engine.begin() as conn:
            await conn.execute(upsert_stmt)

    async def delete(self, id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(self._facts_table).where(self._facts_table.c.id == id))

    async def query(
        self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(self._facts_table.c.doc)

        if type_filter:
            stmt = stmt.where(self._facts_table.c.doc["type"].astext == type_filter)

        if json_filters:
            for key, value in json_filters.items():
                path_parts = key.split(".")
                json_col: Any = self._facts_table.c.doc
                for part in path_parts[:-1]:
                    json_col = json_col[part]
                stmt = stmt.where(json_col[path_parts[-1]] == func.to_jsonb(value))

        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result.all()]

    async def append_tx(self, tx_data: dict[str, Any]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(self._log_table.insert().values(entry=tx_data))

    async def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        stmt = select(self._log_table.c.entry).order_by(desc(self._log_table.c.seq)).limit(limit).offset(offset)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result.all()]

    async def delete_session(self, session_id: str) -> list[str]:
        del_stmt = (
            delete(self._facts_table)
            .where(self._facts_table.c.doc["session_id"].astext == session_id)
            .returning(self._facts_table.c.id)
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(del_stmt)
            return [r[0] for r in result.all()]

    async def remove_last_tx(self, count: int) -> None:
        if count <= 0:
            return

        subquery = select(self._log_table.c.seq).order_by(desc(self._log_table.c.seq)).limit(count).scalar_subquery()

        stmt = delete(self._log_table).where(self._log_table.c.seq.in_(subquery))

        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        stmt = select(self._facts_table.c.doc).where(self._facts_table.c.doc["session_id"].astext == session_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result.all()]

    async def close(self) -> None:
        await self._engine.dispose()
