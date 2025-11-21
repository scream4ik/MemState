from enum import Enum


class Operation(str, Enum):
    COMMIT = "COMMIT"
    COMMIT_EPHEMERAL = "COMMIT_EPHEMERAL"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PROMOTE = "PROMOTE"
    DISCARD_SESSION = "DISCARD_SESSION"
