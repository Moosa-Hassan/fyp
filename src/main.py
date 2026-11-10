import argparse
import asyncio
import logging

from DatabaseAgent import AgentKernelFactory, DatabaseAgentFactory
from DatabaseAgent.DatabaseAgent import DatabaseKernelAgent
from simulation_cases import TEST_CASES


async def create_agent(rebuild: bool = False) -> DatabaseKernelAgent:
    ctx = AgentKernelFactory.configure_kernel(
        {"memory": {"Kind": "SQLite", "ConnectionString": "agent_memory.db"}}
    )
    return await DatabaseAgentFactory.create_agent(ctx, update=rebuild)


async def run(question: str, *, rebuild: bool = False) -> str:
    agent = await create_agent(rebuild)
    answer = await agent.invoke(question)

    if not answer:
        raise RuntimeError("agent returned no answer")

    return answer


async def run_simulation(*, rebuild: bool = False) -> None:
    agent = await create_agent(rebuild)
    for index, (question, expected) in enumerate(TEST_CASES, start=1):
        print(f"\n{'=' * 80}\nCase {index}/{len(TEST_CASES)}\nQuestion: {question}", flush=True)
        print(f"\nExpected answer:\n{expected}", flush=True)
        answer = await agent.invoke(question)
        if not answer:
            raise RuntimeError(f"agent returned no answer for simulation case {index}")
        print(f"\nActual answer:\n{answer}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the database agent a question.")
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to ask. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="Run all shared test cases sequentially using live model calls, without evaluation.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Log rewritten questions, generated SQL, and query results.",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Regenerate stored table descriptions and the agent definition before answering.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        logging.getLogger("DatabaseAgent.DatabaseAgent").setLevel(logging.DEBUG)

    question = " ".join(args.question).strip()
    if args.simulate:
        if question:
            parser.error("--simulate cannot be combined with a question")
        asyncio.run(run_simulation(rebuild=args.rebuild))
        return
    if not question:
        question = input("Question: ").strip()
    if not question:
        parser.error("a question is required")

    print(asyncio.run(run(question, rebuild=args.rebuild)))


if __name__ == "__main__":
    main()
