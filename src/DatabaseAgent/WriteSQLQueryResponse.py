from pydantic import BaseModel, Field


class WriteSQLQueryResponse(BaseModel):
    comments: list[str] = Field(default_factory=list)
    query: str = ""