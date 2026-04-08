from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthenticatedUser(BaseModel):
    id: int
    username: str
    role: str
    source: str
    display_name: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthenticatedUser


class MessageResponse(BaseModel):
    message: str
