"""Validate only explicitly adapted structures; native extensions remain intact."""
from typing import Any, Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


Adaptation = Literal['custom_tools', 'agent_messages', 'standalone_outputs', 'discovered_tools']


class AdaptationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)
    adaptations: list[Adaptation] = Field(default_factory=list)

    @field_validator('adaptations')
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Duplicate adaptation')
        return value


class NativeItem(BaseModel):
    # Validate known fields without removing future protocol extensions.
    model_config = ConfigDict(extra='allow', strict=True, hide_input_in_errors=True)


class InputText(NativeItem):
    type: Literal['input_text']
    text: str


def host_plaintext(value):
    """Recognize readable host spans; do not interpret opaque tokens as plaintext."""
    if not isinstance(value, str) or not value or value.startswith('gAAAA'):
        return False
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-\d+', value):
        return False
    return any(c.isspace() or ord(c) > 127 for c in value) or value.lstrip().startswith(('<', '{', '['))


class AgentMessage(NativeItem):
    type: Literal['agent_message']
    content: list[InputText] = Field(min_length=1)

    @field_validator('content', mode='before')
    @classmethod
    def readable_host_spans(cls, value):
        if not isinstance(value, list):
            return value
        result = []
        for part in value:
            if isinstance(part, dict) and part.get('type') == 'encrypted_content':
                text = part.get('encrypted_content')
                if not host_plaintext(text):
                    raise ValueError('Opaque agent content is not supported')
                part = {k:v for k,v in part.items() if k not in {'type','encrypted_content'}}
                part.update(type='input_text', text=text)
            result.append(part)
        return result


class StandaloneOutput(NativeItem):
    type: Literal['function_call_output', 'custom_tool_call_output']
    name: str = Field(min_length=1)
    namespace: str | None = None
    call_id: None = None
    output: Any


class CustomTool(NativeItem):
    type: Literal['custom']
    name: str = Field(min_length=1)
    description: str = ''
    format: dict[str, Any] | None = None


class CustomCall(NativeItem):
    type: Literal['custom_tool_call']
    name: str = Field(min_length=1)
    namespace: str | None = None
    call_id: str = Field(min_length=1)
    input: str


class CustomArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)
    input: str
