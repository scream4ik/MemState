"""
In-memory storage backend implementation.
"""

import asyncio
import threading
from typing import Any

from memstate.backends.base import AsyncStorageBackend, StorageBackend


class InMemoryStorage(StorageBackend):
    """
    Class representing an in-memory storage backend.

    Provides methods for storing, retrieving, deleting, querying, and managing
    session-related and transaction-log data entirely within memory. This class
    implements thread-safe operations and supports querying with filtering logic
    using hierarchical paths in JSON-like structures.

    Attributes:
        _store (dict[str, dict[str, Any]]): Internal storage for facts indexed by their ID.
        _tx_log (list[dict[str, Any]]): List of transaction log entries.
        _lock (threading.RLock): Reentrant lock for synchronizing access to the storage.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._tx_log: list[dict[str, Any]] = []
        self._lock = threading.RLock()

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
        with self._lock:
            return self._store.get(id)

    def save(self, fact_data: dict[str, Any]) -> None:
        """
        Saves the given fact data into the internal store. The save operation is thread-safe
        and ensures data consistency by utilizing a lock mechanism.

        Args:
            fact_data (dict[str, Any]): A dictionary containing fact data to be stored. The dictionary
                must include an "id" key with a corresponding value as a unique identifier.

        Returns:
            None
        """
        with self._lock:
            self._store[fact_data["id"]] = fact_data

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
            self._store.pop(id, None)

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
        """
        Appends a transaction record to the transaction log in a thread-safe manner.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        with self._lock:
            self._tx_log.append(tx_data)

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
            reversed_log = reversed(self._tx_log)
            filtered = [tx for tx in reversed_log if tx.get("session_id") == session_id]
            return filtered[offset : offset + limit]

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
            to_delete = [fid for fid, f in self._store.items() if f.get("session_id") == session_id]
            for fid in to_delete:
                del self._store[fid]
            return to_delete

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
        return [f for f in self._store.values() if f.get("session_id") == session_id]

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
            ids_to_delete = set(tx_uuids)

            self._tx_log = [tx for tx in self._tx_log if tx["uuid"] not in ids_to_delete]

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
        pass


class AsyncInMemoryStorage(AsyncStorageBackend):
    """
    Class representing an async in-memory storage backend.

    Provides methods for storing, retrieving, deleting, querying, and managing
    session-related and transaction-log data entirely within memory. This class
    implements thread-safe operations and supports querying with filtering logic
    using hierarchical paths in JSON-like structures.

    Attributes:
        _store (dict[str, dict[str, Any]]): Internal storage for facts indexed by their ID.
        _tx_log (list[dict[str, Any]]): List of transaction log entries.
        _lock (asyncio.Lock): Asynchronous lock to ensure safe concurrent access to the storage and transaction log.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._tx_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

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
        async with self._lock:
            return self._store.get(id)

    async def save(self, fact_data: dict[str, Any]) -> None:
        """
        Asynchronously saves the given fact data into the internal store. The save operation is thread-safe
        and ensures data consistency by utilizing a lock mechanism.

        Args:
            fact_data (dict[str, Any]): A dictionary containing fact data to be stored. The dictionary
                must include an "id" key with a corresponding value as a unique identifier.

        Returns:
            None
        """
        async with self._lock:
            self._store[fact_data["id"]] = fact_data

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
            self._store.pop(id, None)

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
        async with self._lock:
            results = []
            for fact in self._store.values():
                if type_filter and fact["type"] != type_filter:
                    continue

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
        Asynchronously appends a transaction record to the transaction log in a thread-safe manner.

        Args:
            tx_data (dict[str, Any]): A dictionary containing transaction data to be appended.

        Returns:
            None
        """
        async with self._lock:
            self._tx_log.append(tx_data)

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
            reversed_log = reversed(self._tx_log)
            filtered = [tx for tx in reversed_log if tx.get("session_id") == session_id]
            return filtered[offset : offset + limit]

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
            to_delete = [fid for fid, f in self._store.items() if f.get("session_id") == session_id]
            for fid in to_delete:
                del self._store[fid]
            return to_delete

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
        return [f for f in self._store.values() if f.get("session_id") == session_id]

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

        async with self._lock:
            ids_to_delete = set(tx_uuids)

            self._tx_log = [tx for tx in self._tx_log if tx["uuid"] not in ids_to_delete]

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
        pass
