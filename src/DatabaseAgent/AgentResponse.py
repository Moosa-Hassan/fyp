from pydantic import BaseModel


class AgentResponse(BaseModel):
    thinking: str = ""
    answer: str = ""