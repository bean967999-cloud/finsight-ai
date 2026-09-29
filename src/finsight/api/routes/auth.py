"""Identity endpoints; authorization of business actions is a separate step."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from finsight.domain.access_control import Principal
from finsight.services.identity import AuthenticationService, InvalidCredentials

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int


def get_auth_service(request: Request) -> AuthenticationService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(503, "身份认证未启用")
    return service


def get_current_principal(request: Request) -> Principal:
    service = get_auth_service(request)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "缺少有效身份令牌", headers={"WWW-Authenticate": "Bearer"})
    try:
        principal = service.resolve(token)
        request.state.audit_actor_id = principal.user_id
        return principal
    except InvalidCredentials as error:
        raise HTTPException(401, "身份令牌无效", headers={"WWW-Authenticate": "Bearer"}) from error


def require_active_principal(request: Request) -> Principal:
    """Public platform capabilities still require a currently active identity."""
    principal = get_current_principal(request)
    if not principal.active:
        raise HTTPException(401, "账号不可用", headers={"WWW-Authenticate": "Bearer"})
    return principal


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    service = get_auth_service(request)
    try:
        token = service.login(payload.email, payload.password)
    except InvalidCredentials as error:
        raise HTTPException(401, "用户名或密码错误") from error
    request.state.audit_actor_id = service.tokens.verify(token)
    return TokenResponse(
        access_token=token,
        expires_in_seconds=service.tokens.ttl_minutes * 60,
    )


@router.get("/me", response_model=Principal)
def current_user(request: Request) -> Principal:
    return get_current_principal(request)
