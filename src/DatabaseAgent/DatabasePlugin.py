from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator, Awaitable, Callable, Protocol

import pandas as pd
from rank_bm25 import BM25Okapi
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.embedding_generator_base import EmbeddingGeneratorBase
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.functions import (
    KernelArguments,
    KernelFunctionFromPrompt,
    kernel_function,
)
from semantic_kernel.prompt_template import PromptTemplateConfig

from .DatabasePluginOptions import DatabasePluginOptions
from .IPromptProvider import IPromptProvider
from .TableDefinationSnippet import TableDefinitionSnippet
from .WriteSQLQueryResponse import WriteSQLQueryResponse

WRITE_SQL_QUERY_PROMPT = "WriteSQLQuery"  # AgentPromptConstants.WriteSQLQuery


# --------------------------------------------------------------------------- #
# Small supporting types (C# had these in other namespaces/files)
# --------------------------------------------------------------------------- #
@dataclass
class QueryExecutionContext:
    kernel: Kernel
    original_query: str
    table_definitions: str
    sql_query: str


class IQueryExecutionFilter(Protocol):
    async def on_query_execution(
        self,
        context: QueryExecutionContext,
        next_: Callable[[QueryExecutionContext], Awaitable[tuple[bool, str]]],
    ) -> tuple[bool, str]: ...


@dataclass
class VectorSearchResult:
    record: TableDefinitionSnippet
    score: float | None = None


class IVectorSearchable(Protocol):
    def search(self, embedding: Any, top: int) -> AsyncIterator[VectorSearchResult]: ...


async def retry_try(
    func: Callable[[Exception | None], Awaitable[Any]],
    count: int,
    log: logging.Logger,
) -> Any:
    """Equivalent of RetryHelper.Try: retries, feeding the last exception back in."""
    last_exc: Exception | None = None
    for attempt in range(1, count + 1):
        try:
            return await func(last_exc)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            last_exc = e
            log.warning("Attempt %d/%d failed: %s", attempt, count, e)
    assert last_exc is not None
    raise last_exc


def get_provider_name(connection: Any) -> str:
    """Rough equivalent of DbConnection.GetProviderName()."""
    return type(connection).__module__.split(".")[0]  # e.g. 'sqlite3', 'psycopg2', 'pyodbc'


async def execute_sql(connection: Any, sql: str) -> pd.DataFrame:
    """Equivalent of QueryExecutor.ExecuteSQLAsync (DB-API / SQLAlchemy connection)."""
    return await asyncio.to_thread(pd.read_sql_query, sql, connection)


def render_markdown(df: pd.DataFrame) -> str:
    """Equivalent of MarkdownRenderer.Render."""
    return df.to_markdown(index=False)


# --------------------------------------------------------------------------- #
# The plugin
# --------------------------------------------------------------------------- #
class DatabasePlugin:
    def __init__(
        self,
        prompt_provider: IPromptProvider,
        options: DatabasePluginOptions,
        vector_store: IVectorSearchable,
        connection: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        if options is None:
            raise ValueError("options is required")

        self._options = options
        self._log = logger or logging.getLogger(__name__)
        self._vector_store = vector_store
        self._connection = connection

        execution_settings = OpenAIChatPromptExecutionSettings(
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            top_p=options.top_p,
            seed=0,
            response_format=WriteSQLQueryResponse,  
        )

        self._write_sql_function = KernelFunctionFromPrompt(
            function_name="write_sql_query",
            plugin_name="DatabasePlugin",
            prompt_template_config=PromptTemplateConfig(
                template=prompt_provider.read_prompt(WRITE_SQL_QUERY_PROMPT),
                template_format="handlebars",
                execution_settings=execution_settings,
            ),
        )

    @kernel_function(
        name="execute_query",
        description=(
            "Execute a query into the database. "
            "The query should be formulate in natural language. "
            "No worry about the schema, I'll look for you in the database."
        ),
    )
    async def execute_query_async(
        self,
        kernel: Kernel,
        prompt: Annotated[str, "The user query in natural language."],
        original_query: Annotated[str, "The original query, used for debugging purposes."],
    ) -> Annotated[str, "A Markdown representation of the query result."]:
        try:
            embedding_service = kernel.get_service(type=EmbeddingGeneratorBase)
            embeddings = (await embedding_service.generate_embeddings([prompt]))[0]

            top = min(self._options.top_k * 5, 100)
            related = [r async for r in self._vector_store.search(embeddings, top=top)]
            ranked = self._bm25_rank(prompt, related, lambda r: r.record.description,
                                     top_n=self._options.top_k)

            table_definitions = "".join(
                f"{r.record.description}\n\n---\n\n" for r in ranked
            )

            sql_query = ""

            async def attempt(prev_exc: Exception | None) -> pd.DataFrame:
                nonlocal sql_query

                sql_query = await self._get_sql_query_string_async(
                    kernel,
                    prompt,
                    table_definitions,
                    previous_sql_query=sql_query,
                    previous_sql_exception=prev_exc,
                )

                if not sql_query or not sql_query.strip():
                    self._log.warning("SQL query is empty for prompt: %s", prompt)
                    raise RuntimeError("The kernel was unable to generate the expected query.")

                self._log.info("SQL query generated: %s", sql_query)

                ctx = QueryExecutionContext(kernel, original_query, table_definitions, sql_query)
                filters = self._get_filters(kernel)

                filtered, message = await self._invoke_filters_or_query(
                    filters,
                    _allow_query,
                    ctx,
                )
                if filtered:
                    raise RuntimeError(f"Query execution was filtered: {message}")

                return await execute_sql(self._connection, sql_query)

            data_table = await retry_try(attempt, count=3, log=self._log)

            result = render_markdown(data_table)
            self._log.info("Query result: %s", result)
            return result

        except Exception:
            self._log.exception("Error executing query: %s", prompt)
            raise

    # ------------------------------------------------------------------ #
    async def _get_sql_query_string_async(
        self,
        kernel: Kernel,
        prompt: str,
        tables_definitions: str,
        previous_sql_query: str | None = None,
        previous_sql_exception: Exception | None = None,
    ) -> str | None:
        arguments = KernelArguments(
            prompt=prompt,
            tablesDefinition=tables_definitions,
            previousAttempt=previous_sql_query,
            previousException=str(previous_sql_exception) if previous_sql_exception else None,
            providerName=get_provider_name(self._connection),
        )

        self._log.info("Write SQL query for: %s", prompt)

        function_result = await self._write_sql_function.invoke(kernel, arguments)
        raw = str(function_result)
        return WriteSQLQueryResponse.model_validate_json(raw).query

    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_filters(kernel: Kernel) -> list[IQueryExecutionFilter]:
        """Equivalent of kernel.GetAllServices<IQueryExecutionFilter>().
        Python SK has no generic 'get all services by type', so we scan them."""
        return [s for s in kernel.services.values() if hasattr(s, "on_query_execution")]

    @classmethod
    async def _invoke_filters_or_query(
        cls,
        filters: list[IQueryExecutionFilter] | None,
        callback: Callable[[QueryExecutionContext], Awaitable[tuple[bool, str]]],
        context: QueryExecutionContext,
        index: int = 0,
    ) -> tuple[bool, str]:
        if filters and index < len(filters):
            return await filters[index].on_query_execution(
                context,
                lambda ctx: cls._invoke_filters_or_query(filters, callback, ctx, index + 1),
            )
        return await callback(context)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _bm25_rank(query: str, items: list, text_of: Callable[[Any], str], top_n: int) -> list:
        """Equivalent of BM25Reranker.RankAsync (English tokenisation only)."""
        if not items:
            return []
        corpus = [text_of(i).lower().split() for i in items]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query.lower().split())
        order = sorted(range(len(items)), key=lambda i: scores[i], reverse=True)
        return [items[i] for i in order[:top_n]]


async def _allow_query(_context: QueryExecutionContext) -> tuple[bool, str]:
    _ = _context
    return False, ""