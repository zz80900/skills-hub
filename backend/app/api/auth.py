import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_user
from app.core.config import get_settings
from app.core.encryption import DecryptionError, decrypt_and_validate
from app.core.rsa import get_challenge_store, get_key_manager
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import AuthenticatedUser, ChallengeResponse, LoginRequest, LoginResponse, MessageResponse
from app.services.ad_auth import ActiveDirectoryUnavailableError
from app.services.user_service import authenticate_user, to_authenticated_user


router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/challenge", response_model=ChallengeResponse)
def get_challenge():
    settings = get_settings()
    key_manager = get_key_manager()
    store = get_challenge_store()
    challenge = store.create(ttl_seconds=settings.challenge_ttl_seconds)
    return ChallengeResponse(
        challenge_id=challenge["challenge_id"],
        public_key_pem=key_manager.public_key_pem,
        server_nonce=challenge["server_nonce"],
        expires_in_seconds=challenge["expires_in"],
        algorithm="RSA-OAEP-SHA256",
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: DbSession):
    if payload.is_encrypted:
        try:
            decrypted = decrypt_and_validate(
                encrypted_password=payload.encrypted_password,
                challenge_id=payload.challenge_id,
                client_ts=payload.client_ts,
                nonce=payload.nonce,
                key_manager=get_key_manager(),
                challenge_store=get_challenge_store(),
                expected_purpose="login",
                max_clock_skew=get_settings().rsa_max_clock_skew_seconds,
            )
            password = decrypted.password
        except DecryptionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    else:
        password = payload.password

    try:
        user = authenticate_user(session, payload.username, password)
    except ActiveDirectoryUnavailableError as exc:
        logger.warning("AD authentication unavailable during login for username=%s: %s", payload.username, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AD 认证服务暂不可用") from exc
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
