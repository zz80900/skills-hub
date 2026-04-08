from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_user
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import AuthenticatedUser, LoginRequest, LoginResponse, MessageResponse
from app.services.user_service import authenticate_user, to_authenticated_user


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: DbSession):
    user = authenticate_user(session, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return LoginResponse(
        access_token=create_access_token(user.id, user.username, user.role.name),
        user=AuthenticatedUser.model_validate(to_authenticated_user(user)),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(_: User = Depends(get_current_user)):
    return MessageResponse(message="已退出登录")


@router.get("/me", response_model=AuthenticatedUser)
def me(current_user: User = Depends(get_current_user)):
    return AuthenticatedUser.model_validate(to_authenticated_user(current_user))
