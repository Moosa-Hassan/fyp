from semantic_kernel.connectors.ai.open_ai import (
    OpenAIChatPromptExecutionSettings,
)


class PromptExecutionSettingsHelper:

    @staticmethod
    def get_prompt_execution_settings(response_type):
        return OpenAIChatPromptExecutionSettings(
            max_tokens=4096,
            temperature=0.1e-9,
            top_p=0.1e-9,
            seed=0,
            response_format=response_type,
        )