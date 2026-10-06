from pydantic import BaseModel


class AgentDescriptionResponse(BaseModel):
    description: str = ""