from semantic_kernel.connectors.ai.open_ai import (
    OpenAIChatPromptExecutionSettings,
)


class PromptExecutionSettingsHelper:

    @staticmethod
    def get_prompt_execution_settings(response_type):
        return OpenAIChatPromptExecutionSettings(
            max_completion_tokens=1000,
            response_format=response_type,
        )