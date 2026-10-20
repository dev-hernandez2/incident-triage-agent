import json
from typing import Any

from llm.openai_provider import OpenAIProvider
from llm.types import AssistantMessage, Message, ToolCallRequest, ToolResultMessage, UserMessage


class _FakeFunctionCall:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id_: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = id_
        self.type = "function"
        self.function = _FakeFunctionCall(name, json.dumps(arguments))


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list[_FakeToolCall] | None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage, finish_reason: str) -> None:
        self.message = message
        self.finish_reason = finish_reason


class _FakeOpenAIUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeOpenAIResponse:
    def __init__(self, choices: list[_FakeChoice], usage: _FakeOpenAIUsage) -> None:
        self.choices = choices
        self.usage = usage


class _FakeCompletionsApi:
    def __init__(self, response: _FakeOpenAIResponse) -> None:
        self._response = response
        self.last_call_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        self.last_call_kwargs = kwargs
        return self._response


class _FakeChatApi:
    def __init__(self, response: _FakeOpenAIResponse) -> None:
        self.completions = _FakeCompletionsApi(response)


class _FakeOpenAIClient:
    def __init__(self, response: _FakeOpenAIResponse) -> None:
        self.chat = _FakeChatApi(response)


def test_to_openai_messages_translates_each_message_kind() -> None:
    provider = OpenAIProvider(
        client=_FakeOpenAIClient(_FakeOpenAIResponse([], _FakeOpenAIUsage(0, 0)))
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
    translated = provider._to_openai_messages(messages)
    assert translated[0] == {"role": "user", "content": "<alert>boom</alert>"}
    assert translated[1]["role"] == "assistant"
    assert translated[1]["content"] == "checking pods"
    assert translated[1]["tool_calls"][0]["id"] == "call_1"
    assert json.loads(translated[1]["tool_calls"][0]["function"]["arguments"]) == {
        "namespace": "boutique"
    }
    assert translated[2] == {"role": "tool", "tool_call_id": "call_1", "content": "[]"}


def test_complete_translates_text_and_tool_call_response() -> None:
    response = _FakeOpenAIResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(
                    content="checking pods",
                    tool_calls=[_FakeToolCall("call_1", "list_pods", {"namespace": "boutique"})],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=_FakeOpenAIUsage(prompt_tokens=42, completion_tokens=7),
    )
    provider = OpenAIProvider(client=_FakeOpenAIClient(response))

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
    assert result.stop_reason == "tool_calls"


def test_complete_passes_model_and_system_through_to_the_client() -> None:
    response = _FakeOpenAIResponse(
        choices=[_FakeChoice(_FakeMessage("hi", None), "stop")],
        usage=_FakeOpenAIUsage(1, 1),
    )
    client = _FakeOpenAIClient(response)
    provider = OpenAIProvider(client=client, model="gpt-5.6-luna")

    provider.complete(messages=[UserMessage(text="hi")], tools=[], system="be helpful")

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["model"] == "gpt-5.6-luna"
    assert kwargs["messages"][0] == {"role": "system", "content": "be helpful"}
