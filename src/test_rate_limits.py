import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import NAMESPACE_DNS, UUID, uuid5

import httpx
import pytest
from openai import RateLimitError
from semantic_kernel import Kernel
from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent
from semantic_kernel.exceptions.function_exceptions import FunctionExecutionException

from DatabaseAgent import AgentKernelFactory, DatabaseAgentFactory
from DatabaseAgent.AgentDefinationSnippit import AgentDefinitionSnippet
from DatabaseAgent.AgentDescriptionResponse import AgentDescriptionResponse
from DatabaseAgent.AgentInstructionsResponse import AgentInstructionsResponse
from DatabaseAgent.AgentNameResponse import AgentNameResponse
from DatabaseAgent.DatabaseAgent import DatabaseKernelAgent
from DatabaseAgent.DatabasePlugin import DatabasePlugin
from DatabaseAgent.DatabasePluginOptions import DatabasePluginOptions
from DatabaseAgent.DescriptionRetrievers import BaselineDescriptionRetriever, HybridDescriptionRetriever
from DatabaseAgent.Internals.PromptRunner import run_prompt
from DatabaseAgent.Internals.RetryHelper import RetryHelper


@pytest.fixture(autouse=True)
def offline_credentials(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "test-deployment")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)


def rate_limit(headers=None):
    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://example.test/openai/v1/chat/completions"),
    )
    return RateLimitError("Token rate limit exceeded", response=response, body=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_rate_limit_retry_honors_server_delay(wrapped):
    error = rate_limit({"retry-after": "12"})
    if wrapped:
        error = FunctionExecutionException("Prompt failed", error)
    operation = AsyncMock(side_effect=[error, "ok"])
    with patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep:
        assert await RetryHelper.retry_rate_limited(operation) == "ok"
    sleep.assert_awaited_once_with(12.0)
    assert operation.await_count == 2


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"retry-after-ms": "1500", "retry-after": "10"}, 1.5),
        ({"x-ms-retry-after-ms": "2500"}, 2.5),
        ({"retry-after": "0"}, 60.0),
        ({"retry-after": "invalid"}, 60.0),
        ({"retry-after": "nan"}, 60.0),
        ({"retry-after": "-1"}, 60.0),
        ({}, 60.0),
    ],
)
def test_retry_delay(headers, expected):
    with patch("DatabaseAgent.Internals.RetryHelper.random.uniform", return_value=0):
        assert RetryHelper._retry_delay(rate_limit(headers), 0, logging.getLogger()) == expected


def test_retry_after_http_date():
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    delay = RetryHelper._retry_delay(
        rate_limit({"retry-after": format_datetime(retry_at, usegmt=True)}), 0, logging.getLogger()
    )
    assert 28 <= delay <= 30


@pytest.mark.asyncio
async def test_retry_exhaustion_preserves_exception():
    error = FunctionExecutionException("Prompt failed", rate_limit({"retry-after": "1"}))
    operation = AsyncMock(side_effect=error)
    with patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(FunctionExecutionException) as raised:
            await RetryHelper.retry_rate_limited(operation, count=3)
    assert raised.value is error
    assert operation.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_non_rate_limit_error_is_not_retried():
    operation = AsyncMock(side_effect=ValueError("Invalid response"))
    with patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(ValueError, match="Invalid response"):
            await RetryHelper.retry_rate_limited(operation)
    operation.assert_awaited_once()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_sql_retries_do_not_restart_exhausted_rate_limit_retries():
    error = FunctionExecutionException("Prompt failed", rate_limit())
    operation = AsyncMock(side_effect=error)
    with pytest.raises(FunctionExecutionException):
        await RetryHelper.try_function(operation)
    operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_prompt_calls_retry_wrapped_rate_limits():
    operation = AsyncMock(
        side_effect=[
            FunctionExecutionException("Prompt failed", rate_limit({"retry-after": "1"})),
            '{"name":"Agent"}',
        ]
    )
    with (
        patch("DatabaseAgent.Internals.PromptRunner.KernelFunctionFromPrompt") as function,
        patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        function.return_value.invoke = operation
        result = await run_prompt(Kernel(), "Generate a name", AgentNameResponse)
    assert result.name == "Agent"
    sleep.assert_awaited_once_with(1.0)
    assert operation.await_count == 2


@pytest.mark.asyncio
async def test_final_answer_retries_rate_limits():
    service = Mock()
    service.get_chat_message_content = AsyncMock(
        side_effect=[
            rate_limit({"retry-after": "2"}),
            ChatMessageContent(role=AuthorRole.ASSISTANT, content='{"answer":"42","thinking":""}'),
        ]
    )
    agent = DatabaseKernelAgent(
        kernel=Kernel(), name="Agent", description="", instructions="",
        prompt_provider=Mock(), plugin=Mock(),
    )
    with (
        patch.object(Kernel, "get_service", return_value=service),
        patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        assert await agent._generate_final_answer(ChatHistory(), None) == "42"
    sleep.assert_awaited_once_with(2.0)
    assert service.get_chat_message_content.await_count == 2


@pytest.mark.asyncio
async def test_sql_generation_retries_rate_limits():
    ctx = AgentKernelFactory.configure_kernel()
    try:
        plugin = DatabasePlugin(
            prompt_provider=ctx.prompt_provider, options=DatabasePluginOptions(),
            vector_store=ctx.table_store, connection=ctx.connection,
            embedding_service=ctx.embedding,
        )
        with (
            patch(
                "semantic_kernel.functions.KernelFunctionFromPrompt.invoke",
                new_callable=AsyncMock,
                side_effect=[rate_limit({"retry-after": "3"}), '{"query":"SELECT 1"}'],
            ) as invoke,
            patch("DatabaseAgent.Internals.RetryHelper.asyncio.sleep", new_callable=AsyncMock) as sleep,
        ):
            assert await plugin._get_sql_query_string_async(ctx.kernel, "test", "") == "SELECT 1"
        sleep.assert_awaited_once_with(3.0)
        assert invoke.await_count == 2
    finally:
        ctx.connection.close()


@pytest.mark.asyncio
async def test_schema_sample_excludes_binary_payloads():
    ctx = AgentKernelFactory.configure_kernel()
    ctx.connection.close()
    ctx.connection = sqlite3.connect(":memory:")
    try:
        ctx.connection.execute("CREATE TABLE sample (Name TEXT, Picture BLOB)")
        ctx.connection.execute(
            "INSERT INTO sample VALUES (?, ?)", ("Example product", b"\xff" * 100000)
        )
        definition, sample = await DatabaseAgentFactory._get_structure_and_sample(ctx, "sample")
        assert "Picture" in definition
        assert "Example product" in sample
        assert "[binary data: 100000 bytes]" in sample
        assert len(sample) < 500
        assert ctx.connection.execute("SELECT length(Picture) FROM sample").fetchone()[0] == 100000
    finally:
        ctx.connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "SavedAgent"])
@pytest.mark.parametrize("retriever", ["baseline", "hybrid"])
async def test_saved_agent_reused_across_contexts(tmp_path, name, retriever):
    configuration = {
        "memory": {"Kind": "SQLite", "ConnectionString": str(tmp_path / "memory.db")}
    }
    key = uuid5(NAMESPACE_DNS, name) if name else UUID(int=0)
    original = AgentKernelFactory.configure_kernel(configuration, chat_service=None)
    restored = None
    try:
        await original.agent_store.ensure_collection()
        await original.agent_store.upsert(
            AgentDefinitionSnippet("SavedAgent", key, "Saved description", "Saved instructions", [])
        )
        restored = AgentKernelFactory.configure_kernel(configuration, chat_service=None)
        with (
            patch.object(DatabaseAgentFactory, "memorize_schema", new_callable=AsyncMock) as memorize,
            patch("DatabaseAgent.DatabaseAgentFactory.run_prompt", new_callable=AsyncMock) as prompt,
        ):
            agent = await DatabaseAgentFactory.create_agent(
                restored, name=name, options=DatabasePluginOptions(retriever=retriever)
            )
        assert agent.name == "SavedAgent"
        assert agent.description == "Saved description"
        assert agent.instructions == "Saved instructions"
        expected_retriever = (
            HybridDescriptionRetriever if retriever == "hybrid" else BaselineDescriptionRetriever
        )
        assert type(agent._plugin._retriever) is expected_retriever
        memorize.assert_not_awaited()
        prompt.assert_not_awaited()
    finally:
        for ctx in (original, restored):
            if ctx is not None:
                ctx.connection.close()
                for store in (ctx.agent_store, ctx.table_store):
                    if store._db is not None:
                        store._db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("update,stored", [(False, False), (True, True)])
async def test_agent_generation_when_missing_or_forced(update, stored):
    ctx = AgentKernelFactory.configure_kernel(chat_service=None)
    try:
        if stored:
            await ctx.agent_store.upsert(
                AgentDefinitionSnippet("OldAgent", UUID(int=0), "Old description", "Old instructions", [])
            )
        with (
            patch.object(
                DatabaseAgentFactory, "memorize_schema", new_callable=AsyncMock, return_value="Schema"
            ) as memorize,
            patch(
                "DatabaseAgent.DatabaseAgentFactory.run_prompt",
                new_callable=AsyncMock,
                side_effect=[
                    AgentDescriptionResponse(description="New description"),
                    AgentNameResponse(name="NewAgent"),
                    AgentInstructionsResponse(instructions="New instructions"),
                ],
            ) as prompt,
        ):
            agent = await DatabaseAgentFactory.create_agent(ctx, update=update)
        assert agent.name == "NewAgent"
        assert prompt.await_count == 3
        memorize.assert_awaited_once_with(ctx, update=update)
        assert (await ctx.agent_store.get(UUID(int=0))).agent_name == "NewAgent"
    finally:
        ctx.connection.close()
