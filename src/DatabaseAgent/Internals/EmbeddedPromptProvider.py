from pathlib import Path


class EmbeddedPromptProvider:
    def read_prompt(self, prompt_name: str) -> str:
        prompt_path = (
            Path(__file__).parent
            .parent
            / "Prompts"
            / f"{prompt_name}.md"
        )

        return prompt_path.read_text(encoding="utf-8")