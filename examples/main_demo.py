import os
import sys

from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from memstate import Constraint, Fact, InMemoryStorage, MemoryStore

# --- 1. Defining Schemes ---


class UserProfile(BaseModel):
    email: str
    full_name: str
    role: str
    level: str = "Junior"  # Default value


class MeetingNote(BaseModel):
    topic: str
    summary: str
    action_items: list[str] = Field(default_factory=list)


# --- 2. Initialization (Brain + Memory) ---

storage = InMemoryStorage()
memory = MemoryStore(storage)

# --- 3. Registration of rules ---

# There must be ONE user profile for each email.
# If a new fact comes with the same email, it is an UPDATE, not a duplicate.
memory.register_schema(
    typename="user_profile", model=UserProfile, constraint=Constraint(singleton_key="email", immutable=False)
)

# Meeting notes can be duplicated, there are no restrictions.
memory.register_schema("meeting_note", MeetingNote)

print("🚀 Agent Memory initialized.\n")

# --- 4. Simulation of Agent work ---

# Scenario 1: Agent learns about the user
print("--- Step 1: Creating User Profile ---")
fact_profile = Fact(
    type="user_profile",
    payload={
        "email": "alex@corp.com",
        "full_name": "Alex Dev",
        "role": "Backend",
        # 'level' is not passed, Pydantic will substitute 'Junior' automatically!
    },
    source="chat_onboarding",
)
memory.commit(fact_profile, actor="Agent_Smith")

# Let's check what was recorded
saved_profile = memory.query(typename="user_profile")[0]
print(f"✅ Saved Profile: {saved_profile['payload']}")


# Scenario 2: Agent learns new data (Singleton Update)
print("\n--- Step 2: Updating Profile (Singleton Logic) ---")
# The agent realized that Alex was actually a Senior.
# He simply commits a new fact. The system will automatically find the old one by email and update it.
fact_update = Fact(
    type="user_profile",
    payload={"email": "alex@corp.com", "full_name": "Alex Dev", "role": "Backend Lead", "level": "Senior"},
    source="linkedin_parser",
)
memory.commit(fact_update, actor="Agent_Smith", reason="found linkedin profile")

# We're checking. There should be one fact left, but it should be updated.
profiles = memory.query(typename="user_profile")
print(f"✅ Total Profiles: {len(profiles)}")
print(f"✅ Updated Level: {profiles[0]['payload']['level']}")


# Scenario 3: Agent hallucinates (writes down delusions)
print("\n--- Step 3: Agent Hallucination ---")
bad_fact = Fact(
    type="meeting_note",
    payload={
        "topic": "Salary Negotiation",
        "summary": "Alex agreed to work for free.",  # Hallucination!
    },
    source="voice_transcription_error",
)
memory.commit(bad_fact, actor="Agent_Smith")
print("⚠️  Bad fact committed.")


# --- 5. Time Travel (Rollback) ---

print("\n--- Step 4: Detection & Rollback ---")
# The developer or Supervisor-Agent notices an error.
# Let's look at the latest transactions
logs = storage.get_tx_log(limit=2)
print(f"🔍 Last Action: {logs[0]['op']} by {logs[0]['actor']}")

print("↺ Rolling back 1 step...")
memory.rollback(steps=1)

# Let's check if the bad fact has disappeared
notes = memory.query(typename="meeting_note")
if not notes:
    print("✅ Rollback successful! The bad note is gone.")
else:
    print("❌ Failed, note still exists.")

# We check that the profile (previous state) is not damaged
profiles = memory.query(typename="user_profile")
print(f"✅ Profile still exists and is {profiles[0]['payload']['level']}")
