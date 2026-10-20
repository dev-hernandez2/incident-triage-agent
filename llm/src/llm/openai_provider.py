"""Translates the common Message/CompletionResult types to/from the OpenAI SDK.

OpenAI's chat-completions tool schema wraps each tool spec under
{"type": "function", "function": {...}} and expects function call arguments
as a JSON string, not a dict — both differ from the common ToolSpec shape
and from Anthropic's wire format, so this adapter converts both directions.
"""

import json
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


class _OpenAIClientProtocol(Protocol):
    @property
    def chat(self) -> Any: ...


class OpenAIProvider:
    def __init__(
        self,
        client: _OpenAIClientProtocol,
        model: str = "gpt-5.6-luna",
        max_tokens: int = 4096,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def _to_openai_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        translated: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, UserMessage):
                translated.append({"role": "user", "content": message.text})
            elif isinstance(message, AssistantMessage):
                entry: dict[str, Any] = {"role": "assistant", "content": message.text}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": json.dumps(call.args)},
                        }
                        for call in message.tool_calls
                    ]
                translated.append(entry)
            elif isinstance(message, ToolResultMessage):
                translated.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
        return translated

    def _to_openai_tools(self, tools: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in tools
        ]

    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "system", "content": system}, *self._to_openai_messages(messages)],
            tools=self._to_openai_tools(tools),
        )

        choice = response.choices[0]
        tool_calls = [
            ToolCallRequest(
                id=call.id, name=call.function.name, args=json.loads(call.function.arguments)
            )
            for call in (choice.message.tool_calls or [])
        ]

        return CompletionResult(
            text=choice.message.content,
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            ),
            stop_reason=choice.finish_reason,
        )
