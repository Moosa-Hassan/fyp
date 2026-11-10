import re
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from rank_bm25 import BM25Okapi

from DatabaseAgent.DatabasePluginOptions import DatabasePluginOptions
from DatabaseAgent.DescriptionRetrievers import (
    BaselineDescriptionRetriever,
    HybridDescriptionRetriever,
)
from DatabaseAgent.Internals.VectorStore import SimpleVectorStore, VectorSearchResult
from DatabaseAgent.TableDefinationSnippet import TableDefinitionSnippet


def record(number, description, embedding=None):
    return TableDefinitionSnippet(
        table_name=f"Table{number}", key=UUID(int=number),
        description=description, definition="RAW_SCHEMA_MUST_NOT_BE_USED",
        text_embedding=embedding,
    )


class DescriptionStore:
    def __init__(self, vector, records):
        self.vector = vector
        self.get_all = AsyncMock(return_value=records)
        self.search_calls = []

    async def search(self, embedding, top):
        self.search_calls.append((embedding, top))
        for result in self.vector[:top]:
            yield result


def embedding_service():
    return Mock(generate=AsyncMock(return_value=[1.0, 0.0]))


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["sales revenue", "MISSING WORD", "", "SALES"])
@pytest.mark.parametrize("top_k", [1, 3, 30])
async def test_baseline_matches_original_algorithm(query, top_k):
    candidates = [
        VectorSearchResult(record(1, "Customers place sales orders"), 0.9),
        VectorSearchResult(record(2, "Revenue and sales from order lines"), 0.7),
        VectorSearchResult(record(3, None), 0.3),
        VectorSearchResult(record(4, "Employee addresses"), 0.1),
    ]
    corpus = [
        re.findall(r"\w+", (item.record.description or "").lower()) or [""]
        for item in candidates
    ]
    scores = BM25Okapi(corpus).get_scores(re.findall(r"\w+", query.lower()))
    expected_order = sorted(range(len(candidates)), key=lambda index: scores[index], reverse=True)
    expected = [candidates[index] for index in expected_order[:top_k]]
    store = DescriptionStore(candidates, [])
    embedding = embedding_service()

    results = await BaselineDescriptionRetriever(store, embedding).retrieve(query, top_k)

    assert results == expected
    assert store.search_calls == [([1.0, 0.0], min(top_k * 5, 100))]
    embedding.generate.assert_awaited_once_with(query)
    store.get_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_recovers_lexical_match_outside_vector_candidates():
    lexical_only = record(1, "net_revenue", embedding=None)
    vector_only = record(2, "customer addresses")
    store = DescriptionStore(
        [VectorSearchResult(vector_only, 0.99)], [vector_only, lexical_only]
    )
    embedding = embedding_service()

    baseline = await BaselineDescriptionRetriever(store, embedding).retrieve("net_revenue", 1)
    hybrid = await HybridDescriptionRetriever(store, embedding).retrieve("net_revenue", 1)

    assert baseline[0].record.key == vector_only.key
    assert hybrid[0].record.key == lexical_only.key
    assert hybrid[0].score == pytest.approx(1 / 61)
    store.get_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_hybrid_uses_both_ranks_and_deduplicates_records():
    first = record(1, "order shipping")
    second = record(2, "revenue revenue")
    third = record(3, "revenue")
    store = DescriptionStore(
        [VectorSearchResult(first, 0.99), VectorSearchResult(second, 0.5)],
        [first, second, third],
    )
    results = await HybridDescriptionRetriever(store, embedding_service()).retrieve("revenue", 3)

    assert [item.record.key for item in results] == [second.key, first.key, third.key]
    assert results[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert results[1].score == pytest.approx(1 / 61)
    assert results[2].score == pytest.approx(1 / 62)
    assert len({item.record.key for item in results}) == len(results)


@pytest.mark.asyncio
async def test_hybrid_no_lexical_match_preserves_vector_order():
    first, second = record(2, "customer"), record(1, None)
    store = DescriptionStore(
        [VectorSearchResult(first, 0.9), VectorSearchResult(second, 0.2)], [first, second]
    )
    results = await HybridDescriptionRetriever(store, embedding_service()).retrieve("missing", 2)
    assert [item.record.key for item in results] == [first.key, second.key]


@pytest.mark.asyncio
async def test_hybrid_keeps_genuine_common_term_matches():
    common = record(1, "sales")
    store = DescriptionStore([], [common])
    results = await HybridDescriptionRetriever(store, embedding_service()).retrieve("sales", 1)
    assert [item.record.key for item in results] == [common.key]
    assert results[0].score == pytest.approx(1 / 61)


@pytest.mark.asyncio
async def test_hybrid_ties_are_deterministic_by_record_key():
    first, second = record(1, "revenue"), record(2, "customers")
    store = DescriptionStore([VectorSearchResult(second, 1)], [second, first])
    results = await HybridDescriptionRetriever(store, embedding_service()).retrieve("revenue", 2)
    assert [item.record.key for item in results] == [first.key, second.key]


@pytest.mark.asyncio
@pytest.mark.parametrize("retriever_type", [BaselineDescriptionRetriever, HybridDescriptionRetriever])
async def test_empty_store_returns_no_matches(retriever_type):
    assert await retriever_type(DescriptionStore([], []), embedding_service()).retrieve("sales", 5) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("top_k", [0, -1])
@pytest.mark.parametrize("retriever_type", [BaselineDescriptionRetriever, HybridDescriptionRetriever])
async def test_invalid_top_k_is_rejected(retriever_type, top_k):
    embedding = embedding_service()
    with pytest.raises(ValueError, match="top_k"):
        await retriever_type(DescriptionStore([], []), embedding).retrieve("sales", top_k)
    embedding.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("retriever_type", [BaselineDescriptionRetriever, HybridDescriptionRetriever])
async def test_embedding_errors_are_propagated(retriever_type):
    embedding = Mock(generate=AsyncMock(side_effect=RuntimeError("Embedding unavailable")))
    with pytest.raises(RuntimeError, match="Embedding unavailable"):
        await retriever_type(DescriptionStore([], []), embedding).retrieve("sales", 5)


@pytest.mark.asyncio
async def test_hybrid_does_not_hide_store_errors():
    store = DescriptionStore([], [])
    store.get_all.side_effect = RuntimeError("Memory unavailable")
    with pytest.raises(RuntimeError, match="Memory unavailable"):
        await HybridDescriptionRetriever(store, embedding_service()).retrieve("sales", 5)


@pytest.mark.parametrize("options", [{"retriever": "unknown"}, {"top_k": 0}, {"top_k": -1}])
def test_invalid_options_are_rejected(options):
    with pytest.raises(ValidationError):
        DatabasePluginOptions(**options)


@pytest.mark.asyncio
async def test_full_corpus_loads_from_persisted_memory_without_exposing_internal_list(tmp_path):
    path = str(tmp_path / "memory.db")
    original = SimpleVectorStore("tables", TableDefinitionSnippet, path)
    restored = SimpleVectorStore("tables", TableDefinitionSnippet, path)
    saved = record(1, "sales revenue")
    try:
        await original.ensure_collection()
        await original.upsert(saved)
        corpus = await restored.get_all()
        assert corpus == [saved]
        corpus.clear()
        assert await restored.get_all() == [saved]
    finally:
        for store in (original, restored):
            if store._db is not None:
                store._db.close()


@pytest.mark.asyncio
async def test_hybrid_limits_candidates_in_both_branches_and_final_output():
    records = [record(index + 1, "sales") for index in range(120)]
    store = DescriptionStore(
        [VectorSearchResult(item, 1.0) for item in reversed(records)], records
    )
    results = await HybridDescriptionRetriever(store, embedding_service()).retrieve("sales", 2)
    assert store.search_calls == [([1.0, 0.0], 10)]
    assert len(results) == 2
    assert [item.record.key for item in results] == [records[0].key, records[-1].key]
    assert all(item.score == pytest.approx(1 / 61) for item in results)
