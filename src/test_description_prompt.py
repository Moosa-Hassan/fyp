import pytest
from semantic_kernel import Kernel
from semantic_kernel.functions import KernelArguments
from semantic_kernel.prompt_template import HandlebarsPromptTemplate, PromptTemplateConfig

from DatabaseAgent.ExplainTableResponse import ExplainTableResponse
from DatabaseAgent.Internals.EmbeddedPromptProvider import EmbeddedPromptProvider
from DatabaseAgent.IPromptProvider import AgentPromptConstants


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["SQLite", "MySQL", "PostgreSQL", "Unknown Provider"])
async def test_description_prompt_preserves_supplied_schema_and_samples(provider):
    template = HandlebarsPromptTemplate(
        prompt_template_config=PromptTemplateConfig(
            template=EmbeddedPromptProvider().read_prompt(AgentPromptConstants.EXPLAIN_TABLE),
            template_format="handlebars",
            allow_dangerously_set_content=True,
        )
    )
    name = 'Line Items "Archive"'
    definition = (
        "Order ID INTEGER; Line No INTEGER; ShipRegion TEXT; Payload BLOB\n"
        "PRIMARY KEY (Order ID, Line No)\n"
        "FOREIGN KEY (Order ID) REFERENCES Order Headers(Header ID)"
    )
    sample = "| Order ID | ShipRegion | Payload |\n| 1 | North & West | [binary data: 100 bytes] |"
    rendered = await template.render(
        Kernel(),
        KernelArguments(
            providerName=provider, tableName=name,
            tableDefinition=definition, tableDataExtract=sample,
        ),
    )
    assert f"Provider: {provider}" in rendered
    assert f"Table name:\n{name}" in rendered
    assert definition in rendered
    assert sample in rendered
    assert "{{tableName}}" not in rendered
    assert "{{tableDefinition}}" not in rendered
    assert "{{tableDataExtract}}" not in rendered


def test_description_response_contract_remains_compatible():
    response = ExplainTableResponse.model_validate(
        {
            "tableName": "Line Items",
            "definition": "Inferred: one row represents an order line.",
            "attributes": "- [Order ID] INTEGER\n- [Line No] INTEGER",
            "relations": "No declared relationships provided",
            "recordSample": "No sample rows provided",
        }
    )
    assert response.table_name == "Line Items"
    assert response.record_sample == "No sample rows provided"
    assert set(response.model_dump(by_alias=True)) == {
        "tableName", "definition", "attributes", "relations", "recordSample",
    }
