from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from sol_api.config import config


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    session_id: str
    expires_at: float


class AuthSessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, AuthIdentity] = {}

    def issue(self, *, user_id: str) -> tuple[str, AuthIdentity]:
        now = time.time()
        token = secrets.token_urlsafe(32)
        identity = AuthIdentity(
            user_id=user_id,
            session_id=secrets.token_hex(12),
            expires_at=now + float(config.auth_session_ttl_s),
        )
        with self._lock:
            self._sessions[token] = identity
        return token, identity

    def authenticate(self, token: str) -> AuthIdentity | None:
        now = time.time()
        with self._lock:
            stale = [key for key, value in self._sessions.items() if value.expires_at <= now]
            for key in stale:
                self._sessions.pop(key, None)
            identity = self._sessions.get(token)
        if not identity:
            return None
        if identity.expires_at <= now:
            self.revoke(token)
            return None
        return identity

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._sessions.clear()


session_store = AuthSessionStore()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_credentials(username: str, password: str) -> str | None:
    user_id = (username or "").strip().lower()
    if not user_id:
        return None
    expected = str(config.auth_users.get(user_id) or "").strip().lower()
    if not expected:
        return None
    candidate = _sha256_hex(password or "")
    if not hmac.compare_digest(candidate, expected):
        return None
    return user_id


def _unauthorized(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def bearer_token_from_request(request: Request) -> str | None:
    header = (request.headers.get("authorization") or "").strip()
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_api_auth(request: Request, authorization: str | None = Header(default=None)) -> AuthIdentity:
    if not config.auth_enabled:
        identity = AuthIdentity(user_id="local", session_id="local", expires_at=float("inf"))
        request.state.auth = identity
        return identity
    header = (authorization or "").strip()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    identity = session_store.authenticate(token.strip())
    if not identity:
        raise _unauthorized("Authentication session is invalid or expired.")
    request.state.auth = identity
    return identity


def current_auth(request: Request) -> AuthIdentity | None:
    auth = getattr(getattr(request, "state", None), "auth", None)
    return auth if isinstance(auth, AuthIdentity) else None


def current_user_id(request: Request) -> str | None:
    auth = current_auth(request)
    return auth.user_id if auth else None
