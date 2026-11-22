import logging
import sys
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

import main
from DatabaseAgent.DatabaseAgent import RewriteMode
from DatabaseAgent.DatabasePluginOptions import DatabasePluginOptions


@pytest.mark.asyncio
@pytest.mark.parametrize("rebuild", [False, True])
@pytest.mark.parametrize("retriever", ["baseline", "hybrid"])
@pytest.mark.parametrize("rewrite_mode", ["always", "off", "conditional"])
async def test_single_question_forwards_rebuild_retriever_and_rewrite_mode(
    rebuild, retriever, rewrite_mode: RewriteMode
):
    agent = Mock(invoke=AsyncMock(return_value="77 products"))
    with (
        patch.object(main.AgentKernelFactory, "configure_kernel") as configure,
        patch.object(main.DatabaseAgentFactory, "create_agent", new_callable=AsyncMock,
                     return_value=agent) as create,
    ):
        assert await main.run(
            "How many products?",
            rebuild=rebuild,
            retriever=retriever,
            rewrite_mode=rewrite_mode,
        ) == "77 products"
    create.assert_awaited_once_with(
        configure.return_value,
        update=rebuild,
        options=DatabasePluginOptions(retriever=retriever),
    )
    agent.invoke.assert_awaited_once_with(
        "How many products?",
        rewrite_mode=rewrite_mode,
        clarification=None,
        confirm_rewrite=main._confirm_rewrite,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("retriever", ["baseline", "hybrid"])
@pytest.mark.parametrize("rewrite_mode", ["always", "off", "conditional"])
async def test_simulation_runs_shared_cases_in_order_with_one_agent(
    capsys, retriever, rewrite_mode: RewriteMode
):
    agent = Mock(invoke=AsyncMock(return_value="An answer"))
    with (
        patch.object(main.AgentKernelFactory, "configure_kernel") as configure,
        patch.object(main.DatabaseAgentFactory, "create_agent", new_callable=AsyncMock,
                     return_value=agent) as create,
    ):
        await main.run_simulation(
            rebuild=True, retriever=retriever, rewrite_mode=rewrite_mode
        )
    configure.assert_called_once()
    create.assert_awaited_once_with(
        configure.return_value,
        update=True,
        options=DatabasePluginOptions(retriever=retriever),
    )
    assert agent.invoke.await_args_list == [
        call(question, rewrite_mode=rewrite_mode) for question, _ in main.TEST_CASES
    ]
    output = capsys.readouterr().out
    for question, expected in main.TEST_CASES:
        assert question in output
        assert expected in output
    assert output.count("Actual answer:") == len(main.TEST_CASES)


@pytest.mark.asyncio
@pytest.mark.parametrize("simulation", [False, True])
async def test_empty_answers_raise(simulation):
    agent = Mock(invoke=AsyncMock(return_value=""))
    with patch.object(main, "create_agent", new_callable=AsyncMock, return_value=agent):
        with pytest.raises(RuntimeError, match="agent returned no answer"):
            if simulation:
                await main.run_simulation()
            else:
                await main.run("Question")


@pytest.mark.asyncio
async def test_simulation_propagates_errors_and_stops():
    agent = Mock(invoke=AsyncMock(side_effect=RuntimeError("Model unavailable")))
    with patch.object(main, "create_agent", new_callable=AsyncMock, return_value=agent):
        with pytest.raises(RuntimeError, match="Model unavailable"):
            await main.run_simulation()
    assert agent.invoke.await_count == 1


def test_cli_simulation_verbose_and_rebuild(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--simulate",
            "--verbose",
            "--rebuild",
            "--retriever",
            "hybrid",
            "--rewrite-mode",
            "off",
        ],
    )
    logger = logging.getLogger("DatabaseAgent.DatabaseAgent")
    previous_level = logger.level
    try:
        with (
            patch.object(main, "run_simulation", new_callable=AsyncMock) as simulate,
            patch("builtins.input") as prompt,
            patch.object(main.logging, "basicConfig") as configure_logging,
        ):
            main.main()
        simulate.assert_awaited_once_with(
            rebuild=True, retriever="hybrid", rewrite_mode="off"
        )
        prompt.assert_not_called()
        configure_logging.assert_called_once()
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(previous_level)


@pytest.mark.parametrize("interactive", [False, True])
def test_cli_existing_question_modes(monkeypatch, interactive, capsys):
    monkeypatch.setattr(
        sys, "argv", ["main.py"] if interactive else ["main.py", "How many products?"]
    )
    with (
        patch("builtins.input", return_value="How many products?") as prompt,
        patch.object(main, "run", new_callable=AsyncMock, return_value="77 products") as run,
    ):
        main.main()
    run.assert_awaited_once_with(
        "How many products?",
        rebuild=False,
        retriever="baseline",
        rewrite_mode="always",
    )
    assert prompt.call_count == int(interactive)
    assert "77 products" in capsys.readouterr().out


def test_cli_rejects_simulation_with_question(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulate", "Question"])
    with patch.object(main, "run_simulation", new_callable=AsyncMock) as simulate:
        with pytest.raises(SystemExit) as exc:
            main.main()
    assert exc.value.code == 2
    simulate.assert_not_awaited()


def test_cli_rejects_unknown_retriever(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--retriever", "unknown"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_cli_rejects_unknown_rewrite_mode(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--rewrite-mode", "unknown"])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_cli_continues_after_aborted_interactive_query(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    with (
        patch(
            "builtins.input",
            side_effect=["first question", "second question"],
        ) as prompt,
        patch.object(
            main,
            "run",
            new_callable=AsyncMock,
            side_effect=[main.QueryAborted(), "answer"],
        ) as run,
    ):
        main.main()

    assert prompt.call_count == 2
    assert run.await_args_list[0].args == ("first question",)
    assert run.await_args_list[1].args == ("second question",)
    assert "Query aborted. Enter another question." in capsys.readouterr().out
