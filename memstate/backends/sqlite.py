"""
SQLite storage backend implementation.
"""

import asyncio
import json
import re
import sqlite3
import threading
from typing import Any

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore[assignment]

from memstate.backends.base import AsyncStorageBackend, StorageBackend


class SQLiteStorage(StorageBackend):
    """
    SQLite-based storage backend for managing structured data and transactional logs.

    This class provides functionality to persistently store, retrieve, and manipulate
    data and transaction logs using an SQLite database. It supports thread-safe
    operations, ensures data integrity, and utilizes SQLite-specific features such
    as WAL mode and JSON querying.

     Attributes:
        _conn (sqlite3.Connection): SQLite database connection object.
        _owns_connection (bool): Specifies whether the SQLiteStorage instance owns the
            connection and is responsible for closing it.
        _lock (threading.RLock): Threading lock that ensures thread-safe access to the database.
    """

    def __init__(self, connection_or_path: str | sqlite3.Connection = "memory.db") -> None:
        self._lock = threading.RLock()
        self._owns_connection = False

        if isinstance(connection_or_path, str):
            self._conn = sqlite3.connect(connection_or_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._owns_connection = True
        elif isinstance(connection_or_path, sqlite3.Connection):
            self._conn = connection_or_path
            self._conn.row_factory = sqlite3.Row
            self._owns_connection = False
        else:
            raise ValueError(f"Invalid connection type: {type(connection_or_path)}")

        self._init_db()

    def _init_db(self) -> None:
        """
        Initializes and sets up the database structure by creating necessary tables and indexes.
        This method ensures the database schema is prepared for storing and querying data, including
        facts and transaction logs. The initialization process is thread-safe.

        Returns:
            None

        Raises:
            sqlite3.Error: If an error occurs during database operations.
        """
        with self._lock:
            c = self._conn.cursor()
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA synchronous=NORMAL;")

            c.execute(
                """
                      CREATE TABLE IF NOT EXISTS facts
                      (
                          id TEXT PRIMARY KEY,
                          type TEXT NOT NULL,
                          data TEXT NOT NULL,
                          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                      )
                      """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(json_extract(data, '$.session_id'))")
            c.execute(
                """
                      CREATE TABLE IF NOT EXISTS tx_log
                      (
                          tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                          uuid TEXT NOT NULL,
                          timestamp TEXT NOT NULL,
                          data TEXT NOT NULL
                      )
                      """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_tx_log_uuid ON tx_log(uuid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tx_log_session ON tx_log(json_extract(data, '$.session_id'))")
            self._conn.commit()

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
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT data FROM facts WHERE id = ?", (id,))
            row = c.fetchone()
            return json.loads(row["data"]) if row else None

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
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                """
                INSERT OR REPLACE INTO facts(id, type, data)
                VALUES (?, ?, ?)
                """,
                (
                    fact_data["id"],
                    fact_data.get("type", "unknown"),
                    json.dumps(fact_data, default=str),
                ),
            )
            self._conn.commit()

    def delete(self, id: str) -> None:
        """
        Removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
        with self._lock:
            c = self._conn.cursor()
            c.execute("DELETE FROM facts WHERE id = ?", (id,))
            self._conn.commit()

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
        query = "SELECT data FROM facts WHERE 1=1"
        params = []

        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)

        if json_filters:
            for key, value in json_filters.items():
                if not re.match(r"^[a-zA-Z0-9_.]+$", key):
                    raise ValueError(f"Invalid characters in filter key: {key}")
                query += f" AND json_extract(data, '$.{key}') = ?"
                params.append(value)

        with self._lock:
            c = self._conn.cursor()
            c.execute(query, params)
            return [json.loads(row["data"]) for row in c.fetchall()]

    def append_tx(self, tx_data: dict[str, Any]) -> None:
        """
        Appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                """
                      INSERT INTO tx_log(uuid, timestamp, data)
                      VALUES (?, ?, ?)
                      """,
                (tx_data["uuid"], tx_data["ts"], json.dumps(tx_data, default=str)),
            )
            self._conn.commit()

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
        with self._lock:
            c = self._conn.cursor()

            c.execute(
                "SELECT data FROM tx_log WHERE json_extract(data, '$.session_id') = ? ORDER BY tx_id DESC LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            )
            rows = c.fetchall()
            return [json.loads(row["data"]) for row in rows]

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
        with self._lock:
            c = self._conn.cursor()

            c.execute("DELETE FROM facts WHERE json_extract(data, '$.session_id') = ? RETURNING id", (session_id,))
            rows = c.fetchall()
            ids = [row["id"] for row in rows]
            self._conn.commit()
            return ids

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
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT data FROM facts WHERE json_extract(data, '$.session_id') = ?", (session_id,))
            return [json.loads(row["data"]) for row in c.fetchall()]

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
        with self._lock:
            c = self._conn.cursor()
            placeholders = ",".join("?" for _ in tx_uuids)
            c.execute(f"DELETE FROM tx_log WHERE uuid IN ({placeholders})", tuple(tx_uuids))  # nosec B608
            self._conn.commit()

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
        if self._owns_connection:
            self._conn.close()


class AsyncSQLiteStorage(AsyncStorageBackend):
    """
    Async SQLite-based storage backend for managing structured data and transactional logs.

    This class provides functionality to persistently store, retrieve, and manipulate
    data and transaction logs using an SQLite database. It supports thread-safe
    operations, ensures data integrity, and utilizes SQLite-specific features such
    as WAL mode and JSON querying.

    Example:
        ```python
        storage = AsyncSQLiteStorage("agent_async.db")
        await storage.connect()
        ```

     Attributes:
        _conn (str | aiosqlite.Connection): SQLite database connection object.
        _owns_connection (bool): Specifies whether the SQLiteStorage instance owns the
            connection and is responsible for closing it.
        _lock (asyncio.Lock): Threading lock that ensures thread-safe access to the database.
        _db (aiosqlite.Connection): Async SQLite connection object.
        _path (str | None): Path to the SQLite database file.
    """

    def __init__(self, connection_or_path: str | aiosqlite.Connection = "memory.db") -> None:
        if aiosqlite is None:
            raise ImportError("Run `pip install aiosqlite` to use AsyncSQLiteStorage.")

        self._lock = asyncio.Lock()
        self._owns_connection = False
        self._db: Any = None
        self._path: str | None = None

        if isinstance(connection_or_path, str):
            self._path = connection_or_path
            self._owns_connection = True
        else:
            self._db = connection_or_path
            self._owns_connection = False

    async def connect(self) -> None:
        """
        Async initialization. Must be called before use.

        Returns:
            None
        """
        if self._owns_connection and self._path:
            self._db = await aiosqlite.connect(self._path)

        if self._db is None:
            raise ValueError("Connection not initialized properly.")

        self._db.row_factory = aiosqlite.Row
        await self._init_db()

    async def _init_db(self) -> None:
        """
        Initializes the database by setting pragma settings, creating necessary tables,
        and setting up indexes. This method ensures that the database is in the correct
        state for future operations.

        Returns:
            None
        """
        async with self._lock:
            await self._db.execute("PRAGMA journal_mode=WAL;")
            await self._db.execute("PRAGMA synchronous=NORMAL;")

            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS facts
                (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await self._db.execute("CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(type)")
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(json_extract(data, '$.session_id'))"
            )

            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS tx_log
                (
                    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL
                )
                """
            )
            await self._db.execute("CREATE INDEX IF NOT EXISTS idx_tx_log_uuid ON tx_log(uuid)")
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tx_log_session ON tx_log(json_extract(data, '$.session_id'))"
            )
            await self._db.commit()

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
        async with self._lock:
            async with self._db.execute("SELECT data FROM facts WHERE id = ?", (id,)) as cursor:
                row = await cursor.fetchone()
                return json.loads(row["data"]) if row else None

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
        async with self._lock:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO facts(id, type, data)
                VALUES (?, ?, ?)
                """,
                (
                    fact_data["id"],
                    fact_data.get("type", "unknown"),
                    json.dumps(fact_data, default=str),
                ),
            )
            await self._db.commit()

    async def delete(self, id: str) -> None:
        """
        Asynchronously removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
        async with self._lock:
            await self._db.execute("DELETE FROM facts WHERE id = ?", (id,))
            await self._db.commit()

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
        query = "SELECT data FROM facts WHERE 1=1"
        params = []

        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)

        if json_filters:
            for key, value in json_filters.items():
                if not re.match(r"^[a-zA-Z0-9_.]+$", key):
                    raise ValueError(f"Invalid characters in filter key: {key}")
                query += f" AND json_extract(data, '$.{key}') = ?"
                params.append(value)

        async with self._lock:
            async with self._db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                return [json.loads(row["data"]) for row in rows]

    async def append_tx(self, tx_data: dict[str, Any]) -> None:
        """
        Asynchronously appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        async with self._lock:
            await self._db.execute(
                """
                INSERT INTO tx_log(uuid, timestamp, data)
                VALUES (?, ?, ?)
                """,
                (tx_data["uuid"], tx_data["ts"], json.dumps(tx_data, default=str)),
            )
            await self._db.commit()

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
        async with self._lock:
            cursor = await self._db.execute(
                "SELECT data FROM tx_log WHERE json_extract(data, '$.session_id') = ? ORDER BY tx_id DESC LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            )

            rows = await cursor.fetchall()
            return [json.loads(row["data"]) for row in rows]

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
        async with self._lock:
            cursor = await self._db.execute(
                "DELETE FROM facts WHERE json_extract(data, '$.session_id') = ? RETURNING id", (session_id,)
            )
            rows = await cursor.fetchall()
            ids = [row["id"] for row in rows]
            await self._db.commit()
            return ids

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
        async with self._lock:
            async with self._db.execute(
                "SELECT data FROM facts WHERE json_extract(data, '$.session_id') = ?", (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [json.loads(row["data"]) for row in rows]

    async def delete_txs(self, tx_uuids: list[str]) -> None:
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
        async with self._lock:
            placeholders = ",".join("?" for _ in tx_uuids)
            await self._db.execute(f"DELETE FROM tx_log WHERE uuid IN ({placeholders})", tuple(tx_uuids))  # nosec B608
            await self._db.commit()

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
        if self._db:
            await self._db.close()
