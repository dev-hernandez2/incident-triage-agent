from llm.types import (
    AssistantMessage,
    CompletionResult,
    ToolCallRequest,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def test_usage_is_a_plain_dataclass_with_token_counts() -> None:
    usage = Usage(input_tokens=10, output_tokens=5)
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5


def test_tool_call_request_carries_id_name_and_args() -> None:
    call = ToolCallRequest(id="call_1", name="list_pods", args={"namespace": "boutique"})
    assert call.id == "call_1"
    assert call.name == "list_pods"
    assert call.args == {"namespace": "boutique"}


def test_completion_result_bundles_text_tool_calls_usage_and_stop_reason() -> None:
    result = CompletionResult(
        text="checking pods",
        tool_calls=[ToolCallRequest(id="call_1", name="list_pods", args={})],
        usage=Usage(input_tokens=1, output_tokens=1),
        stop_reason="tool_use",
    )
    assert result.text == "checking pods"
    assert len(result.tool_calls) == 1
    assert result.stop_reason == "tool_use"


def test_user_message_wraps_plain_text() -> None:
    message = UserMessage(text="<alert>...</alert>")
    assert message.text == "<alert>...</alert>"


def test_assistant_message_carries_text_and_tool_calls() -> None:
    message = AssistantMessage(
        text="checking pods", tool_calls=[ToolCallRequest(id="call_1", name="list_pods", args={})]
    )
    assert message.text == "checking pods"
    assert message.tool_calls[0].name == "list_pods"


def test_tool_result_message_carries_tool_call_id_and_content() -> None:
    message = ToolResultMessage(tool_call_id="call_1", content="pod list here")
    assert message.tool_call_id == "call_1"
    assert message.content == "pod list here"
