import json
from typing import Any

from .base import StorageBackend

try:
    import redis
except ImportError:
    redis = None


class RedisStorage(StorageBackend):
    def __init__(self, redis_url: str) -> None:
        if not redis:
            raise ImportError("redis package is required. pip install redis")
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.prefix = "mem:"

    def _key(self, id: str) -> str:
        return f"{self.prefix}fact:{id}"

    def load(self, id: str) -> dict[str, Any] | None:
        data = self.r.get(self._key(id))
        return json.loads(data) if data else None

    def save(self, fact_data: dict[str, Any]) -> None:
        self.r.set(self._key(fact_data["id"]), json.dumps(fact_data))
        self.r.sadd(f"{self.prefix}type:{fact_data['type']}", fact_data["id"])
        if fact_data.get("session_id"):
            self.r.sadd(f"{self.prefix}session:{fact_data['session_id']}", fact_data["id"])

    def delete(self, id: str) -> None:
        # Need to load first to clear indexes? For speed we might skip,
        # but correctly we should clean up sets.
        # For MVP: just delete key. Indexes might have stale IDs (handled by load check).
        data = self.load(id)
        if data:
            pipe = self.r.pipeline()
            pipe.delete(self._key(id))
            pipe.srem(f"{self.prefix}type:{data['type']}", id)
            if data.get("session_id"):
                pipe.srem(f"{self.prefix}session:{data['session_id']}", id)
            pipe.execute()

    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # Optimization: Use Set Intersections if filters allow, otherwise scan
        # Redis without RediSearch is poor at complex filtering.
        # Strategy: Get IDs from Type Index -> Load -> Filter in Python

        if type_filter:
            ids = self.r.smembers(f"{self.prefix}type:{type_filter}")
        else:
            # Dangerous scan for all keys, acceptable for MVP/Small scale
            keys = self.r.keys(f"{self.prefix}fact:*")
            ids = [k.split(":")[-1] for k in keys]

        results = []
        # Pipeline loading for speed
        if not ids:
            return []

        pipe = self.r.pipeline()
        id_list = list(ids)
        for i in id_list:
            pipe.get(self._key(i))
        raw_docs = pipe.execute()

        for doc_str in raw_docs:
            if not doc_str:
                continue
            fact = json.loads(doc_str)

            # JSON Filter in Python (Backfill for NoSQL)
            if json_filters:
                match = True
                for k, v in json_filters.items():
                    if fact.get("payload", {}).get(k) != v:
                        match = False
                        break
                if not match:
                    continue
            results.append(fact)

        return results

    def append_tx(self, tx_data: dict[str, Any]) -> None:
        self.r.lpush(f"{self.prefix}tx_log", json.dumps(tx_data))

    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        # LPUSH adds to head (index 0). So 0 is newest.
        raw = self.r.lrange(f"{self.prefix}tx_log", offset, offset + limit - 1)
        return [json.loads(x) for x in raw]

    def delete_session(self, session_id: str) -> list[str]:
        # Get IDs from session index
        key = f"{self.prefix}session:{session_id}"
        ids = list(self.r.smembers(key))
        if not ids:
            return []

        pipe = self.r.pipeline()
        for i in ids:
            pipe.delete(self._key(i))
            # Note: cleaning type index is expensive here without reading each fact,
            # acceptable tradeoff for Redis expiration logic later.
        pipe.delete(key)  # clear index
        pipe.execute()
        return ids
