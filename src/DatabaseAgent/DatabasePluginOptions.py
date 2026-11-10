from typing import Literal

from pydantic import BaseModel, Field


class DatabasePluginOptions(BaseModel):
    top_k: int = Field(default=5, ge=1)
    retriever: Literal["baseline", "hybrid"] = "baseline"
    max_tokens: int | None = 4096
    temperature: float | None = 0.0000000001
    top_p: float | None = 0.0000000001