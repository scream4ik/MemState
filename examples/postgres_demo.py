from typing import List

from pydantic import BaseModel
from testcontainers.postgres import PostgresContainer

from memstate import Constraint, MemoryStore
from memstate.backends.postgres import PostgresStorage


# --- Data Model ---
class UserProfile(BaseModel):
    email: str
    full_name: str
    role: str
    level: str = "Junior"
    skills: List[str] = []


def print_fact(title, fact):
    print(title)
    if fact:
        print(f"  ID: {fact['id']}")
        print(f"  Payload: {fact['payload']}")
    else:
        print("  None")
    print()


# --- MAIN DEMO ---
def main():
    print(f"🚀 MemState + PostgreSQL (JSONB) Demo\n")

    # 1. Start Postgres in Docker (Automatic)
    print("🐳 Starting Postgres container...")
    with PostgresContainer("postgres:18-alpine") as postgres:

        # Fix driver string for SQLAlchemy (testcontainers returns old format)
        raw_url = postgres.get_connection_url()
        connection_string = raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")

        print(f"🔌 Connecting to: {connection_string}")

        # 2. Init Storage & Memory
        pg_storage = PostgresStorage(connection_string)
        memory = MemoryStore(pg_storage)

        # 3. Register Schema with SINGLETON Constraint
        # "email" is the unique key. If we commit a new model with the same email,
        # MemState will UPDATE the existing record instead of creating a duplicate.
        memory.register_schema(typename="user_profile", model=UserProfile, constraint=Constraint(singleton_key="email"))

        # --- SCENARIO START ---

        # Step 4: Create Initial Profile (Junior)
        print(f"\n1️⃣  Agent creates a Junior profile...")

        profile_v1 = UserProfile(
            email="alex@corp.com", full_name="Alex Dev", role="Backend", level="Junior", skills=["Python"]
        )

        # Using commit_model (High-Level API)
        # Note: We do NOT pass fact_id. MemState creates a new one.
        fact_id = memory.commit_model(profile_v1, actor="Agent_Smith", reason="Initial onboarding")

        current = pg_storage.load(fact_id)
        print_fact("Current State (Junior):", current)

        # Step 5: Update Profile (Singleton Logic)
        print(f"2️⃣  Agent finds LinkedIn info. Updating to Senior...")

        profile_v2 = UserProfile(
            email="alex@corp.com",  # SAME EMAIL triggers Singleton Update
            full_name="Alex Dev",
            role="Tech Lead",
            level="Senior",
            skills=["Python", "Architecture", "Postgres"],
        )

        # We perform a new commit. MemState detects email match and performs UPDATE.
        memory.commit_model(profile_v2, actor="Agent_Smith", reason="LinkedIn data enrichment")

        current = pg_storage.load(fact_id)
        print_fact("Current State (Senior):", current)

        # Step 6: JSONB Querying
        print(f"3️⃣  Testing Postgres JSONB Querying...")
        print("   Query: SELECT * WHERE payload->>'level' == 'Senior'")

        results = memory.query(
            typename="user_profile", filters={"payload.level": "Senior"}  # MemState converts this to JSONB path
        )

        if len(results) == 1:
            print(f"✅ Found correct user: {results[0]['payload']['full_name']}")
        else:
            print(f"❌ Query failed!")

        # Step 7: Audit Log (Compliance)
        print(f"\n4️⃣  Checking Transaction Log (History)...")
        # Assuming you implemented get_tx_log in PostgresStorage
        history = pg_storage.get_tx_log(session_id="session_1", limit=5)

        for tx in history:
            op = tx.get("op", "UNKNOWN")
            actor = tx.get("actor", "System")
            reason = tx.get("reason", "None")
            print(f"   📜 [{op}] by {actor}: {reason}")

        # Step 8: Rollback
        print(f"\n5️⃣  Oops! Update was a mistake. Rolling back...")
        memory.rollback(session_id="session_1", steps=1)

        final = pg_storage.load(fact_id)
        print(f"   Restored Level: {final['payload']['level']}")

        if final["payload"]["level"] == "Junior":
            print(f"\n✨ ACID Rollback successful! Data restored to Junior.")


if __name__ == "__main__":
    main()
