import httpx
from dashboard.auth import check_discord_role


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, roles: list[str]) -> None:
        self._roles = roles

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"roles": self._roles})


def test_check_discord_role_true_when_role_present() -> None:
    transport = _FakeTransport(roles=["111", "222"])
    client = httpx.Client(transport=transport)

    result = check_discord_role(
        discord_user_id="u1",
        guild_id="g1",
        role_id="222",
        bot_token="tok",
        http_client=client,
    )

    assert result is True


def test_check_discord_role_false_when_role_absent() -> None:
    transport = _FakeTransport(roles=["111"])
    client = httpx.Client(transport=transport)

    result = check_discord_role(
        discord_user_id="u1",
        guild_id="g1",
        role_id="222",
        bot_token="tok",
        http_client=client,
    )

    assert result is False
