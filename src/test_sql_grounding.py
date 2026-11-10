import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from semantic_kernel.functions import KernelArguments
from semantic_kernel.prompt_template import HandlebarsPromptTemplate, PromptTemplateConfig

from DatabaseAgent import AgentKernelFactory
from DatabaseAgent.DatabaseAgent import DatabaseKernelAgent
from DatabaseAgent.DatabasePlugin import DatabasePlugin
from DatabaseAgent.DatabasePluginOptions import DatabasePluginOptions
from DatabaseAgent.RewriteQueryResponse import RewriteQueryResponse
from DatabaseAgent.TableDefinationSnippet import TableDefinitionSnippet
from DatabaseAgent.IPromptProvider import AgentPromptConstants


SALES_SQL = """
SELECT
    SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)) AS TotalRevenue,
    COUNT(DISTINCT o.OrderID) AS OrderCount,
    SUM(od.Quantity) AS UnitsSold
FROM Orders AS o
JOIN [Order Details] AS od ON od.OrderID = o.OrderID
WHERE o.OrderDate >= date('now', 'start of month', '-1 month')
  AND o.OrderDate < date('now', 'start of month')
"""


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.test")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "test-deployment")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    ctx = AgentKernelFactory.configure_kernel()
    ctx.connection.close()
    ctx.connection = sqlite3.connect(":memory:")
    ctx.connection.executescript("""
        CREATE TABLE Orders (
            OrderID INTEGER PRIMARY KEY,
            OrderDate DATETIME,
            CustomerID TEXT
        );
        CREATE TABLE [Order Details] (
            OrderID INTEGER REFERENCES Orders(OrderID),
            UnitPrice NUMERIC,
            Quantity INTEGER,
            Discount REAL
        );
    """)
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    ctx.connection.executemany(
        "INSERT INTO Orders VALUES (?, ?, ?)",
        [
            (1, f"{previous_month_start} 00:00:00", "A"),
            (2, f"{month_start} 00:00:00", "B"),
            (3, f"{previous_month_end} 23:59:59", "C"),
        ],
    )
    ctx.connection.executemany(
        "INSERT INTO [Order Details] VALUES (?, ?, ?, ?)",
        [(1, 10, 2, 0.1), (2, 50, 1, 0), (3, 5, 3, 0)],
    )
    try:
        yield ctx
    finally:
        ctx.connection.close()


def make_plugin(ctx, retriever="baseline"):
    return DatabasePlugin(
        prompt_provider=ctx.prompt_provider,
        options=DatabasePluginOptions(retriever=retriever),
        vector_store=ctx.table_store,
        connection=ctx.connection,
        embedding_service=ctx.embedding,
    )


@pytest.mark.asyncio
async def test_optional_live_schema_block_is_not_rendered(context):
    template = HandlebarsPromptTemplate(
        prompt_template_config=PromptTemplateConfig(
            template=context.prompt_provider.read_prompt(AgentPromptConstants.WRITE_SQL_QUERY),
            template_format="handlebars",
            allow_dangerously_set_content=True,
        )
    )
    rendered = await template.render(
        context.kernel,
        KernelArguments(
            providerName="SQLite", tablesDefinition="AI_DESCRIPTION_MARKER",
            databaseSchema="RAW_SCHEMA_MUST_NOT_LEAK", prompt="sales figures",
            currentDate="2026-11-10",
        ),
    )
    assert "AI_DESCRIPTION_MARKER" in rendered
    assert "RAW_SCHEMA_MUST_NOT_LEAK" not in rendered
    assert "AUTHORITATIVE LIVE SCHEMA" not in rendered
    assert "Optional live-schema augmentation" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("with_description", [False, True])
@pytest.mark.parametrize("retriever", ["baseline", "hybrid"])
async def test_sales_query_uses_only_retrieved_descriptions(context, with_description, retriever):
    plugin = make_plugin(context, retriever)
    description = "Sales are stored in Orders and Order Details."
    if with_description:
        await context.table_store.upsert(
            TableDefinitionSnippet(
                table_name="Orders", key=uuid4(), definition="RAW_SCHEMA_MUST_NOT_LEAK",
                description=description,
                text_embedding=await context.embedding.generate("sales figures last month"),
            )
        )
    executed_sql = []
    context.connection.set_trace_callback(executed_sql.append)
    with patch(
        "semantic_kernel.functions.KernelFunctionFromPrompt.invoke",
        new_callable=AsyncMock,
        return_value=json.dumps({"query": SALES_SQL}),
    ) as invoke:
        result = await plugin.execute_query_async(
            context.kernel,
            "Show sales figures for the previous calendar month.",
            "sales figures for last month",
        )
    arguments = invoke.call_args.args[1]
    assert "databaseSchema" not in arguments
    expected = f"{description}\n\n---\n\n" if with_description else ""
    assert arguments["tablesDefinition"] == expected
    assert "RAW_SCHEMA_MUST_NOT_LEAK" not in str(arguments)
    assert not any("sqlite_master" in sql.lower() or "pragma" in sql.lower() for sql in executed_sql)
    assert arguments["currentDate"] == datetime.now(timezone.utc).date().isoformat()
    assert "| 33.0 | 2.0 | 5.0 |" in result
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_sql_corrections_receive_descriptions_and_database_error(context):
    plugin = make_plugin(context)
    invalid_sql = "SELECT Currency FROM Orders"
    with patch(
        "semantic_kernel.functions.KernelFunctionFromPrompt.invoke",
        new_callable=AsyncMock,
        side_effect=[
            json.dumps({"query": invalid_sql}),
            json.dumps({"query": SALES_SQL}),
        ],
    ) as invoke:
        result = await plugin.execute_query_async(
            context.kernel, "sales figures for last month", "sales figures for last month"
        )
    first = invoke.await_args_list[0].args[1]
    correction = invoke.await_args_list[1].args[1]
    assert "databaseSchema" not in first
    assert "databaseSchema" not in correction
    assert correction["tablesDefinition"] == first["tablesDefinition"]
    assert correction["previousAttempt"] == invalid_sql
    assert "no such column: Currency" in correction["previousException"]
    assert "| 33.0 | 2.0 | 5.0 |" in result
    assert invoke.await_count == 2


@pytest.mark.asyncio
async def test_last_month_does_not_fall_back_to_latest_data(context):
    context.connection.execute("UPDATE Orders SET OrderDate = '2000-01-01 12:00:00'")
    plugin = make_plugin(context)
    with patch(
        "semantic_kernel.functions.KernelFunctionFromPrompt.invoke",
        new_callable=AsyncMock,
        return_value=json.dumps({"query": SALES_SQL}),
    ) as invoke:
        result = await plugin.execute_query_async(
            context.kernel, "sales figures for last month", "sales figures for last month"
        )
    assert "| TotalRevenue | OrderCount | UnitsSold |" in result
    assert "| None | 0 | None |" in result
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_rewrite_receives_current_date_and_original_request(context):
    agent = DatabaseKernelAgent(
        kernel=context.kernel, name="TestAgent", description="", instructions="",
        prompt_provider=context.prompt_provider, plugin=make_plugin(context),
    )
    with patch(
        "DatabaseAgent.DatabaseAgent.run_prompt",
        new_callable=AsyncMock,
        return_value=RewriteQueryResponse(
            query="Show sales figures for the previous calendar month.", thinking="Preserved scope."
        ),
    ) as prompt:
        rewritten = await agent.rewrite_query("sales figures for last month")
    assert rewritten == "Show sales figures for the previous calendar month."
    assert prompt.call_args.kwargs["query"] == "sales figures for last month"
    assert prompt.call_args.kwargs["currentDate"] == datetime.now(timezone.utc).date().isoformat()
