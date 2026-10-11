"""A small OpenID Connect provider over HTTP, for signing in to the served app.

It publishes discovery and a signing key, and plays the user's part at the authorize
step: `approve` turns the app's authorize redirect into the code the browser would
bring back. Its token endpoint refuses a code without the PKCE verifier whose S256
challenge the app sent, or without the client's secret, the way a provider does.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey

CLIENT_ID = "immich-memories"
CLIENT_SECRET = "oidc-feature-client-secret"  # noqa: S105 -- throwaway test client


@dataclass(frozen=True, slots=True)
class _Grant:
    nonce: str
    challenge: str
    redirect_uri: str
    email: str
    verified: bool


class OidcProvider:
    """The provider; `issuer` is the URL the app is configured with."""

    def __init__(self) -> None:
        self._key = RSAKey.generate_key(2048, parameters={"kid": "feature-key", "use": "sig"})
        self._grants: dict[str, _Grant] = {}
        # Every token request: whether its PKCE verifier matched the challenge.
        self.verifier_checks: list[bool] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @classmethod
    def start(cls) -> Self:
        provider = cls()
        provider._thread.start()
        return provider

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def approve(self, authorize_url: str, *, email: str, verified: bool = True) -> str:
        """The user signs in at the provider: the callback query the browser is sent back with."""
        query = {k: v[-1] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert authorize_url.startswith(f"{self.issuer}/authorize?"), authorize_url
        assert query["code_challenge_method"] == "S256", query
        code = secrets.token_urlsafe(16)
        self._grants[code] = _Grant(
            nonce=query["nonce"],
            challenge=query["code_challenge"],
            redirect_uri=query["redirect_uri"],
            email=email,
            verified=verified,
        )
        return f"{query['redirect_uri']}?code={code}&state={query['state']}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # ── the provider's side ───────────────────────────────────────────────────

    def _discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        }

    def _token(self, form: dict[str, str], authorization: str) -> tuple[int, dict[str, Any]]:
        grant = self._grants.pop(form.get("code", ""), None)
        if grant is None or form.get("redirect_uri") != grant.redirect_uri:
            return 400, {"error": "invalid_grant"}
        if not _client_authenticated(form, authorization):
            return 401, {"error": "invalid_client"}
        digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
        matched = base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == grant.challenge
        self.verifier_checks.append(matched)
        if not matched:
            return 400, {"error": "invalid_grant", "error_description": "PKCE verifier"}
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": grant.email,
            "iat": now,
            "exp": now + 300,
            "nonce": grant.nonce,
            "email": grant.email,
            "email_verified": grant.verified,
            "preferred_username": grant.email.split("@")[0],
        }
        id_token = jwt.encode({"alg": "RS256", "kid": "feature-key"}, claims, self._key)
        return 200, {
            "access_token": secrets.token_urlsafe(16),
            "token_type": "Bearer",
            "expires_in": 300,
            "id_token": id_token,
        }

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/.well-known/openid-configuration":
                    self._json(200, provider._discovery())
                elif path == "/jwks":
                    self._json(200, {"keys": [provider._key.as_dict(private=False)]})
                else:
                    self._json(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                if urlsplit(self.path).path != "/token":
                    self._json(404, {"error": "not_found"})
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
                form = {k: v[-1] for k, v in parse_qs(body).items()}
                self._json(*provider._token(form, self.headers.get("Authorization", "")))

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        return Handler


def _client_authenticated(form: dict[str, str], authorization: str) -> bool:
    if authorization.startswith("Basic "):
        decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode()
        return decoded == f"{CLIENT_ID}:{CLIENT_SECRET}"
    return form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET
