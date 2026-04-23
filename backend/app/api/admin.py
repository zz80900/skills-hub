from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_admin
from app.core.config import get_settings
from app.core.encryption import DecryptionError, decrypt_and_validate
from app.core.rsa import get_challenge_store, get_key_manager
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.group import GroupCreateRequest, GroupSummary, GroupUpdateRequest
from app.schemas.user import UserCreateRequest, UserListResponse, UserPasswordResetRequest, UserSummary, UserUpdateRequest
from app.services.group_service import UNSET, create_group, delete_group, get_group_by_id, list_groups, to_group_summary, update_group
from app.services.user_service import (
    create_user,
    get_user_by_id,
    reset_user_password,
    search_users,
    to_user_summary,
    update_user,
)


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _extract_password(payload, expected_purpose: str) -> str:
    if payload.is_encrypted:
        try:
            decrypted = decrypt_and_validate(
                encrypted_password=payload.encrypted_password,
                challenge_id=payload.challenge_id,
                client_ts=payload.client_ts,
                nonce=payload.nonce,
                key_manager=get_key_manager(),
                challenge_store=get_challenge_store(),
                expected_purpose=expected_purpose,
                max_clock_skew=get_settings().rsa_max_clock_skew_seconds,
            )
            return decrypted.password
        except DecryptionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return payload.password


@router.get("/users", response_model=UserListResponse)
def list_admin_users(
    session: DbSession,
    _: User = Depends(require_admin),
    q: str | None = Query(default=None, description="搜索用户名或姓名"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
):
    users, total = search_users(session, q, page=page, page_size=page_size)
    items = [UserSummary.model_validate(to_user_summary(user)) for user in users]
    return UserListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_more=page * page_size < total,
    )


@router.get("/groups", response_model=list[GroupSummary])
def list_admin_groups(
    session: DbSession,
    _: User = Depends(require_admin),
):
    return [GroupSummary.model_validate(to_group_summary(group)) for group in list_groups(session)]


@router.post("/groups", response_model=GroupSummary, status_code=status.HTTP_201_CREATED)
def create_admin_group(
    payload: GroupCreateRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    group = create_group(
        session,
        name=payload.name,
        description=payload.description,
        leader_user_id=payload.leader_user_id,
    )
    return GroupSummary.model_validate(to_group_summary(group))


@router.put("/groups/{group_id}", response_model=GroupSummary)
def update_admin_group(
    group_id: int,
    payload: GroupUpdateRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")

    provided_fields = payload.model_fields_set
    group = update_group(
        session,
        group,
        name=payload.name if "name" in provided_fields else UNSET,
        description=payload.description if "description" in provided_fields else UNSET,
        leader_user_id=payload.leader_user_id if "leader_user_id" in provided_fields else UNSET,
    )
    return GroupSummary.model_validate(to_group_summary(group))


@router.delete("/groups/{group_id}", response_model=MessageResponse)
def delete_admin_group(
    group_id: int,
    session: DbSession,
    _: User = Depends(require_admin),
):
    group = get_group_by_id(session, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户组不存在")
    delete_group(session, group)
    return MessageResponse(message="用户组已删除")


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_admin_user(
    payload: UserCreateRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    try:
        password = _extract_password(payload, "admin_create_user")
        user = create_user(session, payload.username, password, payload.role, payload.is_active)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在") from exc
    return UserSummary.model_validate(to_user_summary(user))


@router.put("/users/{user_id}", response_model=UserSummary)
def update_admin_user(
    user_id: int,
    payload: UserUpdateRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    user = get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    try:
        user = update_user(
            session,
            user,
            username=payload.username,
            role_name=payload.role,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在") from exc
    return UserSummary.model_validate(to_user_summary(user))


@router.put("/users/{user_id}/password", response_model=UserSummary)
def reset_admin_user_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    user = get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    password = _extract_password(payload, "admin_reset_password")
    user = reset_user_password(session, user, password)
    return UserSummary.model_validate(to_user_summary(user))
