from pydantic import BaseModel


class ExtractTableNameResponse(BaseModel):
    thinking: str = ""
    table_name: str = ""