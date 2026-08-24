import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.mcp.context import ANONYMOUS_PRINCIPAL, McpPrincipal, reset_mcp_principal, set_mcp_principal
from app.mcp.results import McpToolFailure
from app.models.user import User
from app.services.api_key_service import API_KEY_PREFIX, resolve_api_key_user


AsgiApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[None]]


class McpApiKeyAuthMiddleware:
    def __init__(self, app: AsgiApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        authorization_values = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        if not authorization_values:
            principal = ANONYMOUS_PRINCIPAL
        elif len(authorization_values) == 1:
            principal = self._authenticate(authorization_values[0])
            if principal is None:
                await _send_unauthorized(send)
                return
        else:
            await _send_unauthorized(send)
            return

        token = set_mcp_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_mcp_principal(token)

    @staticmethod
    def _authenticate(authorization: str) -> McpPrincipal | None:
        parts = authorization.strip().split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        api_key = parts[1]
        if not api_key.startswith(API_KEY_PREFIX):
            return None

        with SessionLocal() as session:
            user = resolve_api_key_user(session, api_key)
            if user is None or not user.is_active:
                return None
            return McpPrincipal(user_id=user.id)


def get_optional_mcp_user(session: Session) -> User | None:
    principal = _current_user_id()
    if principal is None:
        return None
    user = session.get(User, principal)
    if user is None or not user.is_active:
        raise McpToolFailure("AUTHENTICATION_REQUIRED", "API Key 无效、已轮转或账号已停用")
    return user


def require_mcp_user(session: Session) -> User:
    user = get_optional_mcp_user(session)
    if user is None:
        raise McpToolFailure("AUTHENTICATION_REQUIRED", "该工具需要有效的 API Key")
    return user


def _current_user_id() -> int | None:
    from app.mcp.context import get_mcp_principal

    return get_mcp_principal().user_id


async def _send_unauthorized(send: Callable[..., Awaitable[Any]]) -> None:
    payload = json.dumps(
        {
            "error": "invalid_token",
            "error_description": "MCP 仅接受 Authorization Bearer 中当前有效的 ns- API Key",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (
                    b"www-authenticate",
                    b'Bearer realm="nexgo-skills-mcp", error="invalid_token"',
                ),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
