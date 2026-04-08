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


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "USER"
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None


class UserPasswordResetRequest(BaseModel):
    password: str
