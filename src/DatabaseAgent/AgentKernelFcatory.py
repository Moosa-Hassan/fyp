import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from .Internals.EmbeddedPromptProvider import EmbeddedPromptProvider
from .Configuration.configuration import MemorySettings

from .AgentDefinationSnippit import AgentDefinitionSnippet
from .TableDefinationSnippet import TableDefinitionSnippet


load_dotenv()

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")


class AgentKernelFactory:

    @staticmethod
    def _get_vector_store_record_definition(
        vector_dimensions: int = 1536,
    ):
        return {
            "TableName": {
                "type": str,
                "indexed": True,
            },
            "Key": {
                "type": str,
            },
            "Definition": {
                "type": str,
            },
            "Description": {
                "type": str,
                "full_text_indexed": True,
            },
            "TextEmbedding": {
                "type": list[float],
                "dimensions": vector_dimensions,
            },
        }

    @staticmethod
    def _get_agent_store_record_definition(
        vector_dimensions: int = 1536,
    ):
        return {
            "AgentName": {
                "type": str,
                "indexed": True,
            },
            "Key": {
                "type": str,
            },
            "Description": {
                "type": str,
                "full_text_indexed": True,
            },
            "Instructions": {
                "type": str,
            },
            "TextEmbedding": {
                "type": list[float],
                "dimensions": vector_dimensions,
            },
        }

    @staticmethod
    def configure_kernel(configuration, logger_factory=None):

        kernel_settings = configuration["kernel"]
        database_settings = configuration["database"]
        memory_settings = configuration["memory"]

        # -------------------------------------------------
        # Create Kernel
        # -------------------------------------------------

        kernel = Kernel()

        # -------------------------------------------------
        # Azure OpenAI Chat Completion
        # -------------------------------------------------

        if not AZURE_OPENAI_API_KEY:
            raise ValueError(
                "AZURE_OPENAI_API_KEY is not set."
            )

        if not AZURE_OPENAI_ENDPOINT:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is not set."
            )

        if not AZURE_OPENAI_DEPLOYMENT:
            raise ValueError(
                "AZURE_OPENAI_DEPLOYMENT is not set."
            )

        chat_completion = AzureChatCompletion(
            deployment_name=AZURE_OPENAI_DEPLOYMENT,
            api_key=AZURE_OPENAI_API_KEY,
            endpoint=AZURE_OPENAI_ENDPOINT,
            service_id="agent",
        )

        kernel.add_service(chat_completion)

        # -------------------------------------------------
        # Database Connection
        # -------------------------------------------------

        db_path = Path(__file__).parent / "northwind.db"

        db_connection = sqlite3.connect(
            db_path
        )

        # -------------------------------------------------
        # Logger
        # -------------------------------------------------

        logger = (
            logger_factory.getLogger("AgentKernelFactory")
            if logger_factory
            else logging.getLogger("AgentKernelFactory")
        )

        logger.info(
            "Using database %s",
            db_path,
        )

        # -------------------------------------------------
        # Memory Configuration
        # -------------------------------------------------

        logger.info(
            "Using memory kind %s",
            memory_settings["Kind"],
        )

        prefix = memory_settings.get(
            "PrefixCollectionName",
            "",
        )

        if prefix:
            prefix += "-"

        memory_kind = memory_settings["Kind"]

        # -------------------------------------------------
        # Vector Store Definitions
        # -------------------------------------------------

        if memory_kind == MemorySettings.StorageType.Volatile.value:

            agent_collection = {
                "name": f"{prefix}agent",
                "definition":
                    AgentKernelFactory
                    ._get_agent_store_record_definition(),
            }

            table_collection = {
                "name": f"{prefix}tables",
                "definition":
                    AgentKernelFactory
                    ._get_vector_store_record_definition(),
            }

        elif memory_kind == MemorySettings.StorageType.SQLite.value:

            agent_collection = {
                "name": f"{prefix}agent",
                "connection_string":
                    memory_settings["ConnectionString"],
                "definition":
                    AgentKernelFactory
                    ._get_agent_store_record_definition(
                        memory_settings["Dimensions"]
                    ),
            }

            table_collection = {
                "name": f"{prefix}tables",
                "connection_string":
                    memory_settings["ConnectionString"],
                "definition":
                    AgentKernelFactory
                    ._get_vector_store_record_definition(
                        memory_settings["Dimensions"]
                    ),
            }

        elif memory_kind == MemorySettings.StorageType.Qdrant.value:

            agent_collection = {
                "name": f"{prefix}agent",
                "host": memory_settings["Host"],
                "port": memory_settings["Port"],
                "https": memory_settings["Https"],
                "api_key": memory_settings["APIKey"],
                "definition":
                    AgentKernelFactory
                    ._get_agent_store_record_definition(
                        memory_settings["Dimensions"]
                    ),
            }

            table_collection = {
                "name": f"{prefix}tables",
                "host": memory_settings["Host"],
                "port": memory_settings["Port"],
                "https": memory_settings["Https"],
                "api_key": memory_settings["APIKey"],
                "definition":
                    AgentKernelFactory
                    ._get_vector_store_record_definition(
                        memory_settings["Dimensions"]
                    ),
            }

        else:
            raise ValueError(
                f"Unknown storage type '{memory_kind}'"
            )

        # -------------------------------------------------
        # Prompt Provider
        # -------------------------------------------------

        prompt_provider = EmbeddedPromptProvider()

        # -------------------------------------------------
        # Return Kernel
        # -------------------------------------------------

        return kernel