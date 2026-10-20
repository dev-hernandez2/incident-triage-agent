"""Translates the common Message/CompletionResult types to/from the Anthropic SDK."""

from typing import Any, Protocol

from llm.types import (
    AssistantMessage,
    CompletionResult,
    Message,
    ToolCallRequest,
    ToolResultMessage,
    Usage,
    UserMessage,
)


class _AnthropicClientProtocol(Protocol):
    @property
    def messages(self) -> Any: ...


class AnthropicProvider:
    def __init__(
        self,
        client: _AnthropicClientProtocol,
        model: str = "claude-haiku-5-5",
        max_tokens: int = 4096,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        translated: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, UserMessage):
                translated.append({"role": "user", "content": message.text})
            elif isinstance(message, AssistantMessage):
                content: list[dict[str, Any]] = []
                if message.text is not None:
                    content.append({"type": "text", "text": message.text})
                for call in message.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.args}
                    )
                translated.append({"role": "assistant", "content": content})
            elif isinstance(message, ToolResultMessage):
                translated.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
        return translated

    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=self._to_anthropic_messages(messages),
            tools=tools,
        )

        text: str | None = None
        tool_calls: list[ToolCallRequest] = []
        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(id=block.id, name=block.name, args=block.input))

        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
        )
