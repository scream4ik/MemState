import sqlite3
import time


class Color:
    RED = "\033[91m"
    RESET = "\033[0m"


# --- Fake vector DB client without transactional semantics ---
class FakeVectorDB:
    def __init__(self):
        self.vector = None

    def upsert(self, text):
        print("Vector DB: updating embedding...")
        time.sleep(0.3)
        raise RuntimeError("Vector DB FAILURE")


# --- Setup SQL ---
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE profile (id INTEGER PRIMARY KEY, diet TEXT)")
conn.execute("INSERT INTO profile (diet) VALUES ('likes meat')")
conn.commit()

vec = FakeVectorDB()

print("\n--- WITHOUT MEMSTATE ---")
print("Initial state:")
print("SQL:", conn.execute("SELECT diet FROM profile").fetchone()[0])
print("Vector:", vec.vector)

print("\nAttempting to update diet to 'vegetarian'...")
print("SQL: updating diet...")
conn.execute("UPDATE profile SET diet='vegetarian'")
conn.commit()

try:
    vec.upsert("vegetarian")
except Exception as e:
    print("Vector DB ERROR:", e)

print("\nFinal state:")
print("SQL:", conn.execute("SELECT diet FROM profile").fetchone()[0])
print("Vector:", vec.vector)

print(f"{Color.RED}\n❌ INCONSISTENT STATE (SQL updated, vector stale){Color.RESET}")
