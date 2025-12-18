from enum import Enum


class Operation(str, Enum):
    """
    Represents different types of operations that can be performed.

    This enumeration is used to define various constants that represent specific
    operations. It can be utilized in different parts of the system where these
    operations are relevant.
    """

    COMMIT = "COMMIT"
    COMMIT_EPHEMERAL = "COMMIT_EPHEMERAL"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    PROMOTE = "PROMOTE"
    DISCARD_SESSION = "DISCARD_SESSION"
