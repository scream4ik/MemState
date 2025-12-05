import copy
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from memstate.backends.base import StorageBackend
from memstate.constants import Operation
from memstate.exceptions import ConflictError, HookError, MemoryStoreError, ValidationFailed
from memstate.schemas import Fact, TxEntry

MemoryHook = Callable[[Operation, str, Fact | None], None]


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, type[BaseModel]] = {}

    def register(self, typename: str, model: type[BaseModel]) -> None:
        self._schemas[typename] = model

    def validate(self, typename: str, payload: dict[str, Any]) -> dict[str, Any]:
        model_cls = self._schemas.get(typename)
        if not model_cls:
            return payload
        try:
            instance = model_cls.model_validate(payload)
            return instance.model_dump()
        except ValidationError as e:
            raise ValidationFailed(str(e))


class Constraint:
    def __init__(self, singleton_key: str | None = None, immutable: bool = False) -> None:
        self.singleton_key = singleton_key
        self.immutable = immutable


class MemoryStore:
    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage
        self._constraints: dict[str, Constraint] = {}
        self._schema_registry = SchemaRegistry()
        self._lock = threading.RLock()
        self._seq = 0
        self._hooks: list[MemoryHook] = []

    def register_schema(self, typename: str, model: type[BaseModel], constraint: Constraint | None = None) -> None:
        self._schema_registry.register(typename, model)
        if constraint:
            self._constraints[typename] = constraint

    def add_hook(self, hook: MemoryHook):
        self._hooks.append(hook)

    def _notify_hooks(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        for hook in self._hooks:
            try:
                hook(op, fact_id, data)
            except Exception as e:
                raise HookError(e)

    def commit(
        self,
        fact: Fact,
        session_id: str | None = None,
        ephemeral: bool = False,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str:
        with self._lock:
            validated_payload = self._schema_registry.validate(fact.type, fact.payload)
            fact.payload = validated_payload

            if session_id:
                fact.session_id = session_id

            previous_state = None
            op = Operation.COMMIT

            constraint = self._constraints.get(fact.type)

            if constraint and constraint.singleton_key:
                key_val = validated_payload.get(constraint.singleton_key)
                if key_val is not None:
                    search_key = f"payload.{constraint.singleton_key}"
                    matches = self.storage.query(type_filter=fact.type, json_filters={search_key: key_val})

                    if matches:
                        existing_raw = matches[0]
                        if constraint.immutable:
                            raise ConflictError(f"Immutable constraint violation: {fact.type}:{key_val}")

                        # We found a duplicate, so this is an UPDATE of an existing one
                        previous_state = copy.deepcopy(existing_raw)
                        fact.id = existing_raw["id"]  # We replace the ID of the new fact with the old one
                        op = Operation.UPDATE

            if op != Operation.UPDATE:
                existing = self.storage.load(fact.id)
                if existing:
                    previous_state = copy.deepcopy(existing)
                    op = Operation.UPDATE
                else:
                    op = Operation.COMMIT_EPHEMERAL if ephemeral else Operation.COMMIT

            try:
                new_state = fact.model_dump()
                self.storage.save(new_state)
                self._log_tx(op, fact.id, previous_state, new_state, actor, reason)
                self._notify_hooks(op, fact.id, fact)

                return fact.id

            except HookError as e:
                if op == Operation.UPDATE and previous_state:
                    self.storage.save(previous_state)
                else:
                    self.storage.delete(fact.id)

                raise e

    def update(self, fact_id: str, patch: dict[str, Any], actor: str | None = None, reason: str | None = None) -> str:
        with self._lock:
            existing = self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            before = copy.deepcopy(existing)
            # Deep merge or shallow? Shallow for MVP
            existing["payload"].update(patch.get("payload", {}))
            existing["ts"] = datetime.now(timezone.utc).isoformat()

            self.storage.save(existing)
            self._log_tx(Operation.UPDATE, fact_id, before, existing, actor, reason)
            self._notify_hooks(Operation.UPDATE, fact_id, Fact(**existing))
            return fact_id

    def delete(self, fact_id: str, actor: str | None = None, reason: str | None = None) -> str:
        with self._lock:
            existing = self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            self.storage.delete(fact_id)
            self._log_tx(Operation.DELETE, fact_id, existing, None, actor, reason)
            self._notify_hooks(Operation.DELETE, fact_id, Fact(**existing))
            return fact_id

    def get(self, fact_id: str) -> dict[str, Any] | None:
        return self.storage.load(fact_id)

    def query(self, typename: str | None = None, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.storage.query(type_filter=typename, json_filters=filters)

    def promote_session(
        self,
        session_id: str,
        selector: Callable[[dict[str, Any]], bool] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> list[str]:
        with self._lock:
            # Find all session facts (via query or backend index)
            # RedisStorage and InMemory can search by session_id if we add it to the query.
            # For MVP, we use a query with a filter (slow on large volumes, fast with indexes)

            # In RedisStorage, it is better to create a separate get_session_facts method, but we use query
            # We assume that storage stores session_id in json data
            candidates = self.storage.query(json_filters={"session_id": session_id})

            promoted = []
            for fact_dict in candidates:
                if selector and not selector(fact_dict):
                    continue

                before = dict(fact_dict)
                fact_dict["session_id"] = None
                self.storage.save(fact_dict)

                promoted.append(fact_dict["id"])
                self._log_tx(Operation.PROMOTE, fact_dict["id"], before, fact_dict, actor, reason)
                self._notify_hooks(Operation.PROMOTE, fact_dict["id"], Fact(**fact_dict))

            return promoted

    def discard_session(self, session_id: str) -> int:
        deleted_ids = self.storage.delete_session(session_id)
        if deleted_ids:
            self._log_tx(
                Operation.DISCARD_SESSION,
                None,
                None,
                None,
                None,
                f"Session {session_id} cleared ({len(deleted_ids)} facts)",
            )
        return len(deleted_ids)

    def rollback(self, steps: int = 1) -> None:
        with self._lock:
            if steps <= 0:
                return

            logs = self.storage.get_tx_log(limit=steps)

            for entry in logs:
                op = entry["op"]
                fid = entry["fact_id"]

                if op in ("COMMIT", "COMMIT_EPHEMERAL", "UPDATE", "PROMOTE"):
                    if entry["fact_before"]:
                        self.storage.save(entry["fact_before"])
                    else:
                        if fid:
                            self.storage.delete(fid)

                elif op == "DELETE":
                    if entry["fact_before"]:
                        self.storage.save(entry["fact_before"])

            # Ideally, we should log the rollback fact ("Undo operation"),
            # so as not to break the chain of history, but for MVP we simply roll back the data.

    def _log_tx(
        self,
        op: Operation,
        fact_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor: str | None,
        reason: str | None,
    ) -> None:
        self._seq += 1
        tx = TxEntry(
            seq=self._seq,
            ts=datetime.now(timezone.utc),
            op=op,
            fact_id=fact_id,
            fact_before=before,
            fact_after=after,
            actor=actor,
            reason=reason,
        )
        self.storage.append_tx(tx.model_dump())
