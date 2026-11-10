
import json

import pytest
import pytest_asyncio
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.functions import KernelArguments, KernelFunctionFromPrompt
from semantic_kernel.prompt_template import PromptTemplateConfig

from DatabaseAgent import AgentKernelFactory, DatabaseAgentFactory
from simulation_cases import TEST_CASES


EVAL_PROMPT = """
Evaluate the semantic similarity between the expected answer and the actual response to the given question.

# Guidelines

- Score from 0 to 1: 0 = no similarity, 1 = identical meaning.
- Consider both content accuracy and completeness.
- Do not provide any explanation or additional commentary.

# Output Format

Return the similarity score as JSON:

{ "score": SCORE }

## Question:
{{$question}}

## Source of truth:
{{$expected}}

## Second sentence:
{{$actual}}
"""



@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    ctx = AgentKernelFactory.configure_kernel(
        {"memory": {"Kind": "SQLite", "ConnectionString": "agent_memory.db"}}
    )
    agent = await DatabaseAgentFactory.create_agent(ctx)
    return ctx.kernel, agent


@pytest.mark.asyncio(loop_scope="module")   
@pytest.mark.parametrize("question,expected_answer", TEST_CASES)
async def test_agent_can_answer_to_data(env, question, expected_answer):
    kernel, agent = env

    answer = await agent.invoke(question)
    assert answer, "agent returned no answer"

    evaluator = KernelFunctionFromPrompt(
        function_name="evaluate_answer",
        prompt_template_config=PromptTemplateConfig(
            template=EVAL_PROMPT,
            allow_dangerously_set_content=True,  # keep quotes/& in the tables unescaped
            execution_settings=OpenAIChatPromptExecutionSettings(
                max_completion_tokens=4096, response_format={"type": "json_object"}
            ),
        ),
    )
    result = await kernel.invoke(
        evaluator, KernelArguments(question=question, expected=expected_answer, actual=answer)
    )
    score = json.loads(str(result))["score"]

    print("\n" + "=" * 80)
    print("TEST RESULT")
    print("=" * 80)

    print(f"\nQuestion:\n{question}")

    print(f"\nSimilarity Score: {score:.3f}")

    print("\nExpected Answer:")
    print(expected_answer)

    print("\nActual Answer:")
    print(answer)

    print("=" * 80 + "\n")

    assert score >= 0.8, f"Answer is not similar enough. Score: {score:.3f}"