import argparse
import asyncio

from DatabaseAgent import AgentKernelFactory, DatabaseAgentFactory


async def run(question: str) -> str:
    ctx = AgentKernelFactory.configure_kernel(
        {"memory": {"Kind": "SQLite", "ConnectionString": "agent_memory.db"}}
    )
    agent = await DatabaseAgentFactory.create_agent(ctx)
    answer = await agent.invoke(question)

    if not answer:
        raise RuntimeError("agent returned no answer")

    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the database agent a question.")
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to ask. If omitted, you will be prompted.",
    )
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()
    if not question:
        parser.error("a question is required")

    print(asyncio.run(run(question)))


if __name__ == "__main__":
    main()
