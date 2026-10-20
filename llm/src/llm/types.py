"""Provider-agnostic types shared by the Anthropic/OpenAI adapters and the agent loop."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    args: dict[str, object]


@dataclass(frozen=True)
class CompletionResult:
    text: str | None
    tool_calls: list[ToolCallRequest]
    usage: Usage
    stop_reason: str


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResultMessage:
    tool_call_id: str
    content: str


Message = UserMessage | AssistantMessage | ToolResultMessage
