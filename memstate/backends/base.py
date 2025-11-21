from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
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
    def get_tx_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve transaction history (newest first typically, or ordered by seq)."""
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> list[str]:
        """Bulk delete ephemeral facts (Working Memory cleanup). Returns deleted IDs."""
        pass
