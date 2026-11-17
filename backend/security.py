import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from backend.config import settings


def digest(value: str) -> str:
    return hmac.new(
        settings().key_hash_secret.get_secret_value().encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def make_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "MELKA-" + "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def encrypt(value: str) -> str:
    return (
        Fernet(settings().key_encryption_secret.get_secret_value().encode()).encrypt(value.encode()).decode()
    )


def decrypt(value: str) -> str:
    return (
        Fernet(settings().key_encryption_secret.get_secret_value().encode()).decrypt(value.encode()).decode()
    )
