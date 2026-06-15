"""Криптографическое ядро для защищённого мессенджера.

Содержит функции для генерации соли, хеширования пароля через
PBKDF2-HMAC-SHA256 (100 000 итераций) и безопасного сравнения строк.
"""

import hashlib
import hmac
import os
import secrets


PBKDF2_ITERATIONS = 100_000
SALT_LEN = 16
HASH_LEN = 32
HASH_ALGO = "sha256"


def generate_salt() -> bytes:
    """Сгенерировать случайную соль длиной 16 байт."""
    return secrets.token_bytes(SALT_LEN)


def hash_password(password: bytes, salt: bytes) -> bytes:
    """Хешировать пароль с солью через PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        HASH_ALGO,
        bytes(password),
        bytes(salt),
        PBKDF2_ITERATIONS,
        dklen=HASH_LEN,
    )


def secure_compare(a: bytes, b: bytes) -> bool:
    """Сравнить две строки за постоянное время (защита от timing attack)."""
    return hmac.compare_digest(a, b)
