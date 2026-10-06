from __future__ import annotations

from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pandas as pd

from .AgentContext import AgentContext
from .AgentDefinationSnippit import AgentDefinitionSnippet
from .AgentDescriptionResponse import AgentDescriptionResponse
from .AgentInstructionsResponse import AgentInstructionsResponse
from .AgentNameResponse import AgentNameResponse
from .DatabaseAgent import DatabaseKernelAgent
from .DatabasePlugin import DatabasePlugin
from .DatabasePluginOptions import DatabasePluginOptions
from .ExplainTableResponse import ExplainTableResponse
from .ExtractTableNameResponse import ExtractTableNameResponse
from .Extensions.DBConnectionExtension import DBConnectionExtension
from .Internals.MarkdownRenderer import MarkdownRenderer
from .Internals.PromptRunner import run_prompt
from .Internals.QueryExecutor import QueryExecutor
from .IPromptProvider import AgentPromptConstants
from .TableDefinationSnippet import TableDefinitionSnippet
from .WriteSQLQueryResponse import WriteSQLQueryResponse


class DatabaseAgentFactory:
    """
    1. Reuse a stored agent definition (unless update=True).
    2. Otherwise memorize the schema (one description per table, stored with an embedding).
    3. Generate the agent's description, name and instructions; store them.
    4. Return a configured DatabaseKernelAgent.
    """

    @staticmethod
    async def create_agent(
        ctx: AgentContext,
        name: str | None = None,
        update: bool = False,
        options: DatabasePluginOptions | None = None,
    ) -> DatabaseKernelAgent:
        await ctx.table_store.ensure_collection()
        await ctx.agent_store.ensure_collection()

        plugin = DatabasePlugin(
            prompt_provider=ctx.prompt_provider,
            options=options or DatabasePluginOptions(),
            vector_store=ctx.table_store,
            connection=ctx.connection,
            embedding_service=ctx.embedding,
            logger=ctx.logger,
        )

        agent_key = uuid5(NAMESPACE_DNS, name) if name else UUID(int=0)

        existing = await ctx.agent_store.get(agent_key)
        if existing is not None and not update:
            return DatabaseKernelAgent(
                kernel=ctx.kernel,
                name=existing.agent_name,
                description=existing.description,
                instructions=existing.instructions,
                prompt_provider=ctx.prompt_provider,
                plugin=plugin,
            )

        table_descriptions = await DatabaseAgentFactory.memorize_schema(ctx, update=update)

        pp = ctx.prompt_provider

        description = await run_prompt(
            ctx.kernel,
            pp.read_prompt(AgentPromptConstants.AGENT_DESCRIPTION_GENERATOR),
            AgentDescriptionResponse,
            tableDefinitions=table_descriptions,
            expectedName=name or "",
        )

        if name is None:
            name_response = await run_prompt(
                ctx.kernel,
                pp.read_prompt(AgentPromptConstants.AGENT_NAME_GENERATOR),
                AgentNameResponse,
                agentDescription=description.description,
            )
            agent_name = name_response.name
        else:
            agent_name = name

        instructions = await run_prompt(
            ctx.kernel,
            pp.read_prompt(AgentPromptConstants.AGENT_INSTRUCTIONS_GENERATOR),
            AgentInstructionsResponse,
            agentDescription=description.description,
        )

        definition = AgentDefinitionSnippet(
            agent_name=agent_name,
            key=agent_key,
            description=description.description,
            instructions=instructions.instructions,
            text_embedding=await ctx.embedding.generate(description.description),
        )
        await ctx.agent_store.upsert(definition)

        return DatabaseKernelAgent(
            kernel=ctx.kernel,
            name=definition.agent_name,
            description=definition.description,
            instructions=definition.instructions,
            prompt_provider=ctx.prompt_provider,
            plugin=plugin,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    async def memorize_schema(ctx: AgentContext, update: bool = False) -> str:
        descriptions = []
        for table_name in await DatabaseAgentFactory.get_table_names(ctx):
            record = await DatabaseAgentFactory.describe_table(ctx, table_name, update)
            descriptions.append(record.description)
        return "\n".join(descriptions)

    # ------------------------------------------------------------------ #
    @staticmethod
    async def _run_sql(ctx: AgentContext, nl_prompt: str, tables_definition: str = "") -> pd.DataFrame:
        """LLM writes the SQL, we run it, failures are fed back (3 attempts)."""
        sql_prompt = ctx.prompt_provider.read_prompt(AgentPromptConstants.WRITE_SQL_QUERY)
        provider = DBConnectionExtension.get_provider_name(ctx.connection)
        previous_sql, previous_exc = "", None

        for attempt in range(3):
            try:
                response = await run_prompt(
                    ctx.kernel,
                    sql_prompt,
                    WriteSQLQueryResponse,
                    providerName=provider,
                    prompt=nl_prompt,
                    tablesDefinition=tables_definition,
                    previousAttempt=previous_sql,
                    previousException=str(previous_exc) if previous_exc else "",
                )
                previous_sql = response.query
                return await QueryExecutor.execute_sql_async(ctx.connection, previous_sql, ctx.logger)
            except Exception as exc:  # noqa: BLE001
                previous_exc = exc
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    @staticmethod
    async def get_table_names(ctx: AgentContext) -> list[str]:
        provider = DBConnectionExtension.get_provider_name(ctx.connection)

        # SQLite: introspect directly, no LLM needed.
        if provider == "SQLite":
            df = await QueryExecutor.execute_sql_async(
                ctx.connection,
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
                ctx.logger,
            )
            return [f"[{n}]" for n in df["name"]]

        # Other providers: LLM writes the listing query, then formats each name.
        df = await DatabaseAgentFactory._run_sql(ctx, "List all tables")
        extract_prompt = ctx.prompt_provider.read_prompt(AgentPromptConstants.EXTRACT_TABLE_NAME)
        names = []
        for _, row in df.iterrows():
            resp = await run_prompt(
                ctx.kernel,
                extract_prompt,
                ExtractTableNameResponse,
                providerName=provider,
                item=MarkdownRenderer.render(row),
            )
            if not resp.table_name:
                raise RuntimeError("Failed to extract table name.")
            names.append(resp.table_name)
        return names

    @staticmethod
    async def _get_structure_and_sample(ctx: AgentContext, table_name: str) -> tuple[str, str]:
        provider = DBConnectionExtension.get_provider_name(ctx.connection)

        if provider == "SQLite":
            cols = await QueryExecutor.execute_sql_async(
                ctx.connection, f"PRAGMA table_info({table_name})", ctx.logger
            )
            definition = MarkdownRenderer.render(cols)
            fks = await QueryExecutor.execute_sql_async(
                ctx.connection, f"PRAGMA foreign_key_list({table_name})", ctx.logger
            )
            if len(fks):
                definition += "\n\nForeign keys:\n" + MarkdownRenderer.render(fks)
            sample = await QueryExecutor.execute_sql_async(
                ctx.connection, f"SELECT * FROM {table_name} LIMIT 5", ctx.logger
            )
            return definition, MarkdownRenderer.render(sample)

        definition = MarkdownRenderer.render(
            await DatabaseAgentFactory._run_sql(
                ctx,
                f"Extract the structure of table {table_name} by listing the column attributes, "
                "including the column name, data type, maximum length, and default value.",
            )
        )
        sample = MarkdownRenderer.render(
            await DatabaseAgentFactory._run_sql(
                ctx, f"Get the first 5 rows for '{table_name}'", tables_definition=definition
            )
        )
        return definition, sample

    @staticmethod
    async def describe_table(ctx: AgentContext, table_name: str, update: bool) -> TableDefinitionSnippet:
        existing = await ctx.table_store.find(table_name=table_name)
        if existing is not None and not update:
            return existing

        record = existing or TableDefinitionSnippet(table_name=table_name, key=uuid4())

        definition, sample = await DatabaseAgentFactory._get_structure_and_sample(ctx, table_name)

        explanation = await run_prompt(
            ctx.kernel,
            ctx.prompt_provider.read_prompt(AgentPromptConstants.EXPLAIN_TABLE),
            ExplainTableResponse,
            providerName=DBConnectionExtension.get_provider_name(ctx.connection),
            tableName=table_name,
            tableDefinition=definition,
            tableDataExtract=sample,
        )

        description = "\n\n".join(
            [
                f"### {table_name}",
                explanation.definition,
                "#### Attributes",
                explanation.attributes,
                "#### Relations",
                explanation.relations,
            ]
        ) + "\n"
        record.definition = definition
        record.description = description
        record.sample_data = sample
        record.text_embedding = await ctx.embedding.generate(description)

        await ctx.table_store.upsert(record)
        return record