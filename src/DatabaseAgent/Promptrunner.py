from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel
from semantic_kernel import Kernel
from semantic_kernel.functions import KernelArguments, KernelFunctionFromPrompt
from semantic_kernel.prompt_template import PromptTemplateConfig

from .PromptExecutionSettingsHelper import PromptExecutionSettingsHelper

M = TypeVar("M", bound=BaseModel)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_model(model: type[M], raw: str) -> M:
    """model_validate_json, tolerating ```json fences from models without structured output."""
    return model.model_validate_json(_FENCE.sub("", raw))


async def run_prompt(kernel: Kernel, template: str, response_model: type[M], **arguments) -> M:
    """Render a handlebars prompt, call the chat service with response_format=response_model,
    and parse the reply.

    allow_dangerously_set_content=True is required: SK HTML-encodes template arguments by default,
    which would turn quotes in table definitions / SQL into &quot; / &#x27;.
    """
    fn = KernelFunctionFromPrompt(
        function_name="run_prompt",
        prompt_template_config=PromptTemplateConfig(
            template=template,
            template_format="handlebars",
            allow_dangerously_set_content=True,
            execution_settings=PromptExecutionSettingsHelper.get_prompt_execution_settings(response_model),
        ),
    )
    clean = {k: ("" if v is None else v) for k, v in arguments.items()}
    result = await fn.invoke(kernel, KernelArguments(**clean))
    return parse_json_model(response_model, str(result))