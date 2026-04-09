import secrets
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class RSAKeyManager:
    """管理 RSA 密钥对，提供公钥 PEM 和解密能力。"""

    def __init__(self, private_key_pem: str | None = None) -> None:
        if private_key_pem:
            self._private_key = serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"),
                password=None,
            )
        else:
            self._private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=4096,
            )

    @property
    def public_key_pem(self) -> str:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def decrypt(self, encrypted_b64: str) -> str:
        ciphertext = _b64decode(encrypted_b64)
        plaintext = self._private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return plaintext.decode("utf-8")


class ChallengeStore:
    """内存中的 challenge 存储，支持一次性消费和自动过期。"""

    def __init__(self) -> None:
        self._challenges: dict[str, dict[str, Any]] = {}

    def create(self, ttl_seconds: int = 300) -> dict[str, Any]:
        challenge_id = uuid.uuid4().hex
        server_nonce = secrets.token_hex(16)
        created_at = time.time()
        challenge = {
            "challenge_id": challenge_id,
            "server_nonce": server_nonce,
            "expires_in": ttl_seconds,
            "created_at": created_at,
        }
        self._challenges[challenge_id] = challenge
        self._cleanup_expired()
        return challenge

    def consume(self, challenge_id: str) -> dict[str, Any] | None:
        self._cleanup_expired()
        return self._challenges.pop(challenge_id, None)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            cid
            for cid, c in self._challenges.items()
            if now > c["created_at"] + c["expires_in"]
        ]
        for cid in expired:
            del self._challenges[cid]


_key_manager: RSAKeyManager | None = None
_challenge_store: ChallengeStore | None = None


def initialize_key_manager(settings) -> RSAKeyManager:
    global _key_manager
    _key_manager = RSAKeyManager(settings.rsa_private_key_pem)
    return _key_manager


def initialize_challenge_store() -> ChallengeStore:
    global _challenge_store
    _challenge_store = ChallengeStore()
    return _challenge_store


def get_key_manager() -> RSAKeyManager:
    if _key_manager is None:
        raise RuntimeError("RSAKeyManager 尚未初始化，请在 lifespan 中调用 initialize_key_manager()")
    return _key_manager


def get_challenge_store() -> ChallengeStore:
    if _challenge_store is None:
        raise RuntimeError("ChallengeStore 尚未初始化，请在 lifespan 中调用 initialize_challenge_store()")
    return _challenge_store


def _b64decode(value: str) -> bytes:
    import base64
    return base64.b64decode(value)
