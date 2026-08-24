from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.api_key_service import API_KEY_PREFIX, resolve_api_key_user
from app.services.user_service import ROLE_ADMIN


bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def _resolve_resource_authorization(session: Session, authorization: str | None) -> User | None:
    if authorization is None:
        return None

    scheme, separator, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Authorization 请求头",
        )

    if token.startswith(API_KEY_PREFIX):
        user = resolve_api_key_user(session, token)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效、已轮转或账号已停用",
            )
        return user

    payload = decode_access_token(token)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的登录状态",
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效或账号已停用",
        )
    return user


def get_optional_resource_user(
    session: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User | None:
    return _resolve_resource_authorization(session, authorization)


def get_resource_user(
    session: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    user = _resolve_resource_authorization(session, authorization)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请提供登录凭证或 API Key",
        )
    return user


def get_api_key_resource_user(
    session: DbSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请提供 API Key",
        )

    scheme, separator, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 必须使用 Bearer ns-... 格式",
        )
    if not token.startswith(API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该接口只接受 API Key，不接受登录 JWT",
        )

    user = resolve_api_key_user(session, token)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效、已轮转或账号已停用",
        )
    return user

def _resolve_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    if credentials is None:
        return None

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的登录状态",
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效或账号已停用",
        )
    return user


def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    user = _resolve_current_user(session, credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    return user


def get_optional_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    return _resolve_current_user(session, credentials)


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role.name != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可访问该功能",
        )
    return current_user
