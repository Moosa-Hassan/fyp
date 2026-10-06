from enum import Enum


class QdrantMemorySettings:
    def __init__(
        self,
        host: str,
        port: int = 6333,
        https: bool = False,
        api_key: str | None = None,
        dimensions: int = 1536,
    ):
        self.Host = host
        self.Port = port
        self.Https = https
        self.APIKey = api_key
        self.Dimensions = dimensions


class SQLiteMemorySettings:
    def __init__(
        self,
        connection_string: str,
        dimensions: int = 1536,
    ):
        self.ConnectionString = connection_string
        self.Dimensions = dimensions


class DatabaseSettings:
    def __init__(
        self,
        provider: str,
        connection_string: str,
    ):
        self.Provider = provider
        self.ConnectionString = connection_string


class KernelSettings:
    def __init__(
        self,
        completion: str,
        embedding: str,
    ):
        self.Completion = completion
        self.Embedding = embedding


class MemorySettings:

    class StorageType(Enum):
        Volatile = "Volatile"
        SQLite = "SQLite"
        Qdrant = "Qdrant"

    def __init__(
        self,
        kind,
        prefix_collection_name: str = "",
    ):
        self.Kind = kind
        self.PrefixCollectionName = prefix_collection_name