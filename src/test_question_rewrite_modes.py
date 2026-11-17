import logging
from unittest.mock import AsyncMock, Mock

import pytest

from DatabaseAgent.DatabaseAgent import DatabaseKernelAgent


def make_agent() -> DatabaseKernelAgent:
    agent = DatabaseKernelAgent(
        kernel=Mock(),
        name="test-agent",
        description="",
        instructions="",
        prompt_provider=Mock(),
        plugin=Mock(),
    )
    agent._generate_final_answer = AsyncMock(return_value="answer")
    agent._plugin.execute_query_async = AsyncMock(return_value="result")
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "rewrite_result", "expected_query", "calls_rewrite"),
    [
        ("always", "rewritten question", "rewritten question", 1),
        ("off", "rewritten question", "original question", 0),
        ("conditional", "rewritten question", "original question", 0),
    ],
)
async def test_rewrite_modes_select_query(
    mode, rewrite_result, expected_query, calls_rewrite
):
    agent = make_agent()
    agent.rewrite_query = AsyncMock(return_value=rewrite_result)

    await agent.invoke("original question", rewrite_mode=mode)

    if calls_rewrite:
        agent.rewrite_query.assert_awaited_once()
    else:
        agent.rewrite_query.assert_not_awaited()
    agent._plugin.execute_query_async.assert_awaited_once_with(
        kernel=agent.kernel,
        prompt=expected_query,
        original_query="original question",
    )


@pytest.mark.asyncio
async def test_changed_query_logs_original_and_rewritten(caplog):
    agent = make_agent()
    agent.rewrite_query = AsyncMock(return_value="rewritten question")

    with caplog.at_level(logging.INFO, logger="DatabaseAgent.DatabaseAgent"):
        await agent.invoke("original question")

    assert "Original query: original question" in caplog.text
    assert "Rewritten query: rewritten question" in caplog.text
