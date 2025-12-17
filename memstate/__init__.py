import importlib.metadata

try:
    __version__ = importlib.metadata.version("memstate")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"

from memstate.backends.inmemory import AsyncInMemoryStorage, InMemoryStorage
from memstate.backends.sqlite import AsyncSQLiteStorage, SQLiteStorage
from memstate.constants import Operation
from memstate.exceptions import ConflictError, HookError, MemoryStoreError, ValidationFailed
from memstate.schemas import Fact, TxEntry
from memstate.storage import AsyncMemoryStore, Constraint, MemoryStore

__all__ = [
    "MemoryStore",
    "AsyncMemoryStore",
    "Constraint",
    "Fact",
    "TxEntry",
    "Operation",
    "InMemoryStorage",
    "AsyncInMemoryStorage",
    "SQLiteStorage",
    "AsyncSQLiteStorage",
    "MemoryStoreError",
    "ValidationFailed",
    "ConflictError",
    "HookError",
]
