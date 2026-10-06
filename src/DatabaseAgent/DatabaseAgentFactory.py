from uuid import UUID, uuid4

from semantic_kernel import Kernel

from .AgentDefinationSnippit import AgentDefinitionSnippet
from .AgentDescriptionResponse import AgentDescriptionResponse
from .AgentInstructionsResponse import AgentInstructionsResponse
from .AgentNameResponse import AgentNameResponse
from .ExplainTableResponse import ExplainTableResponse
from .ExtractTableNameResponse import ExtractTableNameResponse
from .TableDefinationSnippet import TableDefinitionSnippet
from .WriteSQLQueryResponse import WriteSQLQueryResponse
from .DatabaseAgent import DatabaseKernelAgent
from .DatabasePlugin import DatabasePlugin, get_provider_name
from .DatabasePluginOptions import DatabasePluginOptions
from .Internals.MarkdownRenderer import MarkdownRenderer
from .Internals.QueryExecutor import QueryExecutor
from .IPromptProvider import AgentPromptConstants

class DatabaseAgentFactory:
    """
    Builds a DatabaseKernelAgent.

    Main responsibilities:

    1. Look for an existing agent definition.
    2. If found, reuse it.
    3. Otherwise memorize the database schema.
    4. Generate the agent's name, description, and instructions.
    5. Store the agent definition.
    6. Return a configured DatabaseKernelAgent.
    """

    @staticmethod
    async def create_agent(
        kernel: Kernel,
        name: str | None = None,
        update: bool = False,
        options: DatabasePluginOptions | None = None,
    ):
        """
        Create or load a database agent.

        Args:
            kernel: Semantic Kernel instance.
            name: Optional agent name.
            update: Whether existing table definitions should
                    be regenerated.
        """

        # ---------------------------------------------------------
        # 1. Get the vector stores
        # ---------------------------------------------------------

        table_store = kernel.get_service(
            "table_definition_store"
        )

        if table_store is None:
            raise RuntimeError(
                "Kernel does not have a table definition vector store."
            )

        agent_store = kernel.get_service(
            "agent_definition_store"
        )

        if agent_store is None:
            raise RuntimeError(
                "Kernel does not have an agent definition vector store."
            )

        # ---------------------------------------------------------
        # 2. Make sure collections exist
        # ---------------------------------------------------------

        await table_store.ensure_collection()

        await agent_store.ensure_collection()

        # ---------------------------------------------------------
        # 3. Try to find an existing agent
        # ---------------------------------------------------------

        existing_definition = None

        if name:
            # Named agent
            existing_definition = await agent_store.get_by_name(
                name
            )
        else:
            # Default agent
            existing_definition = await agent_store.get(
                UUID(int=0)
            )

        # ---------------------------------------------------------
        # 4. Reuse existing agent
        # ---------------------------------------------------------

        if existing_definition is not None:

            return DatabaseKernelAgent(
                kernel=kernel,
                name=existing_definition.agent_name,
                description=existing_definition.description,
                instructions=existing_definition.instructions,
                prompt_provider=prompt_provider,
                plugin=plugin,
            )

        # ---------------------------------------------------------
        # 5. No agent exists → learn the database
        # ---------------------------------------------------------

        table_descriptions = await DatabaseAgentFactory.memorize_schema(
            kernel=kernel,
            table_store=table_store,
            update=update,
        )

        # ---------------------------------------------------------
        # 6. Get prompt provider
        # ---------------------------------------------------------

        prompt_provider = kernel.get_service(
            "prompt_provider"
        )
        if prompt_provider is None:
            raise RuntimeError("Kernel does not have a prompt provider.")

        connection = kernel.get_service("db_connection")
        if connection is None:
            raise RuntimeError("Kernel does not have a database connection.")

        plugin = DatabasePlugin(
            prompt_provider=prompt_provider,
            options=options or DatabasePluginOptions(),
            vector_store=table_store,
            connection=connection,
        )

        # ---------------------------------------------------------
        # 7. Generate agent description
        # ---------------------------------------------------------

        description_result = await kernel.invoke_prompt(
            prompt_provider.read_prompt(
                AgentPromptConstants.AGENT_DESCRIPTION_GENERATOR
            ),
            arguments={
                "tableDefinitions": table_descriptions,
                "expectedName": name or "",
            },
        )

        description_response = (
            AgentDescriptionResponse.model_validate_json(
                str(description_result)
            )
        )

        # ---------------------------------------------------------
        # 8. Generate agent name if one wasn't provided
        # ---------------------------------------------------------

        if name is None:

            name_result = await kernel.invoke_prompt(
                prompt_provider.read_prompt(
                    AgentPromptConstants.AGENT_NAME_GENERATOR
                ),
                arguments={
                    "agentDescription":
                        description_response.description
                },
            )

            name_response = AgentNameResponse.model_validate_json(
                str(name_result)
            )

            agent_name = name_response.name

        else:
            agent_name = name

        # ---------------------------------------------------------
        # 9. Generate agent instructions
        # ---------------------------------------------------------

        instructions_result = await kernel.invoke_prompt(
            prompt_provider.read_prompt(
                AgentPromptConstants.AGENT_INSTRUCTIONS_GENERATOR
            ),
            arguments={
                "agentDescription":
                    description_response.description
            },
        )

        instructions_response = (
            AgentInstructionsResponse.model_validate_json(
                str(instructions_result)
            )
        )

        # ---------------------------------------------------------
        # 10. Create agent definition
        # ---------------------------------------------------------

        agent_definition = AgentDefinitionSnippet(
            agent_name=agent_name,
            key=UUID(int=0),
            description=description_response.description,
            instructions=instructions_response.instructions,
            text_embedding=None,
        )

        # ---------------------------------------------------------
        # 11. Embed the agent description
        # ---------------------------------------------------------

        embedding_service = kernel.get_service(
            "embedding_service"
        )

        agent_definition.text_embedding = (
            await embedding_service.generate(
                agent_definition.description
            )
        )

        # ---------------------------------------------------------
        # 12. Store the agent definition
        # ---------------------------------------------------------

        await agent_store.upsert(
            agent_definition
        )

        # ---------------------------------------------------------
        # 13. Return the agent
        # ---------------------------------------------------------

        return DatabaseKernelAgent(
            kernel=kernel,
            name=agent_definition.agent_name,
            description=agent_definition.description,
            instructions=agent_definition.instructions,
            prompt_provider=prompt_provider,
            plugin=plugin,
        )

    # =============================================================
    # SCHEMA MEMORIZATION
    # =============================================================

    @staticmethod
    async def memorize_schema(
        kernel: Kernel,
        table_store,
        update: bool = False,
    ) -> str:
        """
        Discover the database schema and create searchable
        descriptions for the tables.
        """

        descriptions = []

        # First discover all tables.
        tables = DatabaseAgentFactory.get_tables(kernel)

        # Then build a description for every table.
        async for table in DatabaseAgentFactory.get_table_descriptions(
            kernel=kernel,
            tables=tables,
            table_store=table_store,
            update=update,
        ):
            descriptions.append(
                table.description
            )

        return "\n".join(descriptions)

    # =============================================================
    # GET TABLES
    # =============================================================

    @staticmethod
    async def get_tables(
        kernel: Kernel,
    ):
        """
        Ask the LLM to generate SQL that lists all tables,
        execute it, and yield each table.
        """

        connection = kernel.get_service(
            "db_connection"
        )

        prompt_provider = kernel.get_service(
            "prompt_provider"
        )

        sql_prompt = prompt_provider.read_prompt(
            AgentPromptConstants.WRITE_SQL_QUERY
        )

        previous_sql = ""
        previous_exception = None

        # Retry table discovery.
        for attempt in range(3):

            try:

                result = await kernel.invoke_prompt(
                    sql_prompt,
                    arguments={
                        "prompt": "List all tables",
                        "providerName":
                            get_provider_name(connection),
                        "tablesDefinitions": "",
                        "previousAttempt": previous_sql,
                        "previousException":
                            str(previous_exception)
                            if previous_exception
                            else "",
                    },
                )

                response = (
                    WriteSQLQueryResponse
                    .model_validate_json(str(result))
                )

                previous_sql = response.query

                table_data = await QueryExecutor.execute_sql_async(
                    connection,
                    previous_sql,
                )

                for _, row in table_data.iterrows():
                    yield MarkdownRenderer.render(
                        row
                    )

                return

            except Exception as exc:

                previous_exception = exc

                if attempt == 2:
                    raise

    # =============================================================
    # GET TABLE DESCRIPTIONS
    # =============================================================

    @staticmethod
    async def get_table_descriptions(
        kernel: Kernel,
        tables,
        table_store,
        update: bool = False,
    ):
        """
        For every database table:

        1. Extract its table name.
        2. Check whether we already have its definition.
        3. If cached and update=False, reuse it.
        4. Otherwise:
             - get column information
             - get first 5 rows
             - ask LLM to explain the table
             - embed description
             - store it
        """

        connection = kernel.get_service(
            "db_connection"
        )

        prompt_provider = kernel.get_service(
            "prompt_provider"
        )

        embedding_service = kernel.get_service(
            "embedding_service"
        )

        sql_prompt = prompt_provider.read_prompt(
            AgentPromptConstants.WRITE_SQL_QUERY
        )

        extract_table_prompt = prompt_provider.read_prompt(
            AgentPromptConstants.EXTRACT_TABLE_NAME
        )

        explain_table_prompt = prompt_provider.read_prompt(
            AgentPromptConstants.EXPLAIN_TABLE
        )

        async for item in tables:

            # -----------------------------------------------------
            # 1. Extract table name
            # -----------------------------------------------------

            table_name_result = await kernel.invoke_prompt(
                extract_table_prompt,
                arguments={
                    "providerName":
                        get_provider_name(connection),
                    "item": item,
                },
            )

            table_name_response = (
                ExtractTableNameResponse
                .model_validate_json(
                    str(table_name_result)
                )
            )

            table_name = table_name_response.table_name

            if not table_name:
                raise RuntimeError(
                    "Failed to extract table name."
                )

            # -----------------------------------------------------
            # 2. Search existing table definitions
            # -----------------------------------------------------

            embedding = await embedding_service.generate(
                item
            )

            existing_results = await table_store.search(
                embedding,
                top=10,
            )

            existing_record = None

            for result in existing_results:

                if result.table_name == table_name:
                    existing_record = result
                    break

            # -----------------------------------------------------
            # 3. Reuse cached definition
            # -----------------------------------------------------

            if existing_record is not None and not update:

                yield existing_record

                continue

            # -----------------------------------------------------
            # 4. Create new record if necessary
            # -----------------------------------------------------

            if existing_record is None:

                table_record = TableDefinitionSnippet(
                    table_name=table_name,
                    key=uuid4(),
                )

            else:

                table_record = existing_record

            # -----------------------------------------------------
            # 5. Get table structure
            # -----------------------------------------------------

            previous_sql = ""
            previous_exception = None

            for attempt in range(3):

                try:

                    definition_result = (
                        await kernel.invoke_prompt(
                            sql_prompt,
                            arguments={
                                "providerName":
                                    get_provider_name(connection),

                                "prompt": (
                                    "Extract the structure of table "
                                    f"{table_name} by listing the "
                                    "column attributes, including "
                                    "the column name, data type, "
                                    "maximum length, and default value."
                                ),

                                "previousAttempt":
                                    previous_sql,

                                "previousException":
                                    str(previous_exception)
                                    if previous_exception
                                    else "",
                            },
                        )
                    )

                    definition_response = (
                        WriteSQLQueryResponse
                        .model_validate_json(
                            str(definition_result)
                        )
                    )

                    previous_sql = (
                        definition_response.query
                    )

                    table_definition = (
                        await QueryExecutor.execute_sql_async(
                            connection,
                            previous_sql,
                        )
                    )

                    table_definition = (
                        MarkdownRenderer.render(
                            table_definition
                        )
                    )

                    break

                except Exception as exc:

                    previous_exception = exc

                    if attempt == 2:
                        raise

            # -----------------------------------------------------
            # 6. Get first five rows
            # -----------------------------------------------------

            previous_sql = ""
            previous_exception = None

            for attempt in range(3):

                try:

                    extract_result = (
                        await kernel.invoke_prompt(
                            sql_prompt,
                            arguments={
                                "providerName":
                                    get_provider_name(connection),

                                "prompt":
                                    f"Get the first 5 rows for "
                                    f"'{table_name}'",

                                "tablesDefinition":
                                    table_definition,

                                "previousAttempt":
                                    previous_sql,

                                "previousException":
                                    str(previous_exception)
                                    if previous_exception
                                    else "",
                            },
                        )
                    )

                    extract_response = (
                        WriteSQLQueryResponse
                        .model_validate_json(
                            str(extract_result)
                        )
                    )

                    previous_sql = extract_response.query

                    table_extract = (
                        await QueryExecutor.execute_sql_async(
                            connection,
                            previous_sql,
                        )
                    )

                    table_extract = (
                        MarkdownRenderer.render(
                            table_extract
                        )
                    )

                    break

                except Exception as exc:

                    previous_exception = exc

                    if attempt == 2:
                        raise

            # -----------------------------------------------------
            # 7. Ask LLM to explain the table
            # -----------------------------------------------------

            explanation_result = (
                await kernel.invoke_prompt(
                    explain_table_prompt,
                    arguments={
                        "providerName":
                            get_provider_name(connection),

                        "tableName":
                            table_name,

                        "tableDefinition":
                            table_definition,

                        "tableDataExtract":
                            table_extract,
                    },
                )
            )

            explanation = (
                ExplainTableResponse
                .model_validate_json(
                    str(explanation_result)
                )
            )

            # -----------------------------------------------------
            # 8. Construct searchable description
            # -----------------------------------------------------

            description = f"""
            ### {table_name}

            {explanation.definition}

            #### Attributes

            {explanation.attributes}

            #### Relations

            {explanation.relations}
            """

            # -----------------------------------------------------
            # 9. Save table information
            # -----------------------------------------------------

            table_record.definition = table_definition

            table_record.description = description

            table_record.sample_data = table_extract

            table_record.text_embedding = (
                await embedding_service.generate(
                    description
                )
            )

            # -----------------------------------------------------
            # 10. Store in vector database
            # -----------------------------------------------------

            await table_store.upsert(
                table_record
            )

            yield table_record
