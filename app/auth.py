from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .crypto import hash_password as legacy_hash_password
from .crypto import secure_compare


MIN_PASSWORD_LEN = 8
ARGON2 = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


class AuthError(Exception):
    pass


def validate_credentials(login: str, password: str) -> str:
    normalized_login = login.strip()
    if not normalized_login:
        raise AuthError("Login must not be empty")
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(
            f"Password must be at least {MIN_PASSWORD_LEN} characters long"
        )
    return normalized_login


def register_user(login: str, password: str) -> dict[str, str]:
    normalized_login = validate_credentials(login, password)
    return {"login": normalized_login, "hash": ARGON2.hash(password)}


def verify_password(
    password: str,
    stored_hash: bytes | str,
    stored_salt: bytes | None,
) -> tuple[bool, str | None]:
    encoded_hash = (
        stored_hash.decode("utf-8")
        if isinstance(stored_hash, (bytes, bytearray, memoryview))
        else stored_hash
    )
    if encoded_hash.startswith("$argon2id$"):
        try:
            valid = ARGON2.verify(encoded_hash, password)
            replacement = ARGON2.hash(password) if ARGON2.check_needs_rehash(encoded_hash) else None
            return valid, replacement
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, None

    if not stored_salt:
        return False, None
    candidate = legacy_hash_password(password.encode("utf-8"), bytes(stored_salt))
    if not secure_compare(candidate, bytes(stored_hash)):
        return False, None
    return True, ARGON2.hash(password)
