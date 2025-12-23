from typing import Any, List

import pytest

from memstate import Fact, InMemoryStorage, MemoryStore
from memstate.schemas import ScoredFact, SearchResult


class MockSearchHook:
    def __init__(self, results_to_return: List[SearchResult]):
        self.results = results_to_return
        self.last_call_args = {}

    def __call__(self, *args, **kwargs):
        pass

    def search(
        self, query: str, limit: int = 5, filters: dict[str, Any] | None = None, score_threshold: float | None = None
    ) -> List[SearchResult]:
        self.last_call_args = {"query": query, "filters": filters, "limit": limit}
        return self.results


def test_search_happy_path():
    store = MemoryStore(InMemoryStorage())

    f1 = Fact(id="f1", type="doc", payload={"text": "Apple"})
    store.commit(f1)

    hook = MockSearchHook([SearchResult(fact_id="f1", score=0.9)])
    store.add_hook(hook)

    results = store.search("fruit")

    assert len(results) == 1
    item = results[0]

    assert isinstance(item, ScoredFact)
    assert item.score == 0.9
    assert item.fact.id == "f1"
    assert item.fact.payload == {"text": "Apple"}


def test_search_filters_ghost_data():
    store = MemoryStore(InMemoryStorage())

    hook = MockSearchHook([SearchResult(fact_id="ghost_id", score=0.99)])
    store.add_hook(hook)

    results = store.search("something")

    assert results == []


def test_search_propagates_arguments():
    store = MemoryStore(InMemoryStorage())
    hook = MockSearchHook([])
    store.add_hook(hook)

    store.search("test", limit=10, filters={"role": "user"})

    assert hook.last_call_args["query"] == "test"
    assert hook.last_call_args["limit"] == 10
    assert hook.last_call_args["filters"] == {"role": "user"}
