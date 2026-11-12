"""MVP 用户鉴权 helper。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, WebSocket, status

from atestservice.config import ServerSettings


@dataclass(frozen=True, slots=True)
class AuthUser:
    """当前登录用户。"""

    user_id: str


_MOCK_USER_ID = "mock-user"


def verify_token(token: str | None, settings: ServerSettings) -> AuthUser:
    """校验 token，并返回当前用户。MVP 未配置 token 时使用 mock user。"""

    if not settings.auth_token:
        return AuthUser(user_id=_MOCK_USER_ID)

    if token and token == settings.auth_token:
        return AuthUser(user_id=_MOCK_USER_ID)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid token",
    )


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_atest_token: str | None = Header(default=None, alias="X-ATest-Token"),
) -> AuthUser:
    """HTTP API 依赖：解析当前用户。"""

    settings: ServerSettings = request.app.state.settings
    return verify_token(_extract_token(authorization, x_atest_token), settings)


def get_websocket_user(websocket: WebSocket, settings: ServerSettings) -> AuthUser:
    """WebSocket 连接鉴权。"""

    token = websocket.query_params.get("token")
    if token is None:
        token = _extract_token(
            websocket.headers.get("authorization"),
            websocket.headers.get("x-atest-token"),
        )

    return verify_token(token, settings)


def _extract_token(authorization: str | None, explicit_token: str | None) -> str | None:
    if explicit_token:
        return explicit_token

    if not authorization:
        return None

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value

    return authorization
