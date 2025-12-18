"""
LangGraph Checkpointer.
"""

from typing import Any, AsyncIterator, Iterator, Sequence

try:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import (
        BaseCheckpointSaver,
        Checkpoint,
        CheckpointMetadata,
        CheckpointTuple,
        SerializerProtocol,
    )
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
except ImportError:
    raise ImportError("pip install langgraph")

from memstate.schemas import Fact
from memstate.storage import AsyncMemoryStore, MemoryStore


class MemStateCheckpointer(BaseCheckpointSaver[str]):
    """
    Manages the storage, retrieval, and deletion of checkpoint data in memory.

    The MemStateCheckpointer class enables storing checkpoints using an in-memory
    storage system, facilitating workflows that require checkpointing and versioning
    mechanisms. It interacts with a memory store to persist checkpoint data and
    associated metadata, supporting use cases that require checkpointer objects
    functioning as temporary memory storage.

    Attributes:
        memory (MemoryStore): Reference to the memory store used for storage operations.
        serde (SerializerProtocol): Serializer for serializing checkpoint data.
        fact_type (str): String identifier for checkpoint facts within the memory store.
        write_type (str): String identifier for write facts within the memory store.
    """

    def __init__(self, memory: MemoryStore, serde: SerializerProtocol | None = None) -> None:
        super().__init__(serde=serde or JsonPlusSerializer())
        self.memory = memory
        self.fact_type = "langgraph_checkpoint"
        self.write_type = "langgraph_write"

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        """
        Updates the state of a process by committing checkpoint metadata into memory
        and returning an updated configuration object.

        This method handles storing the provided checkpoint and its associated metadata
        to facilitate process tracking. It interacts with the memory instance to ensure
        the relevant details are committed within the appropriate session. After updating
        memory, it returns a modified configuration containing the updated thread
        parameters.

        Args:
            config (RunnableConfig): The configuration object for the runnable, which must include a `thread_id` under the `configurable` key.
            checkpoint (Checkpoint): The checkpoint object containing state information to be stored in memory.
            metadata (CheckpointMetadata): Additional metadata corresponding to the checkpoint, providing
                supplementary details about the stored state.
            new_versions (dict[str, Any]): A mapping of version keys to their new corresponding
                values, used to track changes in versions during the execution process.

        Returns:
            A modified configuration object reflecting the updated thread
                parameters after committing the provided checkpoint to memory.
        """
        thread_id = config["configurable"]["thread_id"]

        payload = {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "new_versions": new_versions,
            "thread_ts": checkpoint["id"],
        }

        self.memory.commit(
            Fact(type=self.fact_type, payload=payload, source="langgraph_checkpoint"), session_id=thread_id
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "thread_ts": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Executes the operation to store a sequence of writes by committing them as facts into memory
        with associated task and thread information. Each write entry in the sequence is processed
        with a specific channel, value, and index to generate a payload, which is then committed.

        Args:
            config (RunnableConfig): The configuration object implementing the `RunnableConfig` interface. It must
                contain a "configurable" dictionary with a thread ID linked under the key "thread_id".
            writes (Sequence[tuple[str, Any]]): A sequence of tuples where each tuple contains a string representing the channel
                and an associated value of type `Any` to be committed.
            task_id (str): A string representing the unique identifier for the task that groups all the writes.
            task_path (str): (optional) A string that represents the path or hierarchy associated with
                the task. Defaults to an empty string if not provided.

        Returns:
            None
        """
        thread_id = config["configurable"]["thread_id"]

        for idx, (channel, value) in enumerate(writes):
            payload = {
                "task_id": task_id,
                "task_path": task_path,
                "channel": channel,
                "value": value,
                "idx": idx,
                "thread_id": thread_id,
            }

            self.memory.commit(
                Fact(type=self.write_type, payload=payload, source="langgraph_writes"), session_id=thread_id
            )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """
        Gets a checkpoint tuple based on the provided configuration.

        This method queries memory to retrieve facts associated with a specific thread ID
        from the configuration. Depending on whether a thread timestamp is provided,
        it selects the most recent fact or the one matching the given timestamp.
        Finally, it reconstructs the checkpoint tuple based on the retrieved fact's payload.

        Args:
            config (RunnableConfig): Configuration object containing thread-specific retrieval
                data, including `thread_id` and optionally `thread_ts`.

        Returns:
            A `CheckpointTuple` containing the retrieved checkpoint data if a fact is found, otherwise `None`.
        """
        thread_id = config["configurable"]["thread_id"]
        thread_ts = config["configurable"].get("thread_ts")

        facts = self.memory.query(typename=self.fact_type, filters={"session_id": thread_id})

        if not facts:
            return None

        if thread_ts:
            matching = [f for f in facts if f["payload"].get("thread_ts") == thread_ts]
            fact = matching[0] if matching else None
        else:
            facts.sort(key=lambda x: x["ts"], reverse=True)
            fact = facts[0]

        if not fact:
            return None

        payload = fact["payload"]
        checkpoint = payload["checkpoint"]
        pending_sends = checkpoint.get("pending_sends") or []

        # TODO: If you need support for restoring PENDING writes,
        # you'll need to run query(typename=self.write_type) here and insert them.
        # For a basic checkpointer, this isn't always necessary, since pending_sends is included in the checkpoint.

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=payload["metadata"],
            parent_config=None,  #  (optional, skip for now)
            pending_writes=pending_sends,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """
        List and yield checkpoint tuples based on given configuration and filters.

        This function retrieves fact data stored in memory, optionally applies
        filters based on configuration or other specified parameters, and yields
        checkpoint tuples sorted by timestamp. The functionality includes support
        for limiting the number of facts processed.

        Args:
            config (RunnableConfig | None): Configuration information for filtering facts. Optional.
            filter (dict[str, Any] | None): Additional criteria for filtering facts based on key-value pairs. Optional.
            before (RunnableConfig | None): Configuration object to apply filter before a certain criterion. Optional.
            limit (int | None): Maximum number of facts to process and yield. Optional.

        Returns:
            An iterator over checkpoint tuples derived from the filtered facts.
        """

        json_filters = {}

        if config and "configurable" in config:
            thread_id = config["configurable"].get("thread_id")
            if thread_id:
                json_filters["session_id"] = thread_id

        facts = self.memory.query(typename=self.fact_type, filters=json_filters if json_filters else None)

        facts.sort(key=lambda x: x["ts"], reverse=True)

        if limit:
            facts = facts[:limit]

        for fact in facts:
            payload = fact["payload"]
            yield CheckpointTuple(
                {
                    "configurable": {
                        "thread_id": payload.get("thread_id") or json_filters.get("session_id"),
                        "thread_ts": payload["thread_ts"],
                    }
                },
                payload["checkpoint"],
                payload["metadata"],
                (payload.get("checkpoint") or {}).get("pending_sends", []),
            )

    def delete_thread(self, thread_id: str) -> None:
        """
        Deletes a specific thread from memory by its identifier.

        This method removes the session associated with the given thread ID
        from the memory, ensuring that it is no longer retained or accessed
        in the system.

        Args:
            thread_id (str): The unique identifier of the thread to be deleted.

        Returns:
            This method does not return any value.
        """
        self.memory.discard_session(thread_id)


class AsyncMemStateCheckpointer(BaseCheckpointSaver[str]):
    """
    Async manages the storage, retrieval, and deletion of checkpoint data in memory.

    The AsyncMemStateCheckpointer class enables storing checkpoints using an in-memory
    storage system, facilitating workflows that require checkpointing and versioning
    mechanisms. It interacts with a memory store to persist checkpoint data and
    associated metadata, supporting use cases that require checkpointer objects
    functioning as temporary memory storage.

    Attributes:
        memory (AsyncMemoryStore): Reference to the memory store used for storage operations.
        serde (SerializerProtocol): Serializer for serializing checkpoint data.
        fact_type (str): String identifier for checkpoint facts within the memory store.
        write_type (str): String identifier for write facts within the memory store.
    """

    def __init__(self, memory: AsyncMemoryStore, serde: SerializerProtocol | None = None) -> None:
        super().__init__(serde=serde or JsonPlusSerializer())
        self.memory = memory
        self.fact_type = "langgraph_checkpoint"
        self.write_type = "langgraph_write"

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        """
        Asynchronously updates the state of a process by committing checkpoint metadata into memory
        and returning an updated configuration object.

        This method handles storing the provided checkpoint and its associated metadata
        to facilitate process tracking. It interacts with the memory instance to ensure
        the relevant details are committed within the appropriate session. After updating
        memory, it returns a modified configuration containing the updated thread
        parameters.

        Args:
            config (RunnableConfig): The configuration object for the runnable, which must include a `thread_id` under the `configurable` key.
            checkpoint (Checkpoint): The checkpoint object containing state information to be stored in memory.
            metadata (CheckpointMetadata): Additional metadata corresponding to the checkpoint, providing
                supplementary details about the stored state.
            new_versions (dict[str, Any]): A mapping of version keys to their new corresponding
                values, used to track changes in versions during the execution process.

        Returns:
            A modified configuration object reflecting the updated thread
                parameters after committing the provided checkpoint to memory.
        """
        thread_id = config["configurable"]["thread_id"]

        payload = {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "new_versions": new_versions,
            "thread_ts": checkpoint["id"],
        }

        # AWAIT COMMIT
        await self.memory.commit(
            Fact(type=self.fact_type, payload=payload, source="langgraph_checkpoint"), session_id=thread_id
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "thread_ts": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Asynchronously executes the operation to store a sequence of writes by committing them as facts into memory
        with associated task and thread information. Each write entry in the sequence is processed
        with a specific channel, value, and index to generate a payload, which is then committed.

        Args:
            config (RunnableConfig): The configuration object implementing the `RunnableConfig` interface. It must
                contain a "configurable" dictionary with a thread ID linked under the key "thread_id".
            writes (Sequence[tuple[str, Any]]): A sequence of tuples where each tuple contains a string representing the channel
                and an associated value of type `Any` to be committed.
            task_id (str): A string representing the unique identifier for the task that groups all the writes.
            task_path (str): (optional) A string that represents the path or hierarchy associated with
                the task. Defaults to an empty string if not provided.

        Returns:
            None
        """
        thread_id = config["configurable"]["thread_id"]

        for idx, (channel, value) in enumerate(writes):
            payload = {
                "task_id": task_id,
                "task_path": task_path,
                "channel": channel,
                "value": value,
                "idx": idx,
                "thread_id": thread_id,
            }

            # AWAIT COMMIT
            await self.memory.commit(
                Fact(type=self.write_type, payload=payload, source="langgraph_writes"), session_id=thread_id
            )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """
        Asynchronously gets a checkpoint tuple based on the provided configuration.

        This method queries memory to retrieve facts associated with a specific thread ID
        from the configuration. Depending on whether a thread timestamp is provided,
        it selects the most recent fact or the one matching the given timestamp.
        Finally, it reconstructs the checkpoint tuple based on the retrieved fact's payload.

        Args:
            config (RunnableConfig): Configuration object containing thread-specific retrieval
                data, including `thread_id` and optionally `thread_ts`.

        Returns:
            A `CheckpointTuple` containing the retrieved checkpoint data if a fact is found, otherwise `None`.
        """
        thread_id = config["configurable"]["thread_id"]
        thread_ts = config["configurable"].get("thread_ts")

        facts = await self.memory.storage.query(type_filter=self.fact_type, json_filters={"session_id": thread_id})

        if not facts:
            return None

        facts.sort(key=lambda x: x["ts"], reverse=True)

        fact = None
        if thread_ts:
            for f in facts:
                if f["payload"].get("thread_ts") == thread_ts:
                    fact = f
                    break
        else:
            fact = facts[0]

        if not fact:
            return None

        payload = fact["payload"]
        checkpoint = payload["checkpoint"]
        pending_sends = checkpoint.get("pending_sends") or []

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=payload["metadata"],
            parent_config=None,
            pending_writes=pending_sends,
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        Asynchronously list and yield checkpoint tuples based on given configuration and filters.

        This function retrieves fact data stored in memory, optionally applies
        filters based on configuration or other specified parameters, and yields
        checkpoint tuples sorted by timestamp. The functionality includes support
        for limiting the number of facts processed.

        Args:
            config (RunnableConfig | None): Configuration information for filtering facts. Optional.
            filter (dict[str, Any] | None): Additional criteria for filtering facts based on key-value pairs. Optional.
            before (RunnableConfig | None): Configuration object to apply filter before a certain criterion. Optional.
            limit (int | None): Maximum number of facts to process and yield. Optional.

        Returns:
            An iterator over checkpoint tuples derived from the filtered facts.
        """

        json_filters = {}
        if config and "configurable" in config:
            thread_id = config["configurable"].get("thread_id")
            if thread_id:
                json_filters["session_id"] = thread_id

        # AWAIT QUERY
        facts = await self.memory.storage.query(
            type_filter=self.fact_type, json_filters=json_filters if json_filters else None
        )
        facts.sort(key=lambda x: x["ts"], reverse=True)

        if limit:
            facts = facts[:limit]

        # ASYNC YIELD
        for fact in facts:
            payload = fact["payload"]
            yield CheckpointTuple(
                {
                    "configurable": {
                        "thread_id": payload.get("thread_id") or json_filters.get("session_id"),
                        "thread_ts": payload["thread_ts"],
                    }
                },
                payload["checkpoint"],
                payload["metadata"],
                (payload.get("checkpoint") or {}).get("pending_sends", []),
            )

    async def adelete_thread(self, thread_id: str) -> None:
        """
        Asynchronously deletes a specific thread from memory by its identifier.

        This method removes the session associated with the given thread ID
        from the memory, ensuring that it is no longer retained or accessed
        in the system.

        Args:
            thread_id (str): The unique identifier of the thread to be deleted.

        Returns:
            This method does not return any value.
        """
        await self.memory.discard_session(thread_id)
