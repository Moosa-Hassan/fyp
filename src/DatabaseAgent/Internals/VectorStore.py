from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, AsyncIterator, Generic, TypeVar
from uuid import UUID

import numpy as np

T = TypeVar("T")


@dataclass
class VectorSearchResult:
    record: Any
    score: float | None = None


class SimpleVectorStore(Generic[T]):
    """Minimal vector store for a dataclass record with `key: UUID` and `text_embedding`.

    path=None -> volatile (in memory). path=<file> -> persisted in SQLite (JSON per record),
    search is brute-force cosine similarity, which is fine for a schema-sized collection.
    """

    def __init__(self, name: str, record_type: type[T], path: str | None = None) -> None:
        self._table = re.sub(r"\W", "_", name)
        self._type = record_type
        self._path = path
        self._records: dict[UUID, T] = {}
        self._db: sqlite3.Connection | None = None
        self._ready = False

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        if self._path:
            self._db = sqlite3.connect(self._path, check_same_thread=False)
            self._db.execute(
                f'CREATE TABLE IF NOT EXISTS "{self._table}" (key TEXT PRIMARY KEY, data TEXT NOT NULL)'
            )
            self._db.commit()
            for (data,) in self._db.execute(f'SELECT data FROM "{self._table}"'):
                rec = self._from_json(data)
                self._records[rec.key] = rec  # type: ignore[attr-defined]
        self._ready = True

    async def upsert(self, record: T) -> None:
        self._records[record.key] = record  # type: ignore[attr-defined]
        if self._db is not None:
            self._db.execute(
                f'INSERT OR REPLACE INTO "{self._table}" (key, data) VALUES (?, ?)',
                (str(record.key), self._to_json(record)),  # type: ignore[attr-defined]
            )
            self._db.commit()

    async def get(self, key: UUID) -> T | None:
        return self._records.get(key)

    async def find(self, **attrs: Any) -> T | None:
        for rec in self._records.values():
            if all(getattr(rec, k) == v for k, v in attrs.items()):
                return rec
        return None

    async def search(self, embedding: Any, top: int = 5) -> AsyncIterator[VectorSearchResult]:
        q = np.asarray(embedding, dtype=float)
        qn = np.linalg.norm(q) or 1.0
        scored: list[VectorSearchResult] = []
        for rec in self._records.values():
            emb = getattr(rec, "text_embedding", None)
            if emb is None or len(emb) == 0:
                continue
            v = np.asarray(emb, dtype=float)
            if v.shape != q.shape:
                raise ValueError(
                    f"Embedding size mismatch ({v.shape[0]} stored vs {q.shape[0]} query). "
                    "The embedding model changed: rebuild the store with update=True."
                )
            denom = (np.linalg.norm(v) * qn) or 1.0
            scored.append(VectorSearchResult(rec, float(v @ q / denom)))
        scored.sort(key=lambda r: r.score or 0.0, reverse=True)
        for r in scored[:top]:
            yield r

    def _to_json(self, rec: T) -> str:
        d = dataclasses.asdict(rec)  # type: ignore[call-overload]
        d["key"] = str(d["key"])
        if d.get("text_embedding") is not None:
            d["text_embedding"] = [float(x) for x in d["text_embedding"]]
        return json.dumps(d)

    def _from_json(self, data: str) -> T:
        d = json.loads(data)
        d["key"] = UUID(d["key"])
        return self._type(**d)  