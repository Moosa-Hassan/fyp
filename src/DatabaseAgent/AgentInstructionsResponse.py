from pydantic import BaseModel


class AgentInstructionsResponse(BaseModel):
    instructions: str