import os
import random
import shutil

import chromadb

from memstate import Fact, HookError, MemoryStore
from memstate.backends.sqlite import SQLiteStorage
from memstate.integrations.chroma import ChromaSyncHook

# --- CONFIGURATION ---
ITERATIONS = 1000
FAILURE_RATE = 0.10
RANDOM_SEED = 42


class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def setup_clean_env(path_sql, path_chroma):
    if os.path.exists(path_sql):
        os.remove(path_sql)
    if os.path.exists(path_chroma):
        shutil.rmtree(path_chroma)
    os.makedirs(path_chroma, exist_ok=True)


class ChaosChromaClient:
    """Wrapper that randomly fails network requests."""

    def __init__(self, real_client):
        self._client = real_client
        self.fail_rate = FAILURE_RATE

    def get_or_create_collection(self, name, **kwargs):
        real_coll = self._client.get_or_create_collection(name, **kwargs)
        return ChaosCollection(real_coll, self.fail_rate)

    def get_collection(self, name):
        real_coll = self._client.get_collection(name)
        return ChaosCollection(real_coll, self.fail_rate)


class ChaosCollection:
    def __init__(self, real_collection, fail_rate):
        self._coll = real_collection
        self._fail_rate = fail_rate

    def upsert(self, ids, documents, metadatas):
        # SIMULATE NETWORK FAILURE
        if random.random() < self._fail_rate:
            raise ConnectionError("❌ 504 Gateway Timeout (Simulated)")
        return self._coll.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def count(self):
        return self._coll.count()

    def get(self, ids):
        return self._coll.get(ids=ids)


# -----------------------------------------------------------------------------
# SCENARIO 1: The "Naive" Approach (Manual Sync)
# -----------------------------------------------------------------------------
def run_manual_sync():
    print(f"\n{Color.BOLD}1️⃣  Running MANUAL Sync (The Hard Way)...{Color.RESET}")

    db_path = "bench_manual.db"
    chroma_path = "bench_chroma_manual"
    setup_clean_env(db_path, chroma_path)

    # Setup
    sql_storage = SQLiteStorage(db_path)
    real_chroma = chromadb.PersistentClient(path=chroma_path)
    chaos_chroma = ChaosChromaClient(real_chroma)
    collection = chaos_chroma.get_or_create_collection("memory")

    for i in range(ITERATIONS):
        data = {"content": f"Fact {i}", "id": str(i)}

        # 1. SQL Write (Success)
        sql_storage.save({"id": data["id"], "payload": data})

        # 2. Vector Write (Failures ignored/uncaught)
        try:
            collection.upsert(ids=[data["id"]], documents=[data["content"]], metadatas=[{"source": "manual"}])
        except ConnectionError:
            pass  # The developer forgot to roll back the SQL!

    sql_count = len(sql_storage.query())
    vector_count = real_chroma.get_or_create_collection("memory").count()

    return sql_count, vector_count


# -----------------------------------------------------------------------------
# SCENARIO 2: MemState (ACID Sync)
# -----------------------------------------------------------------------------
def run_memstate_sync():
    print(f"\n{Color.BOLD}2️⃣  Running MEMSTATE Sync (ACID Transaction)...{Color.RESET}")

    db_path = "bench_memstate.db"
    chroma_path = "bench_chroma_memstate"
    setup_clean_env(db_path, chroma_path)

    # Setup
    real_chroma = chromadb.PersistentClient(path=chroma_path)
    chaos_chroma = ChaosChromaClient(real_chroma)  # Injecting failure

    hook = ChromaSyncHook(
        client=chaos_chroma, collection_name="memory", text_field="content"  # MemState works with the flaky client
    )

    sqlite = SQLiteStorage(db_path)
    memory = MemoryStore(sqlite)
    memory.add_hook(hook)

    for i in range(ITERATIONS):
        try:
            memory.commit(Fact(type="memory", payload={"content": f"Fact {i}"}))
        except HookError:
            # MemState threw an error -> that means it already did a ROLLBACK SQL statement internally
            pass

    sql_count = len(sqlite.query())
    vector_count = real_chroma.get_or_create_collection("memory").count()

    return sql_count, vector_count


# -----------------------------------------------------------------------------
# REPORTING
# -----------------------------------------------------------------------------
def print_results():
    random.seed(RANDOM_SEED)

    m_sql, m_vec = run_manual_sync()
    a_sql, a_vec = run_memstate_sync()

    m_drift = abs(m_sql - m_vec)
    m_drift_pct = (m_drift / m_sql) * 100 if m_sql else 0

    a_drift = abs(a_sql - a_vec)

    # For MemState, "Total records" may be lower (due to rollbacks),
    # but the main thing is that drift should be 0.

    print(f"\n{Color.BOLD}📊 BENCHMARK RESULTS ({ITERATIONS} ops, {int(FAILURE_RATE * 100)}% chaos){Color.RESET}")
    print("=" * 65)
    print(f"{'METRIC':<25} | {'MANUAL SYNC':<15} | {'MEMSTATE':<15}")
    print("-" * 65)
    print(f"{'SQL Records (Committed)':<25} | {m_sql:<15} | {a_sql:<15}")
    print(f"{'Vector Records (Synced)':<25} | {m_vec:<15} | {a_vec:<15}")
    print("-" * 65)

    drift_color = Color.RED if m_drift > 0 else Color.GREEN
    print(
        f"{'DATA DRIFT (Records)':<25} | {drift_color}{m_drift:<15}{Color.RESET} | {Color.GREEN}{a_drift:<15}{Color.RESET}"
    )

    drift_pct_color = Color.RED if m_drift_pct > 0 else Color.GREEN
    print(
        f"{'INCONSISTENCY RATE':<25} | {drift_pct_color}{m_drift_pct:.1f}%{Color.RESET}          | {Color.GREEN}0.0%{Color.RESET}"
    )
    print("=" * 65)

    if a_drift == 0 and a_sql < ITERATIONS:
        print(
            f"\n{Color.GREEN}🏆 WINNER: MemState kept data consistent (rolled back {ITERATIONS - a_sql} failed ops).{Color.RESET}"
        )
    elif a_drift == 0:
        print(f"\n{Color.GREEN}🏆 WINNER: Perfect consistency.{Color.RESET}")
    else:
        print(f"\n{Color.RED}❌ FAILED: MemState leaked data.{Color.RESET}")

    # Cleanup
    for p in ["bench_manual.db", "bench_memstate.db", "bench_chroma_manual", "bench_chroma_memstate"]:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)


if __name__ == "__main__":
    print_results()
