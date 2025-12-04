from typing import Any, Iterator, Sequence

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
from memstate.storage import MemoryStore


class MemStateCheckpointer(BaseCheckpointSaver[str]):
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
        self.memory.discard_session(thread_id)
