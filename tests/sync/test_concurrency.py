import threading

from memstate import SQLiteStorage


def test_sqlite_concurrent_writes(tmp_path):
    db_path = tmp_path / "race.db"
    storage = SQLiteStorage(str(db_path))

    def worker(i):
        storage.save({"id": f"t-{i}", "type": "thread", "payload": {}, "ts": "..."})

    threads = []
    for i in range(50):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(storage.query(type_filter="thread")) == 50
