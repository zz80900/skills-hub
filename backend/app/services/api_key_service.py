import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.user import User


API_KEY_PREFIX = "ns-"
API_KEY_SUFFIX_LENGTH = 8


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    plaintext: str
    suffix: str
    issued_at: datetime


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def mask_api_key(suffix: str | None) -> str | None:
    if not suffix:
        return None
    return f"{API_KEY_PREFIX}{'•' * 8}{suffix}"


def resolve_api_key_user(session: Session, api_key: str) -> User | None:
    if not api_key.startswith(API_KEY_PREFIX) or len(api_key) <= len(API_KEY_PREFIX):
        return None
    return session.query(User).filter(User.api_key_hash == hash_api_key(api_key)).one_or_none()


def create_api_key(session: Session, user: User) -> IssuedApiKey:
    if user.api_key_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前账号已创建 API Key，请使用轮转功能",
        )
    issued = _new_issued_api_key()
    result = session.execute(
        update(User)
        .where(User.id == user.id, User.api_key_hash.is_(None))
        .values(
            api_key_hash=hash_api_key(issued.plaintext),
            api_key_suffix=issued.suffix,
            api_key_issued_at=issued.issued_at,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前账号已创建 API Key，请刷新状态后重试",
        )
    session.commit()
    session.refresh(user)
    return issued


def rotate_api_key(session: Session, user: User) -> IssuedApiKey:
    previous_hash = user.api_key_hash
    if not previous_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前账号尚未创建 API Key",
        )
    issued = _new_issued_api_key()
    result = session.execute(
        update(User)
        .where(User.id == user.id, User.api_key_hash == previous_hash)
        .values(
            api_key_hash=hash_api_key(issued.plaintext),
            api_key_suffix=issued.suffix,
            api_key_issued_at=issued.issued_at,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API Key 已发生变化，请刷新状态后重试",
        )
    session.commit()
    session.refresh(user)
    return issued


def _new_issued_api_key() -> IssuedApiKey:
    plaintext = generate_api_key()
    return IssuedApiKey(
        plaintext=plaintext,
        suffix=plaintext[-API_KEY_SUFFIX_LENGTH:],
        issued_at=datetime.now(timezone.utc),
    )
