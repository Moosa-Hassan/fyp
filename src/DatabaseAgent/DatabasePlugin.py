from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator, Awaitable, Callable, Protocol

from rank_bm25 import BM25Okapi
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.functions import (
    KernelArguments,
    KernelFunctionFromPrompt,
    kernel_function,
)
from semantic_kernel.prompt_template import PromptTemplateConfig

from .DatabasePluginOptions import DatabasePluginOptions
from .Extensions.DBConnectionExtension import DBConnectionExtension
from .Internals.Embeddings import IEmbeddingService
from .Internals.MarkdownRenderer import MarkdownRenderer
from .Internals.PromptRunner import parse_json_model
from .Internals.QueryExecutor import QueryExecutor
from .Internals.RetryHelper import RetryHelper
from .Internals.VectorStore import VectorSearchResult
from .IPromptProvider import AgentPromptConstants, IPromptProvider
from .WriteSQLQueryResponse import WriteSQLQueryResponse


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


class IVectorSearchable(Protocol):
    def search(self, embedding: Any, top: int) -> AsyncIterator[VectorSearchResult]: ...


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|truncate|grant)\b")


class ReadOnlyQueryFilter:
    """Default filter: single read-only statement (SELECT / WITH ... SELECT)."""

    async def on_query_execution(self, context, next_):
        sql = re.sub(r"--.*?$|/\*.*?\*/", "", context.sql_query, flags=re.S | re.M).strip().lower()
        body = sql.rstrip(";").strip()
        if not re.match(r"^\(*\s*(select|with)\b", body) or ";" in body or _FORBIDDEN.search(body):
            return True, "Only a single read-only SELECT statement is allowed."
        return await next_(context)


class DatabasePlugin:
    def __init__(
        self,
        prompt_provider: IPromptProvider,
        options: DatabasePluginOptions,
        vector_store: IVectorSearchable,
        connection: Any,
        embedding_service: IEmbeddingService,
        filters: list[IQueryExecutionFilter] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if options is None:
            raise ValueError("options is required")

        self._options = options
        self._log = logger or logging.getLogger(__name__)
        self._vector_store = vector_store
        self._connection = connection
        self._embedding = embedding_service
        self._filters = filters if filters is not None else [ReadOnlyQueryFilter()]
        self._provider_name = DBConnectionExtension.get_provider_name(connection)

        execution_settings = OpenAIChatPromptExecutionSettings(
            max_completion_tokens=options.max_tokens,
            response_format=WriteSQLQueryResponse,
        )

        self._write_sql_function = KernelFunctionFromPrompt(
            function_name="write_sql_query",
            plugin_name="DatabasePlugin",
            prompt_template_config=PromptTemplateConfig(
                template=prompt_provider.read_prompt(AgentPromptConstants.WRITE_SQL_QUERY),
                template_format="handlebars",
                allow_dangerously_set_content=True,  # keep quotes in schema/SQL unescaped
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
            embedding = await self._embedding.generate(prompt)

            top = min(self._options.top_k * 5, 100)
            related = [r async for r in self._vector_store.search(embedding, top=top)]
            ranked = self._bm25_rank(
                prompt, related, lambda r: r.record.description or "", top_n=self._options.top_k
            )

            table_definitions = "".join(f"{r.record.description}\n\n---\n\n" for r in ranked)

            sql_query = ""

            async def attempt(prev_exc: Exception | None):
                nonlocal sql_query

                sql_query = await self._get_sql_query_string_async(
                    kernel,
                    prompt,
                    table_definitions,
                    previous_sql_query=sql_query,
                    previous_sql_exception=prev_exc,
                )

                if not sql_query or not sql_query.strip():
                    raise RuntimeError("The kernel was unable to generate the expected query.")

                self._log.info("SQL query generated: %s", sql_query)

                ctx = QueryExecutionContext(kernel, original_query, table_definitions, sql_query)
                filtered, message = await self._invoke_filters_or_query(self._filters, _allow_query, ctx)
                if filtered:
                    raise RuntimeError(f"Query execution was filtered: {message}")

                return await QueryExecutor.execute_sql_async(self._connection, sql_query, self._log)

            data_table = await RetryHelper.try_function(attempt, count=3, logger=self._log)

            result = MarkdownRenderer.render(data_table)
            self._log.info("Query result: %s", result)
            return result

        except Exception:
            self._log.exception("Error executing query: %s", prompt)
            raise

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
            previousAttempt=previous_sql_query or "",
            previousException=str(previous_sql_exception) if previous_sql_exception else "",
            providerName=self._provider_name,
        )
        function_result = await self._write_sql_function.invoke(kernel, arguments)
        return parse_json_model(WriteSQLQueryResponse, str(function_result)).query

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

    @staticmethod
    def _bm25_rank(query: str, items: list, text_of: Callable[[Any], str], top_n: int) -> list:
        if not items:
            return []
        corpus = [re.findall(r"\w+", text_of(i).lower()) or [""] for i in items]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(re.findall(r"\w+", query.lower()))
        order = sorted(range(len(items)), key=lambda i: scores[i], reverse=True)
        return [items[i] for i in order[:top_n]]


async def _allow_query(_context: QueryExecutionContext) -> tuple[bool, str]:
    return False, ""  # (filtered, message): nothing filtered