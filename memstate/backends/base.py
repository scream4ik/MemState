"""
Base storage backend interface.
"""

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Synchronous storage interface (blocking I/O)."""

    @abstractmethod
    def load(self, id: str) -> dict[str, Any] | None:
        """Load a single fact by ID."""
        pass

    @abstractmethod
    def save(self, fact_data: dict[str, Any]) -> None:
        """Upsert a fact."""
        pass

    @abstractmethod
    def delete(self, id: str) -> None:
        """Delete a fact."""
        pass

    @abstractmethod
    def query(self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Find facts matching criteria."""
        pass

    @abstractmethod
    def append_tx(self, tx_data: dict[str, Any]) -> None:
        """Log a transaction."""
        pass

    @abstractmethod
    def get_tx_log(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve transaction history (newest first typically, or ordered by seq)."""
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> list[str]:
        """Bulk delete ephemeral facts (Working Memory cleanup). Returns deleted IDs."""
        pass

    @abstractmethod
    def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all facts belonging to a specific session."""
        pass

    @abstractmethod
    def delete_txs(self, tx_uuids: list[str]) -> None:
        """Delete specific transactions from the log by their UUIDs."""
        pass

    def close(self) -> None:
        """Cleanup resources (optional)."""
        pass


class AsyncStorageBackend(ABC):
    """Asynchronous storage interface (non-blocking I/O)."""

    @abstractmethod
    async def load(self, id: str) -> dict[str, Any] | None:
        """Load a single fact by ID asynchronously."""
        pass

    @abstractmethod
    async def save(self, fact_data: dict[str, Any]) -> None:
        """Upsert a fact asynchronously."""
        pass

    @abstractmethod
    async def delete(self, id: str) -> None:
        """Delete a fact asynchronously."""
        pass

    @abstractmethod
    async def query(
        self, type_filter: str | None = None, json_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Find facts matching criteria asynchronously."""
        pass

    @abstractmethod
    async def append_tx(self, tx_data: dict[str, Any]) -> None:
        """Log a transaction asynchronously."""
        pass

    @abstractmethod
    async def get_tx_log(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve transaction history asynchronously."""
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> list[str]:
        """Bulk delete ephemeral facts asynchronously. Returns deleted IDs."""
        pass

    @abstractmethod
    async def get_session_facts(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all facts belonging to a specific session."""
        pass

    @abstractmethod
    async def delete_txs(self, tx_uuids: list[str]) -> None:
        """Delete specific transactions from the log by their UUIDs."""
        pass

    async def close(self) -> None:
        """Cleanup resources asynchronously."""
        pass
