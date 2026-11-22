import logging
from unittest.mock import AsyncMock, Mock

import pytest

from DatabaseAgent.DatabaseAgent import (
    ClarificationRequired,
    DatabaseKernelAgent,
    QueryAborted,
)
from DatabaseAgent.QueryAnalysisResponse import QueryAnalysisResponse


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
    agent.analyze_query = AsyncMock(
        return_value=QueryAnalysisResponse(outcome="preserve")
    )
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
@pytest.mark.parametrize(
    ("mode", "outcome", "expected_query", "calls_rewrite"),
    [
        ("always", "normalize", "rewritten question", 1),
        ("conditional", "normalize", "rewritten question", 1),
        ("conditional", "preserve", "original question", 0),
        ("off", "normalize", "original question", 0),
    ],
)
async def test_analysis_controls_conditional_rewriting(
    mode, outcome, expected_query, calls_rewrite
):
    agent = make_agent()
    agent.analyze_query = AsyncMock(
        return_value=QueryAnalysisResponse(outcome=outcome, guidance="normalize dates")
    )
    agent.rewrite_query = AsyncMock(return_value="rewritten question")

    await agent.invoke(
        "original question",
        rewrite_mode=mode,
        clarification="user clarification",
    )

    if calls_rewrite:
        agent.rewrite_query.assert_awaited_once_with(
            "original question",
            guidance="normalize dates",
            clarification="user clarification",
        )
    else:
        agent.rewrite_query.assert_not_awaited()
    assert agent._plugin.execute_query_async.await_args.kwargs["prompt"] == expected_query


@pytest.mark.asyncio
async def test_clarify_blocks_sql():
    agent = make_agent()
    agent.analyze_query = AsyncMock(
        return_value=QueryAnalysisResponse(
            outcome="clarify",
            clarification_question="What does active mean?",
        )
    )

    with pytest.raises(ClarificationRequired, match="What does active mean"):
        await agent.invoke("How many active customers?")

    agent._plugin.execute_query_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_requires_confirmation_before_sql():
    agent = make_agent()
    agent.rewrite_query = AsyncMock(return_value="rewritten question")

    with pytest.raises(QueryAborted):
        await agent.invoke(
            "original question",
            confirm_rewrite=lambda original, rewritten: False,
        )

    agent._plugin.execute_query_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_query_logs_original_and_rewritten(caplog):
    agent = make_agent()
    agent.rewrite_query = AsyncMock(return_value="rewritten question")

    with caplog.at_level(logging.INFO, logger="DatabaseAgent.DatabaseAgent"):
        await agent.invoke("original question")

    assert "Original query: original question" in caplog.text
    assert "Rewritten query: rewritten question" in caplog.text
