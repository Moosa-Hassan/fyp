from pydantic import BaseModel, Field


class ExplainTableResponse(BaseModel):
    table_name: str = Field(default="", alias="tableName")
    attributes: str = ""
    record_sample: str = Field(default="", alias="recordSample")
    definition: str = ""
    relations: str = ""