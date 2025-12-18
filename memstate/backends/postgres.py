"""
Postgres storage backend implementation using SQLAlchemy.
"""

from typing import Any

try:
    from sqlalchemy import (
        Column,
        ColumnElement,
        Index,
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
    """
    Storage backend implementation using PostgreSQL and SQLAlchemy.

    This class provides methods for interacting with a PostgreSQL database to store, retrieve,
    and manage structured data and logs. It uses SQLAlchemy for ORM capabilities and supports
    advanced querying and filtering using JSONB.

    Attributes:
        _engine (str | Engine): SQLAlchemy Engine or connection URL for interacting with the PostgreSQL database.
        _metadata (MetaData): SQLAlchemy MetaData object for defining table schemas.
        _table_prefix (str): Prefix for naming tables to avoid conflicts.
        _facts_table (Table): SQLAlchemy Table for storing facts data with JSONB indexing.
        _log_table (Table): SQLAlchemy Table for transaction logs.
    """

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
            Column("session_id", String, index=True, nullable=True),
            Column("entry", JSONB, nullable=False),
            Index(f"ix_{table_prefix}_log_entry_gin", "entry", postgresql_using="gin"),
        )
        Index(f"ix_{table_prefix}_log_uuid", self._log_table.c.entry["uuid"].astext, postgresql_using="btree"),

        with self._engine.begin() as conn:
            self._metadata.create_all(conn)

    def load(self, id: str) -> dict[str, Any] | None:
        """
        Loads an item from the store based on the provided identifier.

        This method retrieves the item associated with the given `id`
        from the internal store. If no item is found for the provided
        identifier, it returns ``None``.

        Args:
            id (str): The unique identifier of the item to load.

        Returns:
            The item retrieved from the store or ``None`` if the identifier does not exist in the store.
        """
        with self._engine.connect() as conn:
            stmt = select(self._facts_table.c.doc).where(self._facts_table.c.id == id)
            row = conn.execute(stmt).first()
            if row:
                return row[0]  # SQLAlchemy deserializes JSONB automatically
            return None

    def save(self, fact_data: dict[str, Any]) -> None:
        """
        Saves the given fact data into the internal store. The save operation
        and ensures data consistency by utilizing a lock mechanism.

        Args:
            fact_data (dict[str, Any]): A dictionary containing fact data to be stored. The dictionary
                must include an "id" key with a corresponding value as a unique identifier.

        Returns:
            None
        """
        # Postgres Native Upsert (INSERT ... ON CONFLICT DO UPDATE)
        stmt = pg_insert(self._facts_table).values(id=fact_data["id"], doc=fact_data)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["id"], set_={"doc": stmt.excluded.doc}  # Conflict over PK
        )

        with self._engine.begin() as conn:
            conn.execute(upsert_stmt)

    def delete(self, id: str) -> None:
        """
        Removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
        with self._engine.begin() as conn:
            conn.execute(delete(self._facts_table).where(self._facts_table.c.id == id))

    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Query data from the internal store based on specified filters.

        This method iterates through the internal store and filters the data based on
        the provided `type_filter` and `json_filters`. The results will include
        only the entries that match all specified filtering criteria.

        Args:
            type_filter (str | None): Optional filter to include only items with a matching "type" field.
                If None, this filter is ignored.
            json_filters (dict[str, Any] | None): A dictionary where keys represent the path within the JSON
                data structure, and values represent the required values for inclusion.
                If None, this filter is ignored.

        Returns:
            A list of dictionaries containing the data entries from the internal store that match the specified filters.
        """
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
        """
        Appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        session_id = tx_data.get("session_id")

        with self._engine.begin() as conn:
            conn.execute(self._log_table.insert().values(session_id=session_id, entry=tx_data))

    def get_tx_log(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """
        Retrieves and returns a portion of the transaction log. The transaction log is accessed in
        reverse order of insertion, i.e., the most recently added item is the first in the result.

        Args:
            session_id (str): The identifier of the session whose transactions should be retrieved.
            limit (int): The maximum number of transaction log entries to be retrieved. Default is 100.
            offset (int): The starting position relative to the most recent entry that determines where to begin
                retrieving the log entries. Default is 0.

        Returns:
            A list of dictionaries representing the requested subset of the transaction log. The dictionaries
                contain details of individual transaction log entries.
        """
        stmt = (
            select(self._log_table.c.entry)
            .where(self._log_table.c.session_id == session_id)
            .order_by(desc(self._log_table.c.seq))
            .limit(limit)
            .offset(offset)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
            return [r[0] for r in rows]

    def delete_session(self, session_id: str) -> list[str]:
        """
        Deletes all facts associated with a given session ID from the store.

        This method identifies all fact records in the store that are linked to the specified
        session ID, removes them, and returns a list of fact identifiers that were deleted.

        Args:
            session_id (str): The identifier of the session whose associated facts should be removed.

        Returns:
            A list of fact ids identifiers that were deleted from the store.
        """
        del_stmt = (
            delete(self._facts_table)
            .where(self._facts_table.c.doc["session_id"].astext == session_id)
            .returning(self._facts_table.c.id)
        )

        with self._engine.begin() as conn:
            result = conn.execute(del_stmt)
            return [r[0] for r in result.all()]

    def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        """
        Retrieves all facts associated with a specific session.

        This method filters and returns a list of all facts from the internal store
        that match the provided session ID. Each fact is represented as a dictionary,
        and the list may be empty if no facts match the provided session ID.

        Args:
            session_id (str): The identifier of the session whose facts are to be retrieved.

        Returns:
            A list of dictionaries, where each dictionary represents a fact related to the specified session.
        """
        stmt = select(self._facts_table.c.doc).where(self._facts_table.c.doc["session_id"].astext == session_id)
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
            return [r[0] for r in rows]

    def delete_txs(self, tx_uuids: list[str]) -> None:
        """
        Removes a list of transactions from the transaction log whose session IDs match the provided
        transaction IDs. If the provided list is empty, no transactions are processed.

        Args:
            tx_uuids (list[str]): A list of transaction UUIDs to be removed from the log.

        Returns:
            None
        """
        if not tx_uuids:
            return

        stmt = delete(self._log_table).where(self._log_table.c.entry["uuid"].astext.in_(tx_uuids))

        with self._engine.begin() as conn:
            conn.execute(stmt)

    def close(self) -> None:
        """
        Closes the current open resource or connection.

        This method is responsible for cleanup or finalization tasks.
        It ensures that resources, such as file handles or network connections,
        are properly released or closed. Once called, the resource cannot
        be used again unless it is reopened.

        Returns:
            None
        """
        self._engine.dispose()


class AsyncPostgresStorage(AsyncStorageBackend):
    """
    Async storage backend implementation using PostgreSQL and SQLAlchemy.

    This class provides methods for interacting with a PostgreSQL database to store, retrieve,
    and manage structured data and logs. It uses SQLAlchemy for ORM capabilities and supports
    advanced querying and filtering using JSONB.

    Example:
        ```python
        store = AsyncPostgresStorage(...)
        await store.create_tables()
        ```

    Attributes
        _engine (str | Engine): SQLAlchemy Engine or connection URL for interacting with the PostgreSQL database.
        _metadata (MetaData): SQLAlchemy MetaData object for defining table schemas.
        _table_prefix (str): Prefix for naming tables to avoid conflicts.
        _facts_table (Table): SQLAlchemy Table for storing facts data with JSONB indexing.
        _log_table (Table): SQLAlchemy Table for transaction logs.
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
            Column("session_id", String, index=True, nullable=True),
            Column("entry", JSONB, nullable=False),
            Index(f"ix_{table_prefix}_log_entry_gin", "entry", postgresql_using="gin"),
        )
        Index(f"ix_{table_prefix}_log_uuid", self._log_table.c.entry["uuid"].astext, postgresql_using="btree"),

    async def create_tables(self) -> None:
        """
        Helper to create tables asynchronously (uses run_sync).

        Returns:
            None
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)

    async def load(self, id: str) -> dict[str, Any] | None:
        """
        Asynchronously loads an item from the store based on the provided identifier.

        This method retrieves the item associated with the given `id`
        from the internal store. If no item is found for the provided
        identifier, it returns ``None``.

        Args:
            id (str): The unique identifier of the item to load.

        Returns:
            The item retrieved from the store or ``None`` if the identifier does not exist in the store.
        """
        async with self._engine.connect() as conn:
            stmt = select(self._facts_table.c.doc).where(self._facts_table.c.id == id)
            result = await conn.execute(stmt)
            row = result.first()
            if row:
                return row[0]
            return None

    async def save(self, fact_data: dict[str, Any]) -> None:
        """
        Asynchronously saves the given fact data into the internal store. The save operation
        and ensures data consistency by utilizing a lock mechanism.

        Args:
            fact_data (dict[str, Any]): A dictionary containing fact data to be stored. The dictionary
                must include an "id" key with a corresponding value as a unique identifier.

        Returns:
            None
        """
        stmt = pg_insert(self._facts_table).values(id=fact_data["id"], doc=fact_data)
        upsert_stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"doc": stmt.excluded.doc})
        async with self._engine.begin() as conn:
            await conn.execute(upsert_stmt)

    async def delete(self, id: str) -> None:
        """
        Asynchronously removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
        async with self._engine.begin() as conn:
            await conn.execute(delete(self._facts_table).where(self._facts_table.c.id == id))

    async def query(
        self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Asynchronously query data from the internal store based on specified filters.

        This method iterates through the internal store and filters the data based on
        the provided `type_filter` and `json_filters`. The results will include
        only the entries that match all specified filtering criteria.

        Args:
            type_filter (str | None): Optional filter to include only items with a matching "type" field.
                If None, this filter is ignored.
            json_filters (dict[str, Any] | None): A dictionary where keys represent the path within the JSON
                data structure, and values represent the required values for inclusion.
                If None, this filter is ignored.

        Returns:
            A list of dictionaries containing the data entries from the internal store that match the specified filters.
        """
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
        """
        Asynchronously appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        session_id = tx_data.get("session_id")

        async with self._engine.begin() as conn:
            await conn.execute(self._log_table.insert().values(session_id=session_id, entry=tx_data))

    async def get_tx_log(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """
        Asynchronously retrieves and returns a portion of the transaction log. The transaction log is accessed in
        reverse order of insertion, i.e., the most recently added item is the first in the result.

        Args:
            session_id (str): The identifier of the session whose transactions should be retrieved.
            limit (int): The maximum number of transaction log entries to be retrieved. Default is 100.
            offset (int): The starting position relative to the most recent entry that determines where to begin
                retrieving the log entries. Default is 0.

        Returns:
            A list of dictionaries representing the requested subset of the transaction log. The dictionaries
                contain details of individual transaction log entries.
        """
        stmt = (
            select(self._log_table.c.entry)
            .where(self._log_table.c.session_id == session_id)
            .order_by(desc(self._log_table.c.seq))
            .limit(limit)
            .offset(offset)
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result.all()]

    async def delete_session(self, session_id: str) -> list[str]:
        """
        Asynchronously deletes all facts associated with a given session ID from the store.

        This method identifies all fact records in the store that are linked to the specified
        session ID, removes them, and returns a list of fact identifiers that were deleted.

        Args:
            session_id (str): The identifier of the session whose associated facts should be removed.

        Returns:
            A list of fact ids identifiers that were deleted from the store.
        """
        del_stmt = (
            delete(self._facts_table)
            .where(self._facts_table.c.doc["session_id"].astext == session_id)
            .returning(self._facts_table.c.id)
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(del_stmt)
            return [r[0] for r in result.all()]

    async def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        """
        Asynchronously retrieves all facts associated with a specific session.

        This method filters and returns a list of all facts from the internal store
        that match the provided session ID. Each fact is represented as a dictionary,
        and the list may be empty if no facts match the provided session ID.

        Args:
            session_id (str): The identifier of the session whose facts are to be retrieved.

        Returns:
            A list of dictionaries, where each dictionary represents a fact related to the specified session.
        """
        stmt = select(self._facts_table.c.doc).where(self._facts_table.c.doc["session_id"].astext == session_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return [r[0] for r in result.all()]

    async def delete_txs(self, tx_uuids: list[str]) -> None:
        """
        Asynchronously removes a list of transactions from the transaction log whose session IDs match the provided
        transaction IDs. If the provided list is empty, no transactions are processed.

        Args:
            tx_uuids (list[str]): A list of transaction UUIDs to be removed from the log.

        Returns:
            None
        """
        if not tx_uuids:
            return

        stmt = delete(self._log_table).where(self._log_table.c.entry["uuid"].astext.in_(tx_uuids))

        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def close(self) -> None:
        """
        Asynchronously closes the current open resource or connection.

        This method is responsible for cleanup or finalization tasks.
        It ensures that resources, such as file handles or network connections,
        are properly released or closed. Once called, the resource cannot
        be used again unless it is reopened.

        Returns:
            None
        """
        await self._engine.dispose()
