from __future__ import annotations

import logging
import re

from pydantic import ValidationError
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent

from .AgentResponse import AgentResponse
from .DatabasePlugin import DatabasePlugin
from .Internals.PromptRunner import parse_json_model, run_prompt
from .IPromptProvider import AgentPromptConstants, IPromptProvider
from .RewriteQueryResponse import RewriteQueryResponse

logger = logging.getLogger(__name__)

OUTPUT_FORMAT_PROMPT = """# Output Format

The output should be a JSON object structured as follows:

```json
{
    "thinking": "Your step-by-step thought process and reasoning based on the query result.",
    "answer": "Your final answer in natural language, addressing the question explicitly."
}
```

# Examples

**Example 1**

_Query_: What is the capital of France?  
_Query Result_: 
| Country       | Capital     |
|---------------|-------------|
| France        | Paris       |
| Germany       | Berlin      |
| Spain         | Madrid      |

_Output_:  
```json
{
    "thinking": "The query result indicates that the capital of France is listed as 'Paris.' Therefore, based on this data, the capital of France is Paris.",
    "answer": "The capital of France is Paris."
}
```

**Example 2**

_Query_: What is the population of New York City?  
_Query Result_: 
| City           | Population |
|----------------|------------|
| New York City  | 8,419,600  |
| Los Angeles    | 3,979,576  |

_Output_:  
```json
{
    "thinking": "The query result specifies that the population of New York City is 8,419,600. This directly answers the question about its population.",
    "answer": "The population of New York City is 8,419,600."
}
```
"""


class DatabaseKernelAgent:

    def __init__(
        self,
        kernel: Kernel,
        name: str,
        description: str,
        instructions: str,
        prompt_provider: IPromptProvider,
        plugin: DatabasePlugin,
        instructions_role: AuthorRole = AuthorRole.SYSTEM,
    ) -> None:
        self.kernel = kernel
        self.name = name
        self.description = description
        self.instructions = instructions
        self.instructions_role = instructions_role
        self._prompt_provider = prompt_provider
        self._plugin = plugin
        # OpenAI only accepts [a-zA-Z0-9_-] in message names; LLM-generated agent names may not comply
        self._message_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name or "DatabaseAgent")

    def get_name(self) -> str:
        return self.name or "DatabaseAgent"

    def get_display_name(self) -> str:
        return self.name.strip() if self.name and self.name.strip() else "UnnamedAgent"

    async def invoke(
        self,
        user_query: str,
        chat_history: ChatHistory | None = None,
        settings: OpenAIChatPromptExecutionSettings | None = None,
    ) -> str | None:
        """chat_history is the persistent thread: only the user message and the final answer
        are added to it. DB-result messages live in a working copy."""
        if chat_history is None:
            chat_history = ChatHistory()

        chat_history.add_message(ChatMessageContent(role=AuthorRole.USER, content=user_query))

        history = ChatHistory()
        for m in chat_history.messages:
            history.add_message(m)

        last_user = next(m.content for m in reversed(history.messages) if m.role == AuthorRole.USER)

        rewritten = await self.rewrite_query(last_user)
        logger.debug("Rewritten query: %s", rewritten)

        data = await self._plugin.execute_query_async(
            kernel=self.kernel,
            prompt=rewritten,
            original_query=last_user,
        )

        history.messages.insert(0, self._system("Here are the results from the database:"))
        history.messages.insert(1, self._system(data))

        answer = await self._generate_final_answer(history, settings)

        if answer is not None:
            chat_history.add_message(
                ChatMessageContent(role=AuthorRole.ASSISTANT, content=answer, name=self._message_name)
            )
        return answer

    async def rewrite_query(self, query: str) -> str:
        template = self._prompt_provider.read_prompt(AgentPromptConstants.REWRITE_USER_QUERY)
        response = await run_prompt(self.kernel, template, RewriteQueryResponse, query=query)
        return response.query or query  # fall back to the original question

    def _system(self, content: str) -> ChatMessageContent:
        return ChatMessageContent(role=AuthorRole.SYSTEM, content=content, name=self._message_name)

    def _setup_chat_history(self, history: ChatHistory) -> ChatHistory:
        chat = ChatHistory()
        if self.instructions and self.instructions.strip():
            chat.add_message(
                ChatMessageContent(
                    role=self.instructions_role, content=self.instructions, name=self._message_name
                )
            )
        chat.add_message(self._system(OUTPUT_FORMAT_PROMPT))
        for m in history.messages:
            chat.add_message(m)
        return chat

    async def _generate_final_answer(
        self,
        history: ChatHistory,
        settings: OpenAIChatPromptExecutionSettings | None,
    ) -> str | None:
        chat = self._setup_chat_history(history)

        settings = settings or OpenAIChatPromptExecutionSettings(response_format={"type": "json_object"})

        chat_service = self.kernel.get_service(type=ChatCompletionClientBase)
        result = await chat_service.get_chat_message_content(chat, settings, kernel=self.kernel)
        content = str(result.content if result is not None else "")

        try:
            response = parse_json_model(AgentResponse, content)
        except (ValidationError, ValueError) as ex:
            logger.warning("Failed to parse agent response. Content: %s (%s)", content, ex)
            return content  # return the raw message unchanged

        if not response.answer:
            logger.warning("Agent response had no answer. Content: %s", content)
            return None

        return response.answer