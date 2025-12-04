import threading
from typing import Any

from memstate.backends.base import StorageBackend


class InMemoryStorage(StorageBackend):
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._tx_log: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def _get_value_by_path(self, data: dict[str, Any], path: str) -> Any:
        keys = path.split(".")
        val: Any = data
        try:
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    return None
            return val
        except (AttributeError, TypeError):
            return None

    def load(self, id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._store.get(id)

    def save(self, fact_data: dict[str, Any]) -> None:
        with self._lock:
            self._store[fact_data["id"]] = fact_data

    def delete(self, id: str) -> None:
        with self._lock:
            self._store.pop(id, None)

    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for fact in self._store.values():
                if type_filter and fact["type"] != type_filter:
                    continue
                if json_filters:
                    match = True
                    for k, v in json_filters.items():
                        # The simplest depth-first search payload
                        actual_val = self._get_value_by_path(fact, k)
                        if actual_val != v:
                            match = False
                            break
                    if not match:
                        continue
                results.append(fact)
            return results

    def append_tx(self, tx_data: dict[str, Any]) -> None:
        with self._lock:
            self._tx_log.append(tx_data)

    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._tx_log))[offset : offset + limit]

    def delete_session(self, session_id: str) -> list[str]:
        with self._lock:
            to_delete = [fid for fid, f in self._store.items() if f.get("session_id") == session_id]
            for fid in to_delete:
                del self._store[fid]
            return to_delete
