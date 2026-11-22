from typing import Literal

from pydantic import BaseModel


class QueryAnalysisResponse(BaseModel):
    outcome: Literal["preserve", "normalize", "clarify"]
    guidance: str = ""
    clarification_question: str = ""
