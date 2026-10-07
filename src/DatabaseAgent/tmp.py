import asyncio
import os
from dotenv import load_dotenv
from semantic_kernel.connectors.ai.open_ai import (
    AzureChatCompletion,
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.contents import ChatHistory

load_dotenv()


async def main():
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    print("Endpoint:", endpoint)
    print("Deployment:", deployment)
    print("API key loaded:", bool(api_key))

    service = AzureChatCompletion(
        deployment_name=deployment,
        api_key=api_key,
        endpoint=endpoint,
        service_id="test",
    )

    history = ChatHistory()
    history.add_user_message("Say hello in one sentence.")

    settings = AzureChatPromptExecutionSettings(
        temperature=0
    )

    result = await service.get_chat_message_contents(
        chat_history=history,
        settings=settings,
    )

    print("\nSUCCESS:")
    print(result[0].content)


asyncio.run(main())