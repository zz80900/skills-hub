from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str = ""
    encrypted_password: str | None = None
    challenge_id: str | None = None
    client_ts: int | None = None
    nonce: str | None = None

    @property
    def is_encrypted(self) -> bool:
        return bool(self.encrypted_password)


class ChallengeResponse(BaseModel):
    challenge_id: str
    public_key_pem: str
    server_nonce: str
    expires_in_seconds: int
    algorithm: str


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
