from __future__ import annotations

import time

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field

from sol_api.auth import AuthIdentity, bearer_token_from_request, require_api_auth, session_store, verify_credentials

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    ok: bool = True
    user: str
    token: str
    expires_at: float
    ts: float = Field(default_factory=time.time)


class MeResponse(BaseModel):
    ok: bool = True
    user: str
    expires_at: float
    ts: float = Field(default_factory=time.time)


class LogoutResponse(BaseModel):
    ok: bool = True
    ts: float = Field(default_factory=time.time)


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest = Body(...)) -> LoginResponse:
    user_id = verify_credentials(body.username, body.password)
    if not user_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid credentials.", headers={"WWW-Authenticate": "Bearer"})
    token, identity = session_store.issue(user_id=user_id)
    return LoginResponse(user=user_id, token=token, expires_at=identity.expires_at)


@router.get("/auth/me", response_model=MeResponse)
def me(identity: AuthIdentity = Depends(require_api_auth)) -> MeResponse:
    return MeResponse(user=identity.user_id, expires_at=identity.expires_at)


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(request: Request, _: AuthIdentity = Depends(require_api_auth)) -> LogoutResponse:
    token = bearer_token_from_request(request)
    if token:
        session_store.revoke(token)
    return LogoutResponse()
