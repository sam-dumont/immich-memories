"""The web server: the Svelte client and its API, health, the trigger API, and sign-in.

`immich-memories ui` runs this with uvicorn. It is a plain FastAPI app: the pages are the static
client under /app, every action is an /api/v1 call, and a cut or render is the CLI itself as a
child process (web/jobs.py). The session is Starlette's signed cookie; the rules of who gets in
are the ones in web/auth.py, applied by the middleware below in the same order as before.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from immich_memories.config import get_config, init_config_dir
from immich_memories.config_models_auth import AuthConfig
from immich_memories.security import write_secret_file
from immich_memories.web import mount_web
from immich_memories.web.auth import (
    clear_session,
    client_ip_for_rate_limit,
    is_auth_enabled,
    is_bypass_path,
    is_health_probe_path,
    is_rate_limited,
    is_trigger_path,
    is_trusted_proxy,
    record_failed_login,
    set_session,
    trigger_token_authorizes,
    verify_credentials,
)
from immich_memories.web.health import register_health_routes
from immich_memories.web.reverse_proxy import reverse_proxy_run_kwargs
from immich_memories.web.trigger import register_trigger_routes

logger = logging.getLogger(__name__)

LOGIN_PAGE = "/app/login"
_FONTS = Path(__file__).parent / "static" / "fonts"

# The server pages this client replaced, and where each now lives (#1395).
_MOVED = {
    "/": "/app/create",
    "/step2": "/app/runs",
    "/step3": "/app/runs",
    "/step4": "/app/runs",
    "/suggestions": "/app/suggestions",
    "/settings/config": "/app/settings",
    "/settings/cache": "/app/settings",
    "/settings/people": "/app/settings/people",
    "/login": LOGIN_PAGE,
}


def storage_secret() -> str:
    """The key the session cookie is signed with: env var, then file, then a new one kept on disk.

    The same file the earlier server used, so an upgrade keeps everyone signed in.
    """
    if env_secret := os.environ.get("IMMICH_MEMORIES_STORAGE_SECRET"):
        return env_secret
    path = Path.home() / ".immich-memories" / ".storage_secret"
    if path.exists():
        return path.read_text().strip()
    secret = secrets.token_hex(32)
    write_secret_file(path, secret)
    return secret


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return client_ip_for_rate_limit(
        peer_ip=peer,
        forwarded_for=request.headers.get("x-forwarded-for"),
        auth_config=get_config().auth,
    )


def _try_header_auth(request: Request, auth_config: AuthConfig) -> None:
    """Start a session from a trusted proxy's user header."""
    client_ip = request.client.host if request.client else ""
    if not is_trusted_proxy(client_ip, auth_config.trusted_proxies):
        return
    user = request.headers.get(auth_config.user_header, "")
    if user and not request.session.get("authenticated"):
        email = request.headers.get(auth_config.email_header, "")
        set_session(request.session, username=user, provider="header", email=email)


def _expired(session: dict[str, Any], ttl_hours: int) -> bool:
    started = session.get("authenticated_at")
    if not started:
        return False
    return datetime.now(UTC) > datetime.fromisoformat(str(started)) + timedelta(hours=ttl_hours)


def unauthenticated_response(path: str) -> Response:
    """An API caller gets a status it can act on; a browser goes to the sign-in page."""
    if is_trigger_path(path) or path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse(LOGIN_PAGE, status_code=307)


async def _auth_middleware(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if is_health_probe_path(path):
        return await call_next(request)
    config = get_config()
    if not is_auth_enabled(config.auth) or is_bypass_path(path):
        return await call_next(request)
    if trigger_token_authorizes(path, request.headers, config.server.trigger_token):
        return await call_next(request)
    if config.auth.provider == "header":
        _try_header_auth(request, config.auth)
    if not request.session.get("authenticated"):
        return unauthenticated_response(path)
    if _expired(request.session, config.auth.session_ttl_hours):
        clear_session(request.session)
        return unauthenticated_response(path)
    return await call_next(request)


class Credentials(BaseModel):
    username: str
    password: str


_NOT_AUTHORISED_PAGE = """<!doctype html>
<meta charset="utf-8"><title>Not authorised</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #111; color: #eee;
         display: grid; place-items: center; height: 100vh; margin: 0; }}
  div {{ max-width: 32rem; padding: 2rem; text-align: center; }}
  code {{ background: #222; padding: .15em .4em; border-radius: .25em; }}
</style>
<div>
  <h1>Not authorised</h1>
  <p>You signed in as <code>{who}</code>, but this server requires a verified
     email address on its allow-list.</p>
  <p>Ask the administrator to check email verification at the identity provider
     and <code>auth.allowed_emails</code> or <code>auth.allowed_domains</code>.</p>
</div>
"""


async def login(credentials: Credentials, request: Request) -> JSONResponse:
    """Basic sign-in: the same limiter and constant-time check as before."""
    config = get_config()
    client_ip = _client_ip(request)
    if is_rate_limited(client_ip):
        return JSONResponse(
            {"detail": "Too many failed attempts. Try again later."}, status_code=429
        )
    user = credentials.username.strip()
    if config.auth.provider != "basic" or not verify_credentials(
        user, credentials.password, config.auth
    ):
        record_failed_login(client_ip)
        return JSONResponse({"detail": "Invalid username or password"}, status_code=401)
    set_session(request.session, username=user, provider="basic")
    return JSONResponse({"signed_in": True})


async def logout(request: Request) -> RedirectResponse:
    """Clear the session; an OIDC sign-in also ends at the provider when it offers that."""
    config = get_config()
    provider = request.session.get("auth_provider")
    clear_session(request.session)
    if provider == config.auth.provider == "oidc":
        from immich_memories.web.auth_oidc import get_end_session_url

        if end_session := get_end_session_url(config.auth):
            return RedirectResponse(end_session)
    return RedirectResponse(LOGIN_PAGE, status_code=307)


async def oidc_authorize(request: Request) -> RedirectResponse:
    """Send the browser to the identity provider."""
    config = get_config()
    if config.auth.provider != "oidc":
        return RedirectResponse(LOGIN_PAGE)
    from immich_memories.web.auth_oidc import create_oidc_client, oidc_redirect_uri

    oauth = create_oidc_client(config.auth)
    redirect_uri = oidc_redirect_uri(str(request.url_for("oidc_callback")), config.auth.public_url)
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


async def oidc_callback(request: Request) -> Response:
    """Exchange the code, check the allow-list, and start the session."""
    config = get_config()
    from immich_memories.web.auth_oidc import (
        create_oidc_client,
        extract_user_from_token,
        is_user_allowed,
        validate_callback_origin,
    )

    if not validate_callback_origin(request, config.auth.public_url):
        logger.warning("OIDC callback origin mismatch: %s", request.url)
        return JSONResponse({"detail": "Invalid callback origin"}, status_code=400)
    token = await create_oidc_client(config.auth).oidc.authorize_access_token(request)
    username, email = extract_user_from_token(token)
    verified = (token.get("userinfo") or {}).get("email_verified")
    if not is_user_allowed(email, config.auth, email_verified=verified):
        # WHY a page and not a redirect: the IdP session is still valid, so the sign-in page
        # would send them straight back here and loop.
        logger.warning("OIDC login refused: a verified email on the allow-list is required")
        return HTMLResponse(_NOT_AUTHORISED_PAGE.format(who=html.escape(email or username)), 403)
    set_session(request.session, username=username, provider="oidc", email=email)
    return RedirectResponse("/app/create")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    from immich_memories.automation.in_process_scheduler import automation_scheduler

    init_config_dir()
    config = get_config(reload=True)
    logger.info(
        "Application initialized (auth=%s)", "enabled" if config.auth.enabled else "disabled"
    )
    scheduler = asyncio.ensure_future(automation_scheduler.run_forever())
    try:
        yield
    finally:
        scheduler.cancel()
        logger.info("Application shutting down")


def _moved(target: str):
    async def redirect(request: Request) -> RedirectResponse:
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{target}{query}", status_code=307)

    return redirect


def create_app() -> FastAPI:
    """The whole server, ready for uvicorn."""
    config = get_config()
    app = FastAPI(title="Immich Memories", lifespan=_lifespan, docs_url=None, redoc_url=None)
    register_health_routes(app)
    register_trigger_routes(app)
    mount_web(app)
    app.add_api_route("/auth/login", login, methods=["POST"])
    app.add_api_route("/logout", logout, methods=["GET"])
    app.add_api_route("/auth/authorize", oidc_authorize, methods=["GET"])
    app.add_api_route("/auth/callback", oidc_callback, methods=["GET"], name="oidc_callback")
    for path, target in _MOVED.items():
        app.add_api_route(path, _moved(target), methods=["GET"], include_in_schema=False)
    app.mount("/static/fonts", StaticFiles(directory=_FONTS), name="fonts")
    app.middleware("http")(_auth_middleware)
    # Added last so it wraps outermost: the auth middleware reads the session it decodes.
    session_kwargs = reverse_proxy_run_kwargs(config, os.environ).get(
        "session_middleware_kwargs", {}
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=storage_secret(),
        max_age=config.auth.session_ttl_hours * 3600,
        same_site="lax",
        **session_kwargs,
    )
    return app


def _is_port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def main(
    port: int = 8080, host: str = "127.0.0.1", reload: bool = False, log_level: str | None = None
) -> None:
    """Run the server with uvicorn."""
    import uvicorn

    from immich_memories.logging_config import configure_logging

    configure_logging(level=log_level)
    if not _is_port_free(host, port):
        logger.error(
            "Port %s is already in use. Stop the existing process: lsof -ti :%s | xargs kill",
            port,
            port,
        )
        sys.exit(1)
    proxy = reverse_proxy_run_kwargs(get_config(), os.environ)
    uvicorn.run(
        "immich_memories.web.server:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=proxy.get("forwarded_allow_ips"),
        log_config=None,
    )
