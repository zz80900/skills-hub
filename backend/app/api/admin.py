from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.user import UserCreateRequest, UserPasswordResetRequest, UserSummary, UserUpdateRequest
from app.services.user_service import create_user, get_user_by_id, list_users, reset_user_password, to_user_summary, update_user


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserSummary])
def list_admin_users(session: DbSession, _: User = Depends(require_admin)):
    return [UserSummary.model_validate(to_user_summary(user)) for user in list_users(session)]


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_admin_user(
    payload: UserCreateRequest,
    session: DbSession,
    _: User = Depends(require_admin),
):
    try:
        user = create_user(session, payload.username, payload.password, payload.role, payload.is_active)
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
    user = reset_user_password(session, user, payload.password)
    return UserSummary.model_validate(to_user_summary(user))
