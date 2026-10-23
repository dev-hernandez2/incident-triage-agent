"""Dashboard FastAPI entrypoint: wires create_app to a real DB session
factory, a live Discord role checker, and OAuth2 login/callback routes."""

import os

import httpx
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dashboard.api import create_app
from dashboard.auth import (
    check_discord_role,
    create_session_cookie,
    discord_oauth_authorize_url,
    exchange_oauth_code,
    read_session_cookie,
)

_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"
)
_GUILD_ID = os.environ["DISCORD_GUILD_ID"]
_APPROVER_ROLE_ID = os.environ["DISCORD_APPROVER_ROLE_ID"]
_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
_OAUTH_CLIENT_ID = os.environ["DISCORD_OAUTH_CLIENT_ID"]
_OAUTH_CLIENT_SECRET = os.environ["DISCORD_OAUTH_CLIENT_SECRET"]
_OAUTH_REDIRECT_URI = os.environ["DISCORD_OAUTH_REDIRECT_URI"]
_DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:5173")

_engine = create_engine(_DATABASE_URL)
_http_client = httpx.Client()


def _role_checker(discord_user_id: str) -> bool:
    return check_discord_role(
        discord_user_id=discord_user_id,
        guild_id=_GUILD_ID,
        role_id=_APPROVER_ROLE_ID,
        bot_token=_BOT_TOKEN,
        http_client=_http_client,
    )


def _current_user_id_from_request(request: Request) -> str:
    cookie = request.cookies.get("session")
    user_id = read_session_cookie(cookie) if cookie else None
    if user_id is None:
        raise PermissionError("not logged in")
    return user_id


app = create_app(
    session_factory=lambda: Session(_engine),
    role_checker=_role_checker,
    current_user_id=_current_user_id_from_request,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_DASHBOARD_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/auth/login")
def login() -> RedirectResponse:
    url = discord_oauth_authorize_url(_OAUTH_CLIENT_ID, _OAUTH_REDIRECT_URI)
    return RedirectResponse(url)


@app.get("/auth/callback")
def callback(code: str) -> RedirectResponse:
    user_id = exchange_oauth_code(
        code=code,
        client_id=_OAUTH_CLIENT_ID,
        client_secret=_OAUTH_CLIENT_SECRET,
        redirect_uri=_OAUTH_REDIRECT_URI,
        http_client=_http_client,
    )
    response = RedirectResponse(_DASHBOARD_ORIGIN)
    response.set_cookie("session", create_session_cookie(user_id), httponly=True)
    return response
