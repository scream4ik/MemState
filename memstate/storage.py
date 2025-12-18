import asyncio
import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from memstate.backends.base import AsyncStorageBackend, StorageBackend
from memstate.constants import Operation
from memstate.exceptions import ConflictError, HookError, MemoryStoreError, ValidationFailed
from memstate.schemas import Fact, TxEntry
from memstate.types import AsyncMemoryHook, MemoryHook


class SchemaRegistry:
    """
    Manages schema registration and validation with a mapping of type names to Pydantic models.

    The SchemaRegistry class allows for the registration of Pydantic models with associated type names.
    It provides functionality for validating payloads against the registered schemas and for reverse-
    looking up type names by model classes.

    Attributes:
        schemas (dict[str, type[BaseModel]]): A mapping of type names to their registered Pydantic models.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, type[BaseModel]] = {}

    def register(self, typename: str, model: type[BaseModel]) -> None:
        """
        Registers a model under a specific type name within the schema registry.

        This method associates a given model with a unique type name in the internal
        schema registry. The registered type name and model can later be retrieved or
        used for validation or other processing purposes.

        Args:
            typename (str): The unique identifier for the model being registered.
            model (type[BaseModel]): The Pydantic model class to register.

        Returns:
            None
        """
        self._schemas[typename] = model

    def validate(self, typename: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Validates the given payload against the model schema for the specified type name. If no schema
        exists for the provided type name, the payload is returned unmodified. If validation fails, an
        exception containing the details of the validation failure is raised.

        Args:
            typename (str): The type name for which the payload is to be validated.
            payload (dict[str, Any]): The dictionary payload to be validated against the corresponding model schema.

        Returns:
            A dictionary containing the validated payload in JSON-serializable format.

        Raises:
            ValidationFailed: If the input payload fails validation against the schema.
        """
        model_cls = self._schemas.get(typename)
        if not model_cls:
            return payload
        try:
            instance = model_cls.model_validate(payload)
            return instance.model_dump(mode="json")
        except ValidationError as e:
            raise ValidationFailed(str(e))

    def get_type_by_model(self, model_class: type[BaseModel]) -> str | None:
        """
        Retrieve the type name associated with a given model class.

        This method iterates through a dictionary of schemas and checks if the
        provided model class matches any value in the dictionary. If a match is
        found, the corresponding type name is returned. If no match is found, it
        returns None.

        Args:
            model_class (type[BaseModel]): The Pydantic model class to find the corresponding type name for.

        Returns:
            The type name associated with the provided model class, or None if no match is found.
        """
        for type_name, cls in self._schemas.items():
            if cls == model_class:
                return type_name
        return None


class Constraint:
    """
    Represents a constraint with properties for configuration.

    This class is used to define constraints with options for a singleton
    key and immutability. It provides a structure to manage these constraint
    properties for further processing or validation.

    Attributes:
        singleton_key (str | None): Optional key used to identify a singleton behavior.
            If set, it implies uniqueness based on the value of the key.
        immutable (bool): Indicates if the constraint is immutable. If True, the
            constraint cannot be modified after its creation.
    """

    def __init__(self, singleton_key: str | None = None, immutable: bool = False) -> None:
        self.singleton_key = singleton_key
        self.immutable = immutable


class MemoryStore:
    """
    Handles in-memory storage of structured data with schema enforcement, transactional
    capabilities, and hooks for custom operations.

    This class provides a structured method to store and retrieve facts with enforced schema
    validation and constraints. It also supports mechanisms for transactional logging,
    model validation, and hook execution during operations.

    Attributes:
        storage (StorageBackend): Backend storage mechanism for persisting facts and transaction information.
        hooks (list[MemoryHook]): List of hooks to be executed during memory operations.
    """

    def __init__(self, storage: StorageBackend, hooks: list[MemoryHook] | None = None) -> None:
        self.storage = storage
        self._constraints: dict[str, Constraint] = {}
        self._schema_registry = SchemaRegistry()
        self._lock = threading.RLock()
        self._seq = 0
        self._hooks: list[MemoryHook] = hooks or []

    def register_schema(self, typename: str, model: type[BaseModel], constraint: Constraint | None = None) -> None:
        """
        Registers a schema in the schema registry and optionally applies a constraint.

        Args:
            typename (str): The unique identifier for the model being registered.
            model (type[BaseModel]): The Pydantic model class to register.
            constraint (Constraint | None): Optional constraint to associate with the type.

        Returns:
            None
        """
        self._schema_registry.register(typename, model)
        if constraint:
            self._constraints[typename] = constraint

    def add_hook(self, hook: MemoryHook) -> None:
        """
        Adds a new memory hook to the list of hooks.

        This method registers a `MemoryHook` instance into the internal hooks
        list for further processing. A `MemoryHook` is an abstraction that can
        be used to monitor and react to specific memory-related events.

        Args:
            hook (MemoryHook): The hook instance to be added to the hooks list.

        Returns:
            None
        """
        self._hooks.append(hook)

    def _notify_hooks(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        """
        Notifies all registered hooks about an operation applied to a fact.

        This method iterates over all hooks and invokes each with the operation performed,
        the fact identifier, and optional additional data. It propagates any exceptions
        raised by the hooks within a `HookError` wrapper.

        Args:
            op (Operation): The operation being performed, usually represented as an instance.
            fact_id (str): The identifier of the fact being affected by the operation.
            data (Fact | None): Optional data that provides additional information about the operation or fact.

        Returns:
            None

        Raises:
            HookError: If an exception is raised by a hook during execution.
        """
        for hook in self._hooks:
            try:
                hook(op, fact_id, data)
            except Exception as e:
                raise HookError(e)

    def _log_tx(
        self,
        op: Operation,
        session_id: str | None,
        fact_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor: str | None,
        reason: str | None,
    ) -> None:
        """
        Logs a transaction with details pertaining to an operation, including its type, timestamp, associated fact data,
        the actor involved, and the reason for the operation.

        Args:
            op (Operation): The operation being performed.
            fact_id (str | None): The unique identifier of the fact associated with the operation, or None if not applicable.
            before (dict[str, Any] | None): A dictionary containing the state of the fact before the operation, or None if not applicable.
            after (dict[str, Any] | None): A dictionary containing the state of the fact after the operation, or None if not applicable.
            actor (str | None): The identifier of the actor who performed the operation, or None if not provided.
            reason (str | None): The reason or justification for the operation, or None if not specified.

        Returns:
            None
        """
        self._seq += 1
        tx = TxEntry(
            session_id=session_id,
            seq=self._seq,
            ts=datetime.now(timezone.utc),
            op=op,
            fact_id=fact_id,
            fact_before=before,
            fact_after=after,
            actor=actor,
            reason=reason,
        )
        self.storage.append_tx(tx.model_dump(mode="json"))

    def commit(
        self,
        fact: Fact,
        session_id: str | None = None,
        ephemeral: bool = False,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str:
        """
        Commits a `Fact` object to the storage, optionally allowing for ephemeral
        storage, and updates existing records if applicable. The operation evaluates
        constraints such as immutability or uniqueness, handles potential duplicates,
        and invokes hooks for logging and notifications. Supports rollback of changes
        in case of errors.

        Args:
            fact (Fact): The `Fact` object to be committed. Validates the payload against
                schema registry and potentially updates or creates a new entry in the
                storage.
            session_id (str | None): Optional session identifier associated with the `Fact`.
            ephemeral (bool): Indicates whether the `Fact` is transient and should not be persisted. Defaults to `False`.
            actor (str | None): Optional identifier for the individual or system responsible
                for initiating the commit. Used for logging and auditing purposes.
            reason (str | None): Optional string describing the purpose of the commit. Used
                primarily for auditing and logging.

        Returns:
            The unique identifier of the committed fact.

        Raises:
            HookError: If an error occurs during hook execution.
        """
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
                new_state = fact.model_dump(mode="json")
                self.storage.save(new_state)
                self._log_tx(op, fact.session_id, fact.id, previous_state, new_state, actor, reason)
                self._notify_hooks(op, fact.id, fact)

                return fact.id

            except HookError as e:
                if op == Operation.UPDATE and previous_state:
                    self.storage.save(previous_state)
                else:
                    self.storage.delete(fact.id)

                raise e

    def commit_model(
        self,
        model: BaseModel,
        fact_id: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        ephemeral: bool = False,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str:
        """
        Commits a model to the store using the provided schema registry and additional metadata.

        This method registers a given `model` object with a schema type derived from its class. Metadata such
        as `fact_id`, `source`, `session_id`, `ephemeral`, `actor`, and `reason` can be supplied to categorize
        or provide context for the operation. If the model's schema type is not registered, an error is raised.

        Args:
            model (BaseModel): The model instance to commit.
            fact_id (str | None): Optional unique identifier for the fact. If not provided, a new UUID is generated.
            source (str | None): Optional source of the operation. Defaults to None.
            session_id (str | None): Optional identifier for the session in which the commit is performed. Defaults to None.
            ephemeral (bool): Optional. Determines if the data should be treated as ephemeral. Defaults to False.
            actor (str | None): Optional identifier for the entity performing the commit. Defaults to None.
            reason (str | None): Optional description or justification for the commit operation. Defaults to None.

        Returns:
            The result of the commit operation as a string.

        Raises:
            MemoryStoreError: If the model's schema type is not registered.
            HookError: If an error occurs during hook execution.
        """
        schema_type = self._schema_registry.get_type_by_model(model.__class__)

        if not schema_type:
            raise MemoryStoreError(
                f"Model class '{model.__class__.__name__}' is not registered. "
                f"Please call memory.register_schema('your_type_name', {model.__class__.__name__}) first."
            )

        fact = Fact(
            id=fact_id or str(uuid.uuid4()), type=schema_type, payload=model.model_dump(mode="json"), source=source
        )

        return self.commit(fact, session_id=session_id, ephemeral=ephemeral, actor=actor, reason=reason)

    def update(self, fact_id: str, patch: dict[str, Any], actor: str | None = None, reason: str | None = None) -> str:
        """
        Updates an existing fact in the store by applying a patch to its contents. The update process
        validates the resulting payload using the schema registry and manages concurrent modifications
        with locking. If the update fails during hook notification, the operation is rolled back
        to its previous state.

        Args:
            fact_id (str): The unique identifier of the fact to be updated.
            patch (dict[str, Any]): A dictionary representing the modifications to be applied to the current fact's payload.
            actor (str | None): Optional identifier for the user or system performing the update. Defaults to None if not applicable.
            reason (str | None): Optional reason or context for the update operation. Defaults to None.

        Returns:
            The unique identifier of the updated fact.

        Raises:
            MemoryStoreError: If the fact with the specified identifier is not found in the store.
            HookError: If an error occurs during the hook notification process.
        """
        with self._lock:
            existing = self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            before = copy.deepcopy(existing)
            draft = copy.deepcopy(existing)

            current_payload = draft.get("payload", {})
            patch_payload = patch.get("payload", {})
            current_payload.update(patch_payload)

            fact_type = draft["type"]
            validated_payload = self._schema_registry.validate(fact_type, current_payload)

            draft["payload"] = validated_payload
            draft["ts"] = datetime.now(timezone.utc).isoformat()

            try:
                self.storage.save(draft)
                self._log_tx(Operation.UPDATE, draft["session_id"], fact_id, before, draft, actor, reason)
                self._notify_hooks(Operation.UPDATE, fact_id, Fact(**draft))
            except HookError as e:
                self.storage.save(before)
                raise e

            return fact_id

    def delete(self, session_id: str | None, fact_id: str, actor: str | None = None, reason: str | None = None) -> str:
        """
        Deletes an existing fact from storage identified by the given fact ID. This operation logs the
        deletion, notifies hooks about the operation, and ensures thread safety during execution.

        Args:
            session_id (str | None): Optional identifier for the session in which the deletion is performed. Defaults to None.
            fact_id (str): The unique identifier of the fact to be deleted.
            actor (str | None): Optional identifier for the user or system performing the deletion. Defaults to None if not applicable.
            reason (str | None): Optional reason or context for the deletion operation. Defaults to None.

        Returns:
            The fact ID of the deleted fact.

        Raises:
            MemoryStoreError: If the fact with the given ID is not found in storage.
        """
        with self._lock:
            existing = self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            self.storage.delete(fact_id)
            self._log_tx(Operation.DELETE, session_id, fact_id, existing, None, actor, reason)
            self._notify_hooks(Operation.DELETE, fact_id, Fact(**existing))
            return fact_id

    def get(self, fact_id: str) -> dict[str, Any] | None:
        """
        Retrieves a fact from the storage based on the provided fact ID.

        This method accesses the underlying storage to load a fact corresponding
        to the given identifier. If the fact ID does not exist in the storage,
        the method will return None.

        Args:
            fact_id (str): The unique identifier of the fact to retrieve.

        Returns:
            A dictionary representation of the fact if found, otherwise None.
        """
        return self.storage.load(fact_id)

    def query(
        self, typename: str | None = None, filters: dict[str, Any] | None = None, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Executes a query against the storage with optional type and filter constraints.

        This method interacts with the underlying storage to filter and retrieve data
        based on the provided type and filtering criteria. The `typename` allows for
        filtering objects of a specific type, whereas `filters` enables more fine-grained
        queries by applying a JSON-based filter.

        Args:
            typename (str | None): A string that specifies the type of objects to query. If set
                to None, no type filtering is applied.
            filters (dict[str, Any] | None): A dictionary representing JSON-style filter constraints to
                apply to the query. If set to None, no filter constraints are applied.
            session_id (str | None): Optional identifier for the session associated with the query. Defaults to None.

        Returns:
            A list of dictionaries containing query results that match the given filters and type constraints.
        """
        final_filters = (filters or {}).copy()

        if session_id:
            final_filters["session_id"] = session_id

        return self.storage.query(type_filter=typename, json_filters=final_filters)

    def promote_session(
        self,
        session_id: str,
        selector: Callable[[dict[str, Any]], bool] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> list[str]:
        """
        Promotes session-related facts by modifying the session ID to dissociate
        them from the provided session. This is based on the selector criteria
        (if provided). The promotion operation will be logged and associated hooks
        will be notified.

        Args:
            session_id (str): The unique identifier of the session whose facts are to be processed for promotion.
            selector (Callable[[dict[str, Any]], bool] | None): A callable to filter facts based on custom logic. If
                provided, only facts passing this filter will be promoted. Defaults to None.
            actor (str | None): Optional identifier for the user or system performing the promotion operation. Defaults to None.
            reason (str | None): Optional reason or context for the promotion operation. Defaults to None.

        Returns:
            A list of identifiers for the promoted facts.
        """
        with self._lock:
            candidates = self.storage.get_session_facts(session_id)

            promoted = []
            for fact_dict in candidates:
                if selector and not selector(fact_dict):
                    continue

                before = dict(fact_dict)
                fact_dict["session_id"] = None
                self.storage.save(fact_dict)

                promoted.append(fact_dict["id"])
                self._log_tx(Operation.PROMOTE, session_id, fact_dict["id"], before, fact_dict, actor, reason)
                self._notify_hooks(Operation.PROMOTE, fact_dict["id"], Fact(**fact_dict))

            return promoted

    def discard_session(self, session_id: str) -> int:
        """
        Discard a session and clear related stored data in the storage.

        This method removes all records associated with the given session ID
        from the storage and logs the operation if any data is cleared.

        Args:
            session_id (str): The unique identifier of the session to discard.

        Returns:
            The number of records cleared from the storage.
        """
        deleted_ids = self.storage.delete_session(session_id)
        if deleted_ids:
            self._log_tx(
                Operation.DISCARD_SESSION,
                session_id,
                None,
                None,
                None,
                None,
                f"Session {session_id} cleared ({len(deleted_ids)} facts)",
            )
        return len(deleted_ids)

    def rollback(self, session_id: str, steps: int = 1) -> None:
        """
        Reverts the state of the storage by rolling back a specified number of transactional
        operations. Each operation is extracted from the transaction log and reversed based on
        its type (e.g., CREATE, UPDATE, DELETE).

        Args:
            session_id (str): The unique identifier of the session to roll back.
            steps (int): The number of transactional steps to roll back. Defaults to 1. Must be a positive integer.

        Returns:
            None
        """
        with self._lock:
            if steps <= 0:
                return

            logs = self.storage.get_tx_log(session_id=session_id, limit=steps)

            for entry in logs:
                op = entry["op"]
                fid = entry["fact_id"]

                if op in ("COMMIT", "COMMIT_EPHEMERAL", "UPDATE", "PROMOTE"):
                    if entry["fact_before"]:
                        self.storage.save(entry["fact_before"])
                        self._notify_hooks(Operation.UPDATE, fid, Fact(**entry["fact_before"]))
                    else:
                        if fid:
                            self.storage.delete(fid)
                            self._notify_hooks(Operation.DELETE, fid, None)

                elif op == "DELETE":
                    if entry["fact_before"]:
                        self.storage.save(entry["fact_before"])
                        self._notify_hooks(Operation.COMMIT, fid, Fact(**entry["fact_before"]))

            tx_uuids = [entry["uuid"] for entry in logs]
            self.storage.delete_txs(tx_uuids)


class AsyncMemoryStore:
    """
    Handles in-memory storage of structured data with schema enforcement, transactional
    capabilities, and hooks for custom operations.

    This class provides a structured method to store and retrieve facts with enforced schema
    validation and constraints. It also supports mechanisms for transactional logging,
    model validation, and hook execution during operations.

    Attributes:
        storage (AsyncStorageBackend): Backend storage mechanism for persisting facts and transaction information.
        hooks (list[AsyncMemoryHook]): List of hooks to be executed during memory operations.
    """

    def __init__(self, storage: AsyncStorageBackend, hooks: list[AsyncMemoryHook] | None = None) -> None:
        self.storage = storage
        self._constraints: dict[str, Constraint] = {}
        self._schema_registry = SchemaRegistry()
        self._lock = asyncio.Lock()
        self._seq = 0
        self._hooks: list[AsyncMemoryHook] = hooks or []

    def register_schema(self, typename: str, model: type[BaseModel], constraint: Constraint | None = None) -> None:
        """
        Registers a schema in the schema registry and optionally applies a constraint.

        Args:
            typename (str): The unique identifier for the model being registered.
            model (type[BaseModel]): The Pydantic model class to register.
            constraint (Constraint | None): Optional constraint to associate with the type.

        Returns:
            None
        """
        self._schema_registry.register(typename, model)
        if constraint:
            self._constraints[typename] = constraint

    def add_hook(self, hook: AsyncMemoryHook) -> None:
        """
        Adds a new memory hook to the list of hooks.

        This method registers a `AsyncMemoryHook` instance into the internal hooks
        list for further processing. A `AsyncMemoryHook` is an abstraction that can
        be used to monitor and react to specific memory-related events.

        Args:
            hook (AsyncMemoryHook): The hook instance to be added to the hooks list.

        Returns:
            None
        """
        self._hooks.append(hook)

    async def _notify_hooks(self, op: Operation, fact_id: str, data: Fact | None) -> None:
        """
        Asynchronously notifies all registered hooks about an operation applied to a fact.

        This method iterates over all hooks and invokes each with the operation performed,
        the fact identifier, and optional additional data. It propagates any exceptions
        raised by the hooks within a `HookError` wrapper.

        Args:
            op (Operation): The operation being performed, usually represented as an instance.
            fact_id (str): The identifier of the fact being affected by the operation.
            data (Fact | None): Optional data that provides additional information about the operation or fact.

        Returns:
            None

        Raises:
            HookError: If an exception is raised by a hook during execution.
        """
        for hook in self._hooks:
            try:
                await hook(op, fact_id, data)
            except Exception as e:
                raise HookError(e)

    async def _log_tx(
        self,
        op: Operation,
        session_id: str | None,
        fact_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        actor: str | None,
        reason: str | None,
    ) -> None:
        """
        Asynchronously logs a transaction with details pertaining to an operation, including its type, timestamp, associated fact data,
        the actor involved, and the reason for the operation.

        Args:
            op (Operation): The operation being performed.
            session_id (str | None): The identifier of the session associated with the operation, or None if not applicable.
            fact_id (str | None): The unique identifier of the fact associated with the operation, or None if not applicable.
            before (dict[str, Any] | None): A dictionary containing the state of the fact before the operation, or None if not applicable.
            after (dict[str, Any] | None): A dictionary containing the state of the fact after the operation, or None if not applicable.
            actor (str | None): The identifier of the actor who performed the operation, or None if not provided.
            reason (str | None): The reason or justification for the operation, or None if not specified.

        Returns:
            None
        """
        self._seq += 1
        tx = TxEntry(
            session_id=session_id,
            seq=self._seq,
            ts=datetime.now(timezone.utc),
            op=op,
            fact_id=fact_id,
            fact_before=before,
            fact_after=after,
            actor=actor,
            reason=reason,
        )
        await self.storage.append_tx(tx.model_dump(mode="json"))

    async def commit(
        self,
        fact: Fact,
        session_id: str | None = None,
        ephemeral: bool = False,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str:
        """
        Asynchronously commits a `Fact` object to the storage, optionally allowing for ephemeral
        storage, and updates existing records if applicable. The operation evaluates
        constraints such as immutability or uniqueness, handles potential duplicates,
        and invokes hooks for logging and notifications. Supports rollback of changes
        in case of errors.

        Args:
            fact (Fact): The `Fact` object to be committed. Validates the payload against
                schema registry and potentially updates or creates a new entry in the
                storage.
            session_id (str | None): Optional session identifier associated with the `Fact`.
            ephemeral (bool): Indicates whether the `Fact` is transient and should not be persisted. Defaults to `False`.
            actor (str | None): Optional identifier for the individual or system responsible
                for initiating the commit. Used for logging and auditing purposes.
            reason (str | None): Optional string describing the purpose of the commit. Used
                primarily for auditing and logging.

        Returns:
            The unique identifier of the committed fact.

        Raises:
            HookError: If an error occurs during hook execution.
        """
        async with self._lock:
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
                    matches = await self.storage.query(type_filter=fact.type, json_filters={search_key: key_val})

                    if matches:
                        existing_raw = matches[0]
                        if constraint.immutable:
                            raise ConflictError(f"Immutable constraint violation: {fact.type}:{key_val}")

                        # We found a duplicate, so this is an UPDATE of an existing one
                        previous_state = copy.deepcopy(existing_raw)
                        fact.id = existing_raw["id"]  # We replace the ID of the new fact with the old one
                        op = Operation.UPDATE

            if op != Operation.UPDATE:
                existing = await self.storage.load(fact.id)
                if existing:
                    previous_state = copy.deepcopy(existing)
                    op = Operation.UPDATE
                else:
                    op = Operation.COMMIT_EPHEMERAL if ephemeral else Operation.COMMIT

            try:
                new_state = fact.model_dump(mode="json")
                await self.storage.save(new_state)
                await self._log_tx(op, fact.session_id, fact.id, previous_state, new_state, actor, reason)
                await self._notify_hooks(op, fact.id, fact)

                return fact.id

            except HookError as e:
                if op == Operation.UPDATE and previous_state:
                    await self.storage.save(previous_state)
                else:
                    await self.storage.delete(fact.id)

                raise e

    async def commit_model(
        self,
        model: BaseModel,
        fact_id: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        ephemeral: bool = False,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str:
        """
        Asynchronously commits a model to the store using the provided schema registry and additional metadata.

        This method registers a given `model` object with a schema type derived from its class. Metadata such
        as `fact_id`, `source`, `session_id`, `ephemeral`, `actor`, and `reason` can be supplied to categorize
        or provide context for the operation. If the model's schema type is not registered, an error is raised.

        Args:
            model (BaseModel): The model instance to commit.
            fact_id (str | None): Optional unique identifier for the fact. If not provided, a new UUID is generated.
            source (str | None): Optional source of the operation. Defaults to None.
            session_id (str | None): Optional identifier for the session in which the commit is performed. Defaults to None.
            ephemeral (bool): Optional. Determines if the data should be treated as ephemeral. Defaults to False.
            actor (str | None): Optional identifier for the entity performing the commit. Defaults to None.
            reason (str | None): Optional description or justification for the commit operation. Defaults to None.

        Returns:
            The result of the commit operation as a string.

        Raises:
            MemoryStoreError: If the model's schema type is not registered.
            HookError: If an error occurs during hook execution.
        """
        schema_type = self._schema_registry.get_type_by_model(model.__class__)

        if not schema_type:
            raise MemoryStoreError(
                f"Model class '{model.__class__.__name__}' is not registered. "
                f"Please call memory.register_schema('your_type_name', {model.__class__.__name__}) first."
            )

        fact = Fact(
            id=fact_id or str(uuid.uuid4()), type=schema_type, payload=model.model_dump(mode="json"), source=source
        )

        return await self.commit(fact, session_id=session_id, ephemeral=ephemeral, actor=actor, reason=reason)

    async def update(
        self, fact_id: str, patch: dict[str, Any], actor: str | None = None, reason: str | None = None
    ) -> str:
        """
        Asynchronously updates an existing fact in the store by applying a patch to its contents. The update process
        validates the resulting payload using the schema registry and manages concurrent modifications
        with locking. If the update fails during hook notification, the operation is rolled back
        to its previous state.

        Args:
            fact_id (str): The unique identifier of the fact to be updated.
            patch (dict[str, Any]): A dictionary representing the modifications to be applied to the current fact's payload.
            actor (str | None): Optional identifier for the user or system performing the update. Defaults to None if not applicable.
            reason (str | None): Optional reason or context for the update operation. Defaults to None.

        Returns:
            The unique identifier of the updated fact.

        Raises:
            MemoryStoreError: If the fact with the specified identifier is not found in the store.
            HookError: If an error occurs during the hook notification process.
        """
        async with self._lock:
            existing = await self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            before = copy.deepcopy(existing)
            draft = copy.deepcopy(existing)

            current_payload = draft.get("payload", {})
            patch_payload = patch.get("payload", {})
            current_payload.update(patch_payload)

            fact_type = draft["type"]
            validated_payload = self._schema_registry.validate(fact_type, current_payload)

            draft["payload"] = validated_payload
            draft["ts"] = datetime.now(timezone.utc).isoformat()

            try:
                await self.storage.save(draft)
                await self._log_tx(Operation.UPDATE, draft["session_id"], fact_id, before, draft, actor, reason)
                await self._notify_hooks(Operation.UPDATE, fact_id, Fact(**draft))
            except HookError as e:
                await self.storage.save(before)
                raise e

            return fact_id

    async def delete(
        self, session_id: str | None, fact_id: str, actor: str | None = None, reason: str | None = None
    ) -> str:
        """
        Asynchronously deletes an existing fact from storage identified by the given fact ID. This operation logs the
        deletion, notifies hooks about the operation, and ensures thread safety during execution.

        Args:
            session_id (str | None): Optional identifier for the session associated with the deletion operation. Defaults to None.
            fact_id (str): The unique identifier of the fact to be deleted.
            actor (str | None): Optional identifier for the user or system performing the deletion. Defaults to None if not applicable.
            reason (str | None): Optional reason or context for the deletion operation. Defaults to None.

        Returns:
            The fact ID of the deleted fact.

        Raises:
            MemoryStoreError: If the fact with the given ID is not found in storage.
        """
        async with self._lock:
            existing = await self.storage.load(fact_id)
            if not existing:
                raise MemoryStoreError("Fact not found")

            await self.storage.delete(fact_id)
            await self._log_tx(Operation.DELETE, session_id, fact_id, existing, None, actor, reason)
            await self._notify_hooks(Operation.DELETE, fact_id, Fact(**existing))
            return fact_id

    async def get(self, fact_id: str) -> dict[str, Any] | None:
        """
        Asynchronously retrieves a fact from the storage based on the provided fact ID.

        This method accesses the underlying storage to load a fact corresponding
        to the given identifier. If the fact ID does not exist in the storage,
        the method will return None.

        Args:
            fact_id (str): The unique identifier of the fact to retrieve.

        Returns:
            A dictionary representation of the fact if found, otherwise None.
        """
        return await self.storage.load(fact_id)

    async def query(
        self, typename: str | None = None, filters: dict[str, Any] | None = None, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Asynchronously executes a query against the storage with optional type and filter constraints.

        This method interacts with the underlying storage to filter and retrieve data
        based on the provided type and filtering criteria. The `typename` allows for
        filtering objects of a specific type, whereas `filters` enables more fine-grained
        queries by applying a JSON-based filter.

        Args:
            typename (str | None): A string that specifies the type of objects to query. If set
                to None, no type filtering is applied.
            filters (dict[str, Any] | None): A dictionary representing JSON-style filter constraints to
                apply to the query. If set to None, no filter constraints are applied.
            session_id (str | None): Optional identifier for the session associated with the query. Defaults to None.

        Returns:
            A list of dictionaries containing query results that match the given filters and type constraints.
        """
        final_filters = (filters or {}).copy()

        if session_id:
            final_filters["session_id"] = session_id

        return await self.storage.query(type_filter=typename, json_filters=final_filters)

    async def promote_session(
        self,
        session_id: str,
        selector: Callable[[dict[str, Any]], bool] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> list[str]:
        """
        Asynchronously promotes session-related facts by modifying the session ID to dissociate
        them from the provided session. This is based on the selector criteria
        (if provided). The promotion operation will be logged and associated hooks
        will be notified.

        Args:
            session_id (str): The unique identifier of the session whose facts are to be processed for promotion.
            selector (Callable[[dict[str, Any]], bool] | None): A callable to filter facts based on custom logic. If
                provided, only facts passing this filter will be promoted. Defaults to None.
            actor (str | None): Optional identifier for the user or system performing the promotion operation. Defaults to None.
            reason (str | None): Optional reason or context for the promotion operation. Defaults to None.

        Returns:
            A list of identifiers for the promoted facts.
        """
        async with self._lock:
            candidates = await self.storage.get_session_facts(session_id)

            promoted = []
            for fact_dict in candidates:
                if selector and not selector(fact_dict):
                    continue

                before = dict(fact_dict)
                fact_dict["session_id"] = None
                await self.storage.save(fact_dict)

                promoted.append(fact_dict["id"])
                await self._log_tx(Operation.PROMOTE, session_id, fact_dict["id"], before, fact_dict, actor, reason)
                await self._notify_hooks(Operation.PROMOTE, fact_dict["id"], Fact(**fact_dict))

            return promoted

    async def discard_session(self, session_id: str) -> int:
        """
        Asynchronously discard a session and clear related stored data in the storage.

        This method removes all records associated with the given session ID
        from the storage and logs the operation if any data is cleared.

        Args:
            session_id (str): The unique identifier of the session to discard.

        Returns:
            The number of records cleared from the storage.
        """
        async with self._lock:
            deleted_ids = await self.storage.delete_session(session_id)
            if deleted_ids:
                await self._log_tx(
                    Operation.DISCARD_SESSION,
                    session_id,
                    None,
                    None,
                    None,
                    None,
                    f"Session {session_id} cleared ({len(deleted_ids)} facts)",
                )
                dummy = Fact(id="session", type="session", payload={}, session_id=session_id)
                await self._notify_hooks(Operation.DISCARD_SESSION, "", dummy)
            return len(deleted_ids)

    async def rollback(self, session_id: str, steps: int = 1) -> None:
        """
        Asynchronously reverts the state of the storage by rolling back a specified number of transactional
        operations. Each operation is extracted from the transaction log and reversed based on
        its type (e.g., CREATE, UPDATE, DELETE).

        Args:
            session_id (str): The unique identifier of the session to roll back.
            steps (int): The number of transactional steps to roll back. Defaults to 1. Must be a positive integer.

        Returns:
            None
        """
        async with self._lock:
            if steps <= 0:
                return

            logs = await self.storage.get_tx_log(session_id=session_id, limit=steps)

            for entry in logs:
                op = entry["op"]
                fid = entry["fact_id"]

                if op in ("COMMIT", "COMMIT_EPHEMERAL", "UPDATE", "PROMOTE"):
                    if entry["fact_before"]:
                        await self.storage.save(entry["fact_before"])
                        await self._notify_hooks(Operation.UPDATE, fid, Fact(**entry["fact_before"]))
                    else:
                        if fid:
                            await self.storage.delete(fid)
                            await self._notify_hooks(Operation.DELETE, fid, None)

                elif op == "DELETE":
                    if entry["fact_before"]:
                        await self.storage.save(entry["fact_before"])
                        await self._notify_hooks(Operation.COMMIT, fid, Fact(**entry["fact_before"]))

            tx_uuids = [entry["uuid"] for entry in logs]
            await self.storage.delete_txs(tx_uuids)
