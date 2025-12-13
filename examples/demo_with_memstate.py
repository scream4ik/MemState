import time

from pydantic import BaseModel

from memstate import Constraint, HookError, MemoryStore, Operation
from memstate.backends.sqlite import SQLiteStorage


class Color:
    GREEN = "\033[92m"
    RESET = "\033[0m"


class Food(BaseModel):
    user_id: str
    diet: str


# --- Fake vector DB hook that fails during sync ---
class FailingVectorHook:
    def __call__(self, op, fact_id, data):
        print("Vector DB: updating embedding...")
        print(op)
        time.sleep(0.3)
        if op != Operation.COMMIT:
            raise RuntimeError("Vector DB FAILURE")


print("\n--- WITH MEMSTATE ---")

# Setup MemState SQL backend
sql = SQLiteStorage("demo.db")
mem = MemoryStore(storage=sql)
mem.add_hook(FailingVectorHook())
mem.register_schema("food", Food, Constraint(singleton_key="user_id"))

# Seed initial state
meet_food = Food(user_id="bob", diet="likes meat")
mem.commit_model(meet_food, session_id="session_id")

print("Initial state:", mem.query())

print("\nStarting transaction to update diet → 'vegetarian'...")
try:
    vegetarian_food = Food(user_id="bob", diet="vegetarian")
    mem.commit_model(vegetarian_food, session_id="session_id")
except HookError as e:
    print("ERROR:", e)
    print("Rollback triggered...")

print("\nFinal state:", mem.query())
print(f"{Color.GREEN}\n✔️ CONSISTENT (atomic rollback){Color.RESET}")
