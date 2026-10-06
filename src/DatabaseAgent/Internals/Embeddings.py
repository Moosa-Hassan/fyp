from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Any, Protocol


class IEmbeddingService(Protocol):
    dimensions: int

    async def generate(self, text: str) -> list[float]: ...


class HashingEmbeddingService:
    """PLACEHOLDER until a real embedding model is available.

    Hashed bag-of-words, L2-normalised. Gives lexical (not semantic) similarity, which is
    enough for the pipeline to run; BM25 reranking in DatabasePlugin does the real work.
    Vectors from this are NOT compatible with a real model: when you switch, rebuild the
    stores (create_agent(..., update=True) with a fresh/empty store).
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    async def generate(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for tok in re.findall(r"\w+", text.lower()):
            idx = int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "little") % self.dimensions
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SKEmbeddingService:
    """Wraps a Semantic Kernel embedding generator (e.g. AzureTextEmbedding) for later."""

    def __init__(self, generator: Any, dimensions: int = 1536) -> None:
        self._generator = generator
        self.dimensions = dimensions

    async def generate(self, text: str) -> list[float]:
        result = await self._generator.generate_embeddings([text])
        return [float(x) for x in result[0]]


class LocalEmbeddingService:
    """Free, local embeddings via sentence-transformers (pip install sentence-transformers).

    Downloads the model from Hugging Face on first use, then runs offline on CPU.
    Good defaults: "sentence-transformers/all-MiniLM-L6-v2" (384 dims),
                   "BAAI/bge-small-en-v1.5" (384 dims).
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy: only needed if used

        self._model = SentenceTransformer(model_name)
        self.dimensions = int(self._model.get_sentence_embedding_dimension())

    async def generate(self, text: str) -> list[float]:
        vec = await asyncio.to_thread(self._model.encode, text, normalize_embeddings=True)
        return [float(x) for x in vec]