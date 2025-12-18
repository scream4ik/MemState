class MemoryStoreError(Exception):
    """
    Represents custom exceptions for the MemoryStore system.

    This class is used as a base exception for handling errors specific
    to the MemoryStore logic. It provides a way to differentiate
    exceptions occurring in this domain from generic exceptions.
    """

    pass


class ValidationFailed(MemoryStoreError):
    """
    Represents a specific error related to validation failure.

    This exception class is used to indicate that a certain validation
    process has failed during the operation. It inherits from the
    `MemoryStoreError` class, which represents generic errors related
    to memory store operations.
    """

    pass


class ConflictError(MemoryStoreError):
    """
    Represents an error occurring due to a conflict within the memory store operations.

    This exception is raised when there is a conflict in the memory store, such as
    an attempt to perform an operation that violates constraints or duplications
    within the data. It inherits from MemoryStoreError and provides a more specific
    context for handling errors related to conflicts in storage.
    """

    pass


class HookError(MemoryStoreError):
    """
    Represents a specific type of error that occurs when there is an issue with
    hook operations in the memory store.

    This class is a subclass of MemoryStoreError, and it is used to distinctively
    identify and handle errors related to hooks within the memory operations context.
    """

    pass
