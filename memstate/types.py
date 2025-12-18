from typing import Protocol

from memstate.schemas import Fact, Operation


class MemoryHook(Protocol):
    """
    Defines the MemoryHook protocol, which provides a callable interface
    for operations involving facts and identifiers.

    This protocol is intended for usage in scenarios where operations
    must be performed with specific facts and their associated identifiers.
    It ensures that any implementing object adheres to the defined call signature.
    """

    def __init__(self, *args, **kwargs) -> None: ...

    def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        ...


class AsyncMemoryHook(Protocol):
    """
    Defines the AsyncMemoryHook protocol, which provides a callable interface
    for operations involving facts and identifiers.

    This protocol is intended for usage in scenarios where operations
    must be performed with specific facts and their associated identifiers.
    It ensures that any implementing object adheres to the defined call signature.
    """

    async def __call__(self, op: Operation, fact_id: str, fact: Fact | None) -> None:
        """
        Asynchronously executes the instance as a callable. The method processes an operation with an
        associated fact ID and optional fact data.

        Args:
            op (Operation): Operation to be processed.
            fact_id (str): Identifier associated with the fact.
            fact (Fact | None): Optional fact data related to the operation.

        Returns:
            None
        """
        ...
