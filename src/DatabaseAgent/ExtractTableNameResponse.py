from pydantic import BaseModel, ConfigDict, Field


class ExtractTableNameResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thinking: str = ""
    table_name: str = Field(default="", alias="tableName")