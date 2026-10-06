from pydantic import BaseModel


class DatabasePluginOptions(BaseModel):
    top_k: int = 5
    max_tokens: int | None = 4096
    temperature: float | None = 0.0000000001
    top_p: float | None = 0.0000000001