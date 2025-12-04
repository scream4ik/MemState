import json
import sqlite3
import threading
from typing import Any

from memstate.backends.base import StorageBackend


class SQLiteStorage(StorageBackend):
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
        with self._lock:
            c = self._conn.cursor()
            c.execute("PRAGMA journal_mode=WAL;")

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
            self._conn.commit()

    def load(self, id: str) -> dict[str, Any] | None:
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT data FROM facts WHERE id = ?", (id,))
            row = c.fetchone()
            return json.loads(row["data"]) if row else None

    def save(self, fact_data: dict[str, Any]) -> None:
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
        with self._lock:
            c = self._conn.cursor()
            c.execute("DELETE FROM facts WHERE id = ?", (id,))
            self._conn.commit()

    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query = "SELECT data FROM facts WHERE 1=1"
        params = []

        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)

        if json_filters:
            for key, value in json_filters.items():
                query += f" AND json_extract(data, '$.{key}') = ?"
                params.append(value)

        with self._lock:
            c = self._conn.cursor()
            c.execute(query, params)
            return [json.loads(row["data"]) for row in c.fetchall()]

    def append_tx(self, tx: dict[str, Any]) -> None:
        with self._lock:
            c = self._conn.cursor()
            c.execute(
                """
                      INSERT INTO tx_log(uuid, timestamp, data)
                      VALUES (?, ?, ?)
                      """,
                (tx["uuid"], tx["ts"], json.dumps(tx, default=str)),
            )
            self._conn.commit()

    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            c = self._conn.cursor()
            c.execute("SELECT data FROM tx_log ORDER BY tx_id DESC LIMIT ? OFFSET ?", (limit, offset))
            rows = c.fetchall()

            return [json.loads(row["data"]) for row in rows]

    def delete_session(self, session_id: str) -> list[str]:
        with self._lock:
            c = self._conn.cursor()

            c.execute("SELECT id FROM facts WHERE json_extract(data, '$.session_id') = ?", (session_id,))
            rows = c.fetchall()
            ids = [row["id"] for row in rows]

            if ids:
                c.execute("DELETE FROM facts WHERE json_extract(data, '$.session_id') = ?", (session_id,))
                self._conn.commit()

            return ids

    def close(self):
        if self._owns_connection:
            self._conn.close()
