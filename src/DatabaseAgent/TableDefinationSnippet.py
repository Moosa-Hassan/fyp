from dataclasses import dataclass
from uuid import UUID


@dataclass
class TableDefinitionSnippet:
    table_name: str
    key: UUID
    definition: str | None = None
    description: str | None = None
    sample_data: str | None = None
    text_embedding: list[float] | None = None