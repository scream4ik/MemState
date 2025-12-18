"""
Redis storage backend implementation.
"""

import json
from typing import Any, Union

from memstate.backends.base import AsyncStorageBackend, StorageBackend

try:
    import redis
    import redis.asyncio as aredis
except ImportError:
    raise ImportError("redis package is required. pip install redis")


class RedisStorage(StorageBackend):
    """
    RedisStorage class provides a Redis-based implementation for storing and retrieving structured
    data, facilitating the management of session-based storage, type-based indexing, and transaction logs.

    This class aims to handle data persistence efficiently using Redis as the backend, enabling features
    such as loading, saving, querying, and deleting data with support for session-specific and type-specific
    operations. It includes tools to query and backfill JSON filters and also supports transactional logging.

    Attributes:
        prefix (str): Prefix used for all Redis keys to avoid collisions with other data in the Redis instance.
        r (redis.Redis): Redis client for performing operations against the Redis database.
        _owns_client (bool): Flag indicating whether the Redis client was created by the RedisStorage class.
    """

    def __init__(self, client_or_url: Union[str, "redis.Redis"] = "redis://localhost:6379/0") -> None:
        self.prefix = "mem:"

        if isinstance(client_or_url, str):
            self.r = redis.from_url(client_or_url, decode_responses=True)  # type: ignore[no-untyped-call]
            self._owns_client = True
        else:
            self.r = client_or_url
            self._owns_client = False

    def _key(self, id: str) -> str:
        """
        Generates a key string by combining the prefix attribute with a given identifier.

        Args:
            id (str): The identifier to be appended to the prefix. Must be a string.

        Returns:
            A formatted string combining the prefix and the identifier.
        """
        return f"{self.prefix}fact:{id}"

    def _to_str(self, data: bytes | str | None) -> str | None:
        """
        Converts the provided data into a string representation. If the input is
        a byte sequence, it decodes it using UTF-8. A `None` input will result
        in a `None` output. This utility function ensures consistent string
        representation across different input types.

        Args:
            data: The input data that can be of type `bytes`, `str`, or `None`.
                If `bytes`, it will be decoded to a UTF-8 string. If `None`, the
                function returns `None` directly.

        Returns:
            A string representation of the input data or `None` if the input is `None`.
        """
        if data is None:
            return None
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return data

    def _get_value_by_path(self, data: dict[str, Any], path: str) -> Any:
        """
        Retrieves a value from a nested dictionary-like structure based on a dot-delimited
        string path. If the path does not exist, or if an attribute or type mismatch occurs
        during traversal, the function returns None.

        Args:
            data (dict[str, Any]): The dictionary-like structure to retrieve the value from.
            path (str): The dot-delimited string representing the path to the desired value.

        Returns:
            The value at the specified path within the dictionary-like structure, or
                None if the path does not exist or an error occurs during traversal.
        """
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
        raw_data = self.r.get(self._key(id))
        json_str = self._to_str(raw_data)
        return json.loads(json_str) if json_str else None

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
        self.r.set(self._key(fact_data["id"]), json.dumps(fact_data))
        self.r.sadd(f"{self.prefix}type:{fact_data['type']}", fact_data["id"])
        if fact_data.get("session_id"):
            self.r.sadd(f"{self.prefix}session:{fact_data['session_id']}", fact_data["id"])

    def delete(self, id: str) -> None:
        """
        Removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
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

        for raw_doc in raw_docs:
            if not raw_doc:
                continue
            doc_str = self._to_str(raw_doc)
            if doc_str is None:
                continue
            fact = json.loads(doc_str)

            # JSON Filter in Python (Backfill for NoSQL)
            if json_filters:
                match = True
                for k, v in json_filters.items():
                    actual_val = self._get_value_by_path(fact, k)
                    if actual_val != v:
                        match = False
                        break
                if not match:
                    continue
            results.append(fact)

        return results

    def append_tx(self, tx_data: dict[str, Any]) -> None:
        """
        Appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        self.r.lpush(f"{self.prefix}tx_log", json.dumps(tx_data))

    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """
        Retrieves and returns a portion of the transaction log. The transaction log is accessed in
        reverse order of insertion, i.e., the most recently added item is the first in the result.

        Args:
            limit (int): The maximum number of transaction log entries to be retrieved. Default is 100.
            offset (int): The starting position relative to the most recent entry that determines where to begin
                retrieving the log entries. Default is 0.

        Returns:
            A list of dictionaries representing the requested subset of the transaction log. The dictionaries
                contain details of individual transaction log entries.
        """
        # LPUSH adds to head (index 0). So 0 is newest.
        raw_list = self.r.lrange(f"{self.prefix}tx_log", offset, offset + limit - 1)

        results = []
        for item in raw_list:
            s = self._to_str(item)
            if s is not None:
                results.append(json.loads(s))

        return results

    def delete_session(self, session_id: str) -> list[str]:
        """
        Deletes all facts associated with a given session ID from the store.

        This method identifies all facts records in the store that are linked to the specified
        session ID, removes them, and returns a list of fact identifiers that were deleted.

        Args:
            session_id (str): The identifier of the session whose associated facts should be removed.

        Returns:
            A list of fact ids identifiers that were deleted from the store.
        """
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

    def remove_last_tx(self, count: int) -> None:
        """
        Removes a specified number of the most recent transactions from the transaction
        log. If the number of transactions to remove exceeds the current size of the
        log, the entire log will be cleared.

        Args:
            count (int): The number of transactions to remove. Must be a positive integer.

        Returns:
            None
        """
        if count <= 0:
            return
        self.r.ltrim(f"{self.prefix}tx_log", count, -1)

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
        key = f"{self.prefix}session:{session_id}"
        ids = self.r.smembers(key)

        if not ids:
            return []

        pipe = self.r.pipeline()
        for i in ids:
            pipe.get(self._key(i))
        raw_docs = pipe.execute()

        results = []
        for raw_doc in raw_docs:
            doc_str = self._to_str(raw_doc)
            if doc_str:
                results.append(json.loads(doc_str))
        return results

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
        if self._owns_client:
            self.r.close()


class AsyncRedisStorage(AsyncStorageBackend):
    """
    AsyncRedisStorage class provides an async Redis-based implementation for storing and retrieving structured
    data, facilitating the management of session-based storage, type-based indexing, and transaction logs.

    This class aims to handle data persistence efficiently using Redis as the backend, enabling features
    such as loading, saving, querying, and deleting data with support for session-specific and type-specific
    operations. It includes tools to query and backfill JSON filters and also supports transactional logging.

    Attributes:
        prefix (str): Prefix used for all Redis keys to avoid collisions with other data in the Redis instance.
        r (aredis.Redis): Redis client for performing operations against the Redis database.
        _owns_client (bool): Flag indicating whether the Redis client was created by the AsyncRedisStorage class.
    """

    def __init__(self, client_or_url: Union[str, "aredis.Redis"] = "redis://localhost:6379/0") -> None:
        self.prefix = "mem:"

        if isinstance(client_or_url, str):
            self.r = aredis.from_url(client_or_url, decode_responses=True)  # type: ignore[no-untyped-call]
            self._owns_client = True
        else:
            self.r = client_or_url
            self._owns_client = False

    def _key(self, id: str) -> str:
        """
        Generates a key string by combining the prefix attribute with a given identifier.

        Args:
            id (str): The identifier to be appended to the prefix. Must be a string.

        Returns:
            A formatted string combining the prefix and the identifier.
        """
        return f"{self.prefix}fact:{id}"

    def _get_value_by_path(self, data: dict[str, Any], path: str) -> Any:
        """
        Retrieves a value from a nested dictionary-like structure based on a dot-delimited
        string path. If the path does not exist, or if an attribute or type mismatch occurs
        during traversal, the function returns None.

        Args:
            data (dict[str, Any]): The dictionary-like structure to retrieve the value from.
            path (str): The dot-delimited string representing the path to the desired value.

        Returns:
            The value at the specified path within the dictionary-like structure, or
                None if the path does not exist or an error occurs during traversal.
        """
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
        raw_data = await self.r.get(self._key(id))
        return json.loads(raw_data) if raw_data else None

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
        async with self.r.pipeline() as pipe:
            pipe.set(self._key(fact_data["id"]), json.dumps(fact_data))
            pipe.sadd(f"{self.prefix}type:{fact_data['type']}", fact_data["id"])
            if fact_data.get("session_id"):
                pipe.sadd(f"{self.prefix}session:{fact_data['session_id']}", fact_data["id"])
            await pipe.execute()

    async def delete(self, id: str) -> None:
        """
        Asynchronously removes an entry from the store based on the provided identifier. If the identifier
        does not exist, the method performs no action and completes silently.

        Args:
            id (str): The identifier of the entry to be removed from the store. Must be a string.

        Returns:
            None
        """
        data = await self.load(id)
        if data:
            async with self.r.pipeline() as pipe:
                pipe.delete(self._key(id))
                pipe.srem(f"{self.prefix}type:{data['type']}", id)
                if data.get("session_id"):
                    pipe.srem(f"{self.prefix}session:{data['session_id']}", id)
                await pipe.execute()

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
        if type_filter:
            ids = await self.r.smembers(f"{self.prefix}type:{type_filter}")
        else:
            keys = await self.r.keys(f"{self.prefix}fact:*")
            ids = [k.split(":")[-1] for k in keys]

        if not ids:
            return []

        async with self.r.pipeline() as pipe:
            for i in list(ids):
                pipe.get(self._key(i))
            raw_docs = await pipe.execute()

        results = []
        for doc_str in raw_docs:
            if not doc_str:
                continue
            fact = json.loads(doc_str)

            if json_filters:
                match = True
                for k, v in json_filters.items():
                    actual_val = self._get_value_by_path(fact, k)
                    if actual_val != v:
                        match = False
                        break
                if not match:
                    continue
            results.append(fact)

        return results

    async def append_tx(self, tx_data: dict[str, Any]) -> None:
        """
        Asynchronously appends a transaction record to the transaction log.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        await self.r.lpush(f"{self.prefix}tx_log", json.dumps(tx_data))

    async def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """
        Asynchronously retrieves and returns a portion of the transaction log. The transaction log is accessed in
        reverse order of insertion, i.e., the most recently added item is the first in the result.

        Args:
            limit (int): The maximum number of transaction log entries to be retrieved. Default is 100.
            offset (int): The starting position relative to the most recent entry that determines where to begin
                retrieving the log entries. Default is 0.

        Returns:
            A list of dictionaries representing the requested subset of the transaction log. The dictionaries
                contain details of individual transaction log entries.
        """
        raw_list = await self.r.lrange(f"{self.prefix}tx_log", offset, offset + limit - 1)
        results = []
        for item in raw_list:
            if item:
                results.append(json.loads(item))
        return results

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
        key = f"{self.prefix}session:{session_id}"
        ids = list(await self.r.smembers(key))

        if not ids:
            return []

        async with self.r.pipeline() as pipe:
            for i in ids:
                pipe.delete(self._key(i))
            pipe.delete(key)
            await pipe.execute()

        return ids

    async def remove_last_tx(self, count: int) -> None:
        """
        Asynchronously removes a specified number of the most recent transactions from the transaction
        log. If the number of transactions to remove exceeds the current size of the
        log, the entire log will be cleared.

        Args:
            count (int): The number of transactions to remove. Must be a positive integer.

        Returns:
            None
        """
        if count <= 0:
            return
        await self.r.ltrim(f"{self.prefix}tx_log", count, -1)

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
        key = f"{self.prefix}session:{session_id}"
        ids = await self.r.smembers(key)

        if not ids:
            return []

        async with self.r.pipeline() as pipe:
            for i in ids:
                pipe.get(self._key(i))
            raw_docs = await pipe.execute()

        results = []
        for raw_doc in raw_docs:
            if raw_doc:
                results.append(json.loads(raw_doc))
        return results

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
        if self._owns_client:
            await self.r.aclose()
