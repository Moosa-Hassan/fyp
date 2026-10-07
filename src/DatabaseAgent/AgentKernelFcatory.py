import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from openai import AsyncOpenAI

from .AgentContext import AgentContext
from .AgentDefinationSnippit import AgentDefinitionSnippet
from .Configuration.configuration import MemorySettings
from .Internals.Embeddings import HashingEmbeddingService, IEmbeddingService, LocalEmbeddingService
from .Internals.EmbeddedPromptProvider import EmbeddedPromptProvider
from .Internals.VectorStore import SimpleVectorStore
from .TableDefinationSnippet import TableDefinitionSnippet

load_dotenv()


class AgentKernelFactory:

    @staticmethod
    def configure_kernel(
        configuration: dict | None = None,
        logger_factory=None,
        chat_service=None,
        embedding_service: IEmbeddingService | None = None,
    ) -> AgentContext:
        """
        configuration (all optional):
            {"database": {"ConnectionString": "path/to/file.db"},
             "memory":   {"Kind": "Volatile" | "SQLite", "ConnectionString": "memory.db",
                          "PrefixCollectionName": "", "Dimensions": 256}}   # Dimensions only applies to the placeholder
        chat_service / embedding_service can be injected (tests, or once you have an embedding model).
        """
        cfg = configuration or {}
        database_settings = cfg.get("database", {})
        memory_settings = {"Kind": MemorySettings.StorageType.Volatile.value, **cfg.get("memory", {})}

        logger = (
            logger_factory.getLogger("AgentKernelFactory")
            if logger_factory
            else logging.getLogger("AgentKernelFactory")
        )

        # ---- Kernel + chat service -------------------------------------------------
        kernel = Kernel()

        if chat_service is None:
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

            for var, val in (
                ("AZURE_OPENAI_API_KEY", api_key),
                ("AZURE_OPENAI_ENDPOINT", endpoint),
                ("AZURE_OPENAI_DEPLOYMENT", deployment),
            ):
                if not val:
                    raise ValueError(f"{var} is not set.")

            async_client = AsyncOpenAI(
                api_key=api_key,
                base_url=endpoint.rstrip("/") + "/openai/v1/",
            )

            chat_service = OpenAIChatCompletion(
                ai_model_id=deployment,
                api_key=api_key,
                service_id="agent",
                async_client=async_client,
            )
        kernel.add_service(chat_service)

        # ---- Database (read-only) --------------------------------------------------
        db_path = Path(database_settings.get("ConnectionString") or Path(__file__).parent / "northwind.db")
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")
        connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True, check_same_thread=False)
        logger.info("Using database %s", db_path)

        # ---- Embeddings (placeholder until a real model exists) ---------------------
        # Priority: injected service > EMBEDDING_MODEL env var (local sentence-transformers) > placeholder.
        if embedding_service is None:
            model_name = os.getenv("EMBEDDING_MODEL")
            if model_name:
                embedding_service = LocalEmbeddingService(model_name)
            else:
                embedding_service = HashingEmbeddingService(dimensions=int(memory_settings.get("Dimensions", 256)))
        embedding = embedding_service

        # ---- Vector stores ---------------------------------------------------------
        kind = memory_settings["Kind"]
        logger.info("Using memory kind %s", kind)
        prefix = memory_settings.get("PrefixCollectionName", "")
        prefix = f"{prefix}-" if prefix else ""

        if kind == MemorySettings.StorageType.Volatile.value:
            path = None
        elif kind == MemorySettings.StorageType.SQLite.value:
            path = memory_settings["ConnectionString"]
        else:
            raise NotImplementedError(f"Memory kind '{kind}' is not implemented (use Volatile or SQLite).")

        table_store = SimpleVectorStore(f"{prefix}tables", TableDefinitionSnippet, path)
        agent_store = SimpleVectorStore(f"{prefix}agent", AgentDefinitionSnippet, path)

        return AgentContext(
            kernel=kernel,
            connection=connection,
            prompt_provider=EmbeddedPromptProvider(),
            embedding=embedding,
            table_store=table_store,
            agent_store=agent_store,
            logger=logger,
        )