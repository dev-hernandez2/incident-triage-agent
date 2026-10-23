"""Discord OAuth2 login/callback and a live guild-role check.

Sessions are a signed cookie containing only the Discord user id — never
their roles — because the whole point of checking the role live on every
write request (see Task description / spec's Dashboard auth section) is
that a role revoked mid-session must lose approve access on the very next
request, not just at next login.
"""

import os

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer

_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ["DASHBOARD_SESSION_SECRET"]
    return URLSafeTimedSerializer(secret)


def create_session_cookie(discord_user_id: str) -> str:
    return _serializer().dumps({"discord_user_id": discord_user_id})


def read_session_cookie(cookie_value: str) -> str | None:
    try:
        data = _serializer().loads(cookie_value, max_age=_SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    user_id = data.get("discord_user_id")
    return user_id if isinstance(user_id, str) else None


def check_discord_role(
    discord_user_id: str,
    guild_id: str,
    role_id: str,
    bot_token: str,
    http_client: httpx.Client,
) -> bool:
    response = http_client.get(
        f"https://discord.com/api/v10/guilds/{guild_id}/members/{discord_user_id}",
        headers={"Authorization": f"Bot {bot_token}"},
    )
    response.raise_for_status()
    roles = response.json().get("roles", [])
    return role_id in roles


def discord_oauth_authorize_url(client_id: str, redirect_uri: str) -> str:
    return (
        "https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}&redirect_uri={redirect_uri}"
        "&response_type=code&scope=identify"
    )


def exchange_oauth_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_client: httpx.Client,
) -> str:
    """Exchanges an OAuth2 code for the authenticated user's Discord id."""
    token_response = http_client.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    token_response.raise_for_status()
    access_token = token_response.json()["access_token"]

    user_response = http_client.get(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    user_response.raise_for_status()
    user_id = user_response.json()["id"]
    assert isinstance(user_id, str)
    return user_id
