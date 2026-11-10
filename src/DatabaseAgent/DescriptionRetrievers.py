from __future__ import annotations

import re
from typing import AsyncIterator, Protocol
from uuid import UUID

from rank_bm25 import BM25Okapi

from .Internals.Embeddings import IEmbeddingService
from .Internals.VectorStore import VectorSearchResult
from .TableDefinationSnippet import TableDefinitionSnippet


class IDescriptionStore(Protocol):
    def search(
        self, embedding: list[float], top: int
    ) -> AsyncIterator[VectorSearchResult[TableDefinitionSnippet]]: ...

    async def get_all(self) -> list[TableDefinitionSnippet]: ...


class IDescriptionRetriever(Protocol):
    async def retrieve(
        self, query: str, top_k: int
    ) -> list[VectorSearchResult[TableDefinitionSnippet]]: ...


def _bm25_rank(
    query: str,
    items: list[VectorSearchResult[TableDefinitionSnippet]],
    top_n: int,
    *,
    matching_only: bool = False,
) -> list[VectorSearchResult[TableDefinitionSnippet]]:
    if not items:
        return []
    corpus = [
        re.findall(r"\w+", (item.record.description or "").lower()) or [""]
        for item in items
    ]
    query_tokens = re.findall(r"\w+", query.lower())
    scores = BM25Okapi(corpus).get_scores(query_tokens)
    order = sorted(range(len(items)), key=lambda index: scores[index], reverse=True)
    if matching_only:
        # BM25 may assign zero or negative scores to genuine common-term matches.
        tokens = set(query_tokens)
        order = [index for index in order if tokens.intersection(corpus[index])]
    return [items[index] for index in order[:top_n]]


class BaselineDescriptionRetriever:
    """Preserve the original vector-candidate search followed by BM25-only ordering."""

    def __init__(self, store: IDescriptionStore, embedding_service: IEmbeddingService) -> None:
        self._store = store
        self._embedding = embedding_service

    async def _vector_candidates(
        self, query: str, top_k: int
    ) -> list[VectorSearchResult[TableDefinitionSnippet]]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        embedding = await self._embedding.generate(query)
        return [
            result async for result in self._store.search(embedding, top=min(top_k * 5, 100))
        ]

    async def retrieve(
        self, query: str, top_k: int
    ) -> list[VectorSearchResult[TableDefinitionSnippet]]:
        related = await self._vector_candidates(query, top_k)
        return _bm25_rank(query, related, top_k)


class HybridDescriptionRetriever(BaselineDescriptionRetriever):
    """Fuse independent vector and full-description BM25 ranks using equal-weight RRF."""

    async def retrieve(
        self, query: str, top_k: int
    ) -> list[VectorSearchResult[TableDefinitionSnippet]]:
        vector = await self._vector_candidates(query, top_k)
        records = await self._store.get_all()
        lexical = _bm25_rank(
            query,
            [VectorSearchResult(record) for record in records],
            min(top_k * 5, 100),
            matching_only=True,
        )

        scores: dict[UUID, float] = {}
        candidates: dict[UUID, TableDefinitionSnippet] = {}
        for ranking in (vector, lexical):
            seen: set[UUID] = set()
            for rank, result in enumerate(ranking, start=1):
                key = result.record.key
                if key in seen:
                    continue
                seen.add(key)
                candidates[key] = result.record
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)

        ordered = sorted(scores, key=lambda key: (-scores[key], str(key)))
        return [
            VectorSearchResult(candidates[key], scores[key])
            for key in ordered[:top_k]
        ]
