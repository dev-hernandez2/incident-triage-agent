from agent.tools.redact import redact


def test_redacts_bearer_header() -> None:
    text = "Authorization: Bearer abc.def-ghi_123"
    assert "abc.def-ghi_123" not in redact(text)
    assert "Bearer ***REDACTED***" in redact(text)


def test_redacts_password_key_value() -> None:
    text = 'password="hunter2secret"'
    out = redact(text)
    assert "hunter2secret" not in out
    assert "password=" in out


def test_redacts_token_key_value_without_quotes() -> None:
    text = "token=sk-abcdef1234567890"
    out = redact(text)
    assert "sk-abcdef1234567890" not in out


def test_redacts_long_hex_string() -> None:
    text = "session_id " + "a" * 40 + " end"
    out = redact(text)
    assert "a" * 40 not in out


def test_leaves_normal_text_untouched() -> None:
    text = "pod cartservice-abc123 is CrashLoopBackOff, restarts=5"
    assert redact(text) == text


def test_leaves_long_kubernetes_pod_name_untouched() -> None:
    text = "cartservice-c7cf86b58-fmkhn"
    assert redact(text) == text


def test_redacts_base64_token_with_padding() -> None:
    text = "ghp_dGhpc2lzYXNlY3JldHRva2VuMTIzNDU2Nzg5MA=="
    out = redact(text)
    assert "dGhpc2lzYXNlY3JldHRva2VuMTIzNDU2Nzg5MA==" not in out
