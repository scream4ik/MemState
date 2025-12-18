# Exceptions & Error Handling

MemState uses a hierarchy of custom exceptions to help you handle failures gracefully. All exceptions inherit from `MemStateError`.

## Hierarchy

```text
MemStateError
├── ValidationFailed    (Schema mismatch)
├── ConflictError       (Constraint violation)
├── HookError           (Vector DB sync failure)
└── MemoryStoreError    (Storage issues, not found, etc.)
```

## HookError (The ACID Signal)

This is the most important exception in MemState. It is raised when a **Sync Hook** (e.g., ChromaDB, Qdrant) fails during a commit.

**What it means:**

* The Vector DB write failed (network timeout, auth error).
* **Crucial:** MemState has **already automatically rolled back** the SQL change.
* Your data is consistent (nothing saved), but the operation failed.

**How to handle:**

=== "Sync"
    ```python
    from memstate import HookError

    try:
        store.commit_model(user_pref)
    except HookError as e:
        # The transaction was rolled back.
        # You can retry, or ask the user to try again.
        print(f"Sync failed: {e}. Changes rolled back.")
    ```

=== "Async"
    ```python
    from memstate import HookError

    try:
        await store.commit_model(user_pref)
    except HookError as e:
        print(f"Sync failed: {e}. Changes rolled back.")
    ```

## ValidationFailed

Raised when the data provided (usually from an LLM) does not match the registered Pydantic schema.

**What it means:**

* The LLM generated a string for an `int` field, or missed a required field.
* The transaction was **rejected** before touching the database.

**How to handle:**
Usually, you catch this and feed the error message back to the LLM so it can "Self-Correct".

```python
from memstate import ValidationFailed

try:
    store.commit_model(model_from_llm)
except ValidationFailed as e:
    # Feedback loop for the Agent
    prompt_to_llm = f"You provided invalid data: {e}. Please fix and retry."
    retry_llm(prompt_to_llm)
```

## ConflictError

Raised when a write violates a defined `Constraint` (specifically `immutable=True`).

**What it means:**

* You tried to update a fact that was marked as immutable.
* Example: Trying to change a signed "User Agreement" fact.

```python
from memstate import Constraint, ConflictError

store.register_schema("policy", PolicyModel, constraint=Constraint(singleton_key="id", immutable=True))

try:
    store.commit_model(new_policy)
except ConflictError:
    print("Cannot overwrite immutable policy!")
```
