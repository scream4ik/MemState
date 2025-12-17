import asyncio

from memstate import AsyncSQLiteStorage


async def test_sqlite_concurrent_writes(tmp_path):
    db_path = tmp_path / "race.db"
    storage = AsyncSQLiteStorage(str(db_path))
    await storage.connect()

    async def worker(i):
        await storage.save({"id": f"t-{i}", "type": "thread", "payload": {}, "ts": "..."})

    tasks = [worker(i) for i in range(50)]
    await asyncio.gather(*tasks)

    results = await storage.query(type_filter="thread")
    assert len(results) == 50

    await storage.close()
