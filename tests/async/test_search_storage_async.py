from memstate import AsyncInMemoryStorage, AsyncMemoryStore, Fact
from memstate.schemas import ScoredFact, SearchResult


class AsyncMockSearchHook:
    def __init__(self, results_to_return):
        self.results = results_to_return
        self.last_call_args = {}

    def __call__(self, *args, **kwargs):
        pass

    async def search(self, query, limit=5, filters=None, score_threshold=None):
        self.last_call_args = {"query": query, "filters": filters, "limit": limit}
        return self.results


async def test_search_happy_path():
    store = AsyncMemoryStore(AsyncInMemoryStorage())

    f1 = Fact(id="f1", type="doc", payload={"text": "Apple"})
    await store.commit(f1)

    hook = AsyncMockSearchHook([SearchResult(fact_id="f1", score=0.9)])
    store.add_hook(hook)

    results = await store.search("fruit")

    assert len(results) == 1
    item = results[0]

    assert isinstance(item, ScoredFact)
    assert item.score == 0.9
    assert item.fact.id == "f1"
    assert item.fact.payload == {"text": "Apple"}


async def test_search_filters_ghost_data():
    store = AsyncMemoryStore(AsyncInMemoryStorage())

    hook = AsyncMockSearchHook([SearchResult(fact_id="ghost_id", score=0.99)])
    store.add_hook(hook)

    results = await store.search("something")

    assert results == []


async def test_search_propagates_arguments():
    store = AsyncMemoryStore(AsyncInMemoryStorage())
    hook = AsyncMockSearchHook([])
    store.add_hook(hook)

    await store.search("test", limit=10, filters={"role": "user"})

    assert hook.last_call_args["query"] == "test"
    assert hook.last_call_args["limit"] == 10
    assert hook.last_call_args["filters"] == {"role": "user"}
