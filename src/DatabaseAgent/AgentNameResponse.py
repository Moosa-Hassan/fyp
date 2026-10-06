from pydantic import BaseModel


class AgentNameResponse(BaseModel):
    name: str