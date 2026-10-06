from typing import Protocol


class AgentPromptConstants:
    AGENT_DESCRIPTION_GENERATOR = "AgentDescriptionGenerator"
    AGENT_INSTRUCTIONS_GENERATOR = "AgentInstructionsGenerator"
    AGENT_NAME_GENERATOR = "AgentNameGenerator"
    EXPLAIN_TABLE = "ExplainTable"
    WRITE_SQL_QUERY = "WriteSQLQuery"
    REWRITE_USER_QUERY = "RewriteUserQuery"
    EXTRACT_TABLE_NAME = "ExtractTableName"


class IPromptProvider(Protocol):
    def read_prompt(self, prompt_name: str) -> str:
        ...