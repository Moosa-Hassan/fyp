import json
import pytest

from semantic_kernel.functions import KernelFunction
from semantic_kernel.connectors.ai.open_ai import (
    OpenAIChatPromptExecutionSettings,
)

from src.DatabaseAgent.AgentKernelFcatory import AgentKernelFactory
from src.DatabaseAgent.DatabaseAgentFactory import DatabaseAgentFactory


TEST_CASES = [
    (
        "Counts the number of orders placed by each customer in the top 5",
        """| CustomerID | OrderCount |
| --- | --- |
| BSBEV | 210 |
| RICAR | 203 |
| LILAS | 203 |
| GOURL | 202 |
| PRINI | 200 |
|""",
    ),

    (
        "Compute the units sold for each of the top 5 products by aggregating the quantity values from the order details",
        """| ProductName | TotalUnitsSold |
| --- | --- |
| Louisiana Hot Spiced Okra | 206213 |
| Sir Rodney's Marmalade | 205637 |
| Teatime Chocolate Biscuits | 205487 |
| Sirop d'érable | 205005 |
| Gumbär Gummibärchen | 204761 |
|""",
    ),

    (
        "Calculate the average unit price of products grouped by their category.",
        """| CategoryName | average_unit_price |
| --- | --- |
| Beverages | 37.979166666666664 |
| Condiments | 23.0625 |
| Confections | 25.16 |
| Dairy Products | 28.73 |
| Grains/Cereals | 20.25 |
| Meat/Poultry | 54.00666666666667 |
| Produce | 32.37 |
| Seafood | 20.6825 |
|""",
    ),

    (
        "Count how many orders each employee has processed",
        """| EmployeeID | OrderCount |
| --- | --- |
| 1 | 1846 |
| 2 | 1771 |
| 3 | 1846 |
| 4 | 1908 |
| 5 | 1804 |
| 6 | 1754 |
| 7 | 1789 |
| 8 | 1798 |
| 9 | 1766 |
|""",
    ),

    (
        "List the five products with the highest unit price",
        """| ProductName | UnitPrice |
| --- | --- |
| Côte de Blaye | 263.5 |
| Thüringer Rostbratwurst | 123.79 |
| Mishi Kobe Niku | 97 |
| Sir Rodney's Marmalade | 81 |
| Carnarvon Tigers | 62.5 |
|""",
    ),

    (
        "Counts how many sales were made with and without a discount",
        """| sales_with_discount | sales_without_discount |
| --- | --- |
| 838 | 608445 |
|""",
    ),

    (
        "Calculate the total revenue generated from the product 'Chai'",
        """| total_revenue |
| --- |
| 3632174.1 |
|""",
    ),

    (
        "Counts how many products each supplier provides",
        """| CompanyName | ProductCount |
| --- | --- |
| Aux joyeux ecclésiastiques | 2 |
| Bigfoot Breweries | 3 |
| Cooperativa de Quesos 'Las Cabras' | 2 |
| Escargots Nouveaux | 1 |
| Exotic Liquids | 3 |
| Formaggi Fortini s.r.l. | 3 |
| Forêts d'érables | 2 |
| G'day, Mate | 3 |
| Gai pâturage | 2 |
| Grandma Kelly's Homestead | 3 |
| Heli Süßwaren GmbH & Co. KG | 3 |
| Karkki Oy | 3 |
| Leka Trading | 3 |
| Lyngbysild | 2 |
| Ma Maison | 2 |
| Mayumi's | 3 |
| New England Seafood Cannery | 2 |
| New Orleans Cajun Delights | 4 |
| Nord-Ost-Fisch Handelsgesellschaft mbH | 1 |
| Norske Meierier | 3 |
| PB Knäckebröd AB | 2 |
| Pasta Buttini s.r.l. | 2 |
| Pavlova, Ltd. | 5 |
| Plutzer Lebensmittelgroßmärkte AG | 5 |
| Refrescos Americanas LTDA | 1 |
| Specialty Biscuits, Ltd. | 4 |
| Svensk Sjöföda AB | 3 |
| Tokyo Traders | 3 |
| Zaanse Snoepfabriek | 2 |
|""",
    ),

    (
        "List employees and their manager",
        """| EmployeeName | ManagerName |
| --- | --- |
| Nancy Davolio | Andrew Fuller |
| Andrew Fuller | |
| Janet Leverling | Andrew Fuller |
| Margaret Peacock | Andrew Fuller |
| Steven Buchanan | Andrew Fuller |
| Michael Suyama | Steven Buchanan |
| Robert King | Steven Buchanan |
| Laura Callahan | Andrew Fuller |
| Anne Dodsworth | Steven Buchanan |
|""",
    ),

    (
        "Lists the top 5 orders with the most expensive shipping fees",
        """| OrderID | Freight |
| --- | --- |
| 13460 | 587 |
| 17596 | 580.75 |
| 13372 | 574.5 |
| 13466 | 568.25 |
| 25679 | 561.25 |
|""",
    ),
]


class TestDatabaseAgent:

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, request):

        # 1. Configure kernel and vector stores
        kernel = AgentKernelFactory.configure_kernel()

        # 2. Create database agent
        agent = DatabaseAgentFactory.create_agent(
            kernel,
            update=True,
        )

        request.cls.kernel = kernel
        request.cls.agent = agent

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "question,expected_answer",
        TEST_CASES,
    )
    async def test_agent_can_answer_to_data(
        self,
        question,
        expected_answer,
    ):

        # 3. Ask the database agent
        responses = self.agent.invoke(question)

        async for response in responses:

            assert response is not None

            # 4. Use ChatGPT LLM to evaluate the answer
            evaluator = KernelFunction.from_prompt(
                prompt=f"""
Evaluate the semantic similarity between the expected answer
and the actual response to the given question.

# Guidelines

- The similarity should be assessed on a scale from 0 to 1,
  where 0 indicates no similarity and 1 indicates identical meaning.
- Consider both content accuracy and completeness.
- Do not provide any explanation or additional commentary.

# Steps

1. Compare the Source of Truth with the Second Sentence.
2. Analyze accuracy, completeness, and meaning.
3. Assign a score between 0 and 1.

# Output Format

Return the similarity score as JSON:

{{
    "score": SCORE
}}

## Question:
{question}

## Source of truth:
{expected_answer}

## Second sentence:
{response}
""",
                function_name="evaluate_answer",
                execution_settings=OpenAIChatPromptExecutionSettings(
                    max_tokens=4096,
                    temperature=0.0000000001,
                    top_p=0.0000000001,
                    response_format="json_object",
                ),
            )

            evaluation_result = await self.kernel.invoke(evaluator)

            evaluation = json.loads(str(evaluation_result))

            score = evaluation["score"]

            print(f"\nScore: {score}")
            print(f"Answer: {response}")
            print(f"Expected: {expected_answer}")

            # 5. Require at least 0.8 similarity
            if score < 0.8:
                pytest.fail(
                    f"Answer is not similar enough. Score: {score}"
                )