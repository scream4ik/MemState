import importlib.metadata

try:
    __version__ = importlib.metadata.version("memstate")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"

from memstate.backends.inmemory import InMemoryStorage
from memstate.backends.sqlite import SQLiteStorage
from memstate.constants import Operation
from memstate.exceptions import ConflictError, HookError, MemoryStoreError, ValidationFailed
from memstate.schemas import Fact, TxEntry
from memstate.storage import Constraint, MemoryStore

__all__ = [
    "MemoryStore",
    "Constraint",
    "Fact",
    "TxEntry",
    "Operation",
    "InMemoryStorage",
    "SQLiteStorage",
    "MemoryStoreError",
    "ValidationFailed",
    "ConflictError",
    "HookError",
]
