from pydantic import BaseModel


class RewriteQueryResponse(BaseModel):
    thinking: str = ""
    query: str | None = None