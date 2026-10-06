from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from semantic_kernel import Kernel

from .Internals.Embeddings import IEmbeddingService
from .Internals.VectorStore import SimpleVectorStore
from .IPromptProvider import IPromptProvider


@dataclass
class AgentContext:
    """Everything the factory/plugin need. Replaces kernel.get_service("db_connection") etc.,
    because Python SK's kernel only holds AI services."""

    kernel: Kernel
    connection: Any
    prompt_provider: IPromptProvider
    embedding: IEmbeddingService
    table_store: SimpleVectorStore
    agent_store: SimpleVectorStore
    logger: logging.Logger