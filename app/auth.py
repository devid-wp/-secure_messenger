"""Модуль аутентификации для защищённого мессенджера."""

from .crypto import generate_salt, hash_password, secure_compare

MIN_PASSWORD_LEN = 8


class AuthError(Exception):
    """Ошибка аутентификации (пустой логин, короткий пароль и т. п.)."""


def register_user(login: str, password: str) -> dict:
    """Зарегистрировать нового пользователя.

    Возвращает dict с ключами ``login``, ``hash`` (bytes), ``salt`` (bytes).
    """
    if not login:
        raise AuthError("Login must not be empty")
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(
            f"Password must be at least {MIN_PASSWORD_LEN} characters long"
        )

    salt = generate_salt()
    password_hash = hash_password(password.encode("utf-8"), salt)
    return {"login": login, "hash": password_hash, "salt": salt}


def verify_user(
    login: str,
    password: str,
    stored_hash: bytes,
    stored_salt: bytes,
) -> bool:
    """Проверить пароль пользователя по сохранённым hash и salt."""
    candidate = hash_password(password.encode("utf-8"), stored_salt)
    return secure_compare(candidate, bytes(stored_hash))
