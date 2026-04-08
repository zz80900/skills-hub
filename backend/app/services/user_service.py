import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import Role, User, USER_SOURCE_AD, USER_SOURCE_LOCAL
from app.services.ad_auth import (
    ActiveDirectoryIdentity,
    ActiveDirectoryInvalidCredentialsError,
    ActiveDirectoryLookupError,
    authenticate_active_directory_user,
)


ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
UNUSABLE_PASSWORD_HASH = "!ad-auth-only!"


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def normalize_login_identifier(username: str) -> str:
    normalized = (username or "").strip()
    if "\\" in normalized:
        normalized = normalized.rsplit("\\", 1)[-1]
    if "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    return normalize_username(normalized)


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用户名只允许小写字母、数字、点号、下划线和中划线，长度为 3 到 64 位",
        )
    return normalized


def validate_password(password: str) -> str:
    if len(password or "") < 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="密码长度不能少于 4 位",
        )
    return password


def normalize_role_name(role_name: str) -> str:
    normalized = (role_name or "").strip().upper()
    if normalized not in {ROLE_ADMIN, ROLE_USER}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="角色只允许为 ADMIN 或 USER",
        )
    return normalized


def get_role_by_name(session: Session, role_name: str) -> Role | None:
    normalized = normalize_role_name(role_name)
    statement = select(Role).where(Role.name == normalized)
    return session.scalar(statement)


def get_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    normalized = normalize_username(username)
    if not normalized:
        return None
    statement = select(User).where(User.username == normalized)
    return session.scalar(statement)


def get_user_by_login_identifier(session: Session, username: str) -> User | None:
    normalized = normalize_login_identifier(username)
    if not normalized:
        return None
    statement = select(User).where(User.username == normalized)
    return session.scalar(statement)


def list_users(session: Session) -> list[User]:
    statement = select(User).order_by(User.created_at.desc(), User.id.desc())
    return list(session.scalars(statement))


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = get_user_by_login_identifier(session, username)
    if user is not None:
        if not user.is_active:
            return None
        if user.source == USER_SOURCE_AD:
            return authenticate_existing_ad_user(session, user, username, password)
        return authenticate_local_user(user, password)

    try:
        identity = authenticate_active_directory_user(username, password)
    except (ActiveDirectoryInvalidCredentialsError, ActiveDirectoryLookupError):
        return None
    return provision_ad_user(session, identity)


def authenticate_local_user(user: User, password: str) -> User | None:
    if user.source != USER_SOURCE_LOCAL:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def authenticate_existing_ad_user(session: Session, user: User, username: str, password: str) -> User | None:
    try:
        identity = authenticate_active_directory_user(username, password)
    except (ActiveDirectoryInvalidCredentialsError, ActiveDirectoryLookupError):
        return None
    synced_user = sync_ad_user_profile(session, user, identity)
    return synced_user


def create_user(
    session: Session,
    username: str,
    password: str | None,
    role_name: str,
    is_active: bool = True,
    *,
    source: str = USER_SOURCE_LOCAL,
    display_name: str | None = None,
    external_principal: str | None = None,
) -> User:
    role = get_role_by_name(session, role_name)
    if role is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="角色不存在")

    normalized_source = normalize_user_source(source)
    password_hash = build_password_hash_for_source(normalized_source, password)
    user = User(
        username=validate_username(username),
        password_hash=password_hash,
        role_id=role.id,
        source=normalized_source,
        display_name=normalize_display_name(display_name),
        external_principal=normalize_external_principal(external_principal),
        is_active=is_active,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def count_active_admins(session: Session) -> int:
    statement = (
        select(func.count(User.id))
        .join(Role, Role.id == User.role_id)
        .where(Role.name == ROLE_ADMIN, User.is_active.is_(True))
    )
    return int(session.scalar(statement) or 0)


def ensure_admin_guard(session: Session, user: User, next_role_name: str, next_is_active: bool) -> None:
    is_current_admin = user.role.name == ROLE_ADMIN and user.is_active
    will_remain_active_admin = next_role_name == ROLE_ADMIN and next_is_active
    if not is_current_admin or will_remain_active_admin:
        return
    if count_active_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统至少需要保留一个启用中的管理员账号",
        )


def update_user(
    session: Session,
    user: User,
    *,
    username: str | None = None,
    role_name: str | None = None,
    is_active: bool | None = None,
) -> User:
    next_role_name = normalize_role_name(role_name) if role_name is not None else user.role.name
    next_is_active = user.is_active if is_active is None else is_active
    ensure_admin_guard(session, user, next_role_name, next_is_active)

    if username is not None:
        next_username = validate_username(username)
        if user.source == USER_SOURCE_AD and next_username != user.username:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AD 用户用户名由域账号映射，不支持手动修改",
            )
        user.username = next_username
    if role_name is not None:
        role = get_role_by_name(session, next_role_name)
        if role is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="角色不存在")
        user.role_id = role.id
    if is_active is not None:
        user.is_active = is_active

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def reset_user_password(session: Session, user: User, password: str) -> User:
    if user.source != USER_SOURCE_LOCAL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AD 用户密码由域控管理，不支持本地重置",
        )
    user.password_hash = hash_password(validate_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def provision_ad_user(session: Session, identity: ActiveDirectoryIdentity) -> User:
    existing_user = get_user_by_username(session, identity.username)
    if existing_user is not None:
        if existing_user.source != USER_SOURCE_AD:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="AD 用户与现有本地账号重名，请联系管理员处理",
            )
        return sync_ad_user_profile(session, existing_user, identity)

    try:
        return create_user(
            session,
            identity.username,
            None,
            ROLE_USER,
            True,
            source=USER_SOURCE_AD,
            display_name=identity.display_name,
            external_principal=identity.external_principal or identity.principal,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AD 用户与现有本地账号重名，请联系管理员处理",
        ) from exc


def sync_ad_user_profile(session: Session, user: User, identity: ActiveDirectoryIdentity) -> User:
    if user.source != USER_SOURCE_AD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户来源与登录方式不匹配，请联系管理员处理",
        )
    user.display_name = normalize_display_name(identity.display_name)
    user.external_principal = normalize_external_principal(identity.external_principal or identity.principal)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def build_password_hash_for_source(source: str, password: str | None) -> str:
    if source == USER_SOURCE_AD:
        return UNUSABLE_PASSWORD_HASH
    return hash_password(validate_password(password or ""))


def normalize_user_source(source: str) -> str:
    normalized = (source or "").strip().upper()
    if normalized not in {USER_SOURCE_LOCAL, USER_SOURCE_AD}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用户来源只允许为 LOCAL 或 AD",
        )
    return normalized


def normalize_display_name(display_name: str | None) -> str | None:
    normalized = (display_name or "").strip()
    return normalized or None


def normalize_external_principal(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def to_authenticated_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role.name,
        "source": user.source,
        "display_name": user.display_name,
    }


def to_user_summary(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role.name,
        "source": user.source,
        "display_name": user.display_name,
        "external_principal": user.external_principal,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }
