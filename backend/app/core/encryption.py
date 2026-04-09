from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.core.rsa import RSAKeyManager, ChallengeStore


VALID_PURPOSES = {"login", "admin_create_user", "admin_reset_password"}


class DecryptionError(Exception):
    """解密或验证失败时抛出的异常。"""
    pass


@dataclass
class DecryptedPayload:
    password: str
    username: str
    user_id: str
    purpose: str
    challenge_id: str
    server_nonce: str
    client_ts: int
    nonce: str


def decrypt_and_validate(
    encrypted_password: str,
    challenge_id: str,
    client_ts: int,
    nonce: str,
    key_manager: RSAKeyManager,
    challenge_store: ChallengeStore,
    expected_purpose: str,
    max_clock_skew: int = 30,
) -> DecryptedPayload:
    """解密前端 RSA-OAEP 加密的密码并验证挑战参数。"""
    challenge = challenge_store.consume(challenge_id)
    if challenge is None:
        raise DecryptionError("安全验证已过期，请刷新页面")

    try:
        plaintext = key_manager.decrypt(encrypted_password)
    except Exception:
        raise DecryptionError("安全验证失败")

    try:
        data = json.loads(plaintext)
    except json.JSONDecodeError:
        raise DecryptionError("安全验证失败")

    purpose = data.get("purpose", "")
    if purpose != expected_purpose:
        raise DecryptionError("安全验证失败")

    if data.get("server_nonce") != challenge["server_nonce"]:
        raise DecryptionError("安全验证失败")

    now = int(time.time())
    ttl = challenge["expires_in"]
    if client_ts < now - (ttl + max_clock_skew) or client_ts > now + max_clock_skew:
        raise DecryptionError("安全验证已过期，请刷新页面")

    if not nonce or not isinstance(nonce, str):
        raise DecryptionError("安全验证失败")

    return DecryptedPayload(
        password=data.get("password", ""),
        username=data.get("username", ""),
        user_id=str(data.get("user_id", "")),
        purpose=purpose,
        challenge_id=challenge_id,
        server_nonce=challenge["server_nonce"],
        client_ts=client_ts,
        nonce=nonce,
    )
