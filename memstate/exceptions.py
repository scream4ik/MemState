class MemoryStoreError(Exception):
    pass


class ValidationFailed(MemoryStoreError):
    pass


class ConflictError(MemoryStoreError):
    pass


class HookError(MemoryStoreError):
    pass
