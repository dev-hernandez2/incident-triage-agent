from typing import Any

from llm.anthropic_provider import AnthropicProvider
from llm.types import AssistantMessage, Message, ToolCallRequest, ToolResultMessage, UserMessage


class _FakeContentBlock:
    def __init__(self, type_: str, **kwargs: Any) -> None:
        self.type = type_
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeAnthropicResponse:
    def __init__(self, content: list[_FakeContentBlock], stop_reason: str, usage: Any) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessagesApi:
    def __init__(self, response: _FakeAnthropicResponse) -> None:
        self._response = response
        self.last_call_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeAnthropicResponse:
        self.last_call_kwargs = kwargs
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: _FakeAnthropicResponse) -> None:
        self.messages = _FakeMessagesApi(response)


def test_to_anthropic_messages_translates_each_message_kind() -> None:
    provider = AnthropicProvider(
        client=_FakeAnthropicClient(_FakeAnthropicResponse([], "end_turn", _FakeUsage(0, 0)))
    )
    messages: list[Message] = [
        UserMessage(text="<alert>boom</alert>"),
        AssistantMessage(
            text="checking pods",
            tool_calls=[
                ToolCallRequest(id="call_1", name="list_pods", args={"namespace": "boutique"})
            ],
        ),
        ToolResultMessage(tool_call_id="call_1", content="[]"),
    ]
    translated = provider._to_anthropic_messages(messages)
    assert translated[0] == {"role": "user", "content": "<alert>boom</alert>"}
    assert translated[1]["role"] == "assistant"
    assert translated[1]["content"][0] == {"type": "text", "text": "checking pods"}
    assert translated[1]["content"][1] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "list_pods",
        "input": {"namespace": "boutique"},
    }
    assert translated[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "[]"}],
    }


def test_complete_translates_text_and_tool_use_response() -> None:
    response = _FakeAnthropicResponse(
        content=[
            _FakeContentBlock("text", text="checking pods"),
            _FakeContentBlock(
                "tool_use", id="call_1", name="list_pods", input={"namespace": "boutique"}
            ),
        ],
        stop_reason="tool_use",
        usage=_FakeUsage(input_tokens=42, output_tokens=7),
    )
    provider = AnthropicProvider(client=_FakeAnthropicClient(response))

    result = provider.complete(
        messages=[UserMessage(text="<alert>boom</alert>")],
        tools=[
            {"name": "list_pods", "description": "list pods", "input_schema": {"type": "object"}}
        ],
        system="investigate the alert",
    )

    assert result.text == "checking pods"
    assert result.tool_calls == [
        ToolCallRequest(id="call_1", name="list_pods", args={"namespace": "boutique"})
    ]
    assert result.usage.input_tokens == 42
    assert result.usage.output_tokens == 7
    assert result.stop_reason == "tool_use"


def test_complete_passes_model_and_system_through_to_the_client() -> None:
    response = _FakeAnthropicResponse([], "end_turn", _FakeUsage(1, 1))
    client = _FakeAnthropicClient(response)
    provider = AnthropicProvider(client=client, model="claude-haiku-5-5")

    provider.complete(messages=[UserMessage(text="hi")], tools=[], system="be helpful")

    assert client.messages.last_call_kwargs["model"] == "claude-haiku-5-5"
    assert client.messages.last_call_kwargs["system"] == "be helpful"
