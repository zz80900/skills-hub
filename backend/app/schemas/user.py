from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    source: str
    display_name: str | None = None
    external_principal: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserSummary]
    page: int
    page_size: int
    total: int
    has_more: bool


class UserCreateRequest(BaseModel):
    username: str
    password: str = ""
    encrypted_password: str | None = None
    challenge_id: str | None = None
    client_ts: int | None = None
    nonce: str | None = None
    role: str = "USER"
    is_active: bool = True

    @property
    def is_encrypted(self) -> bool:
        return bool(self.encrypted_password)


class UserUpdateRequest(BaseModel):
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None


class UserPasswordResetRequest(BaseModel):
    password: str = ""
    encrypted_password: str | None = None
    challenge_id: str | None = None
    client_ts: int | None = None
    nonce: str | None = None

    @property
    def is_encrypted(self) -> bool:
        return bool(self.encrypted_password)
