from dataclasses import dataclass
from uuid import UUID
from typing import Sequence


@dataclass
class AgentDefinitionSnippet:
    agent_name: str
    key: UUID
    description: str
    instructions: str
    text_embedding: Sequence[float]