"""
core/crypto.py
──────────────
Transparent encryption at rest for secret columns.

OAuth access tokens are bearer credentials for a user's ad account: anyone
holding one can spend that account's money. They were stored as plaintext
``Text``, so a database dump, a read-replica, or a backup file handed to the
wrong person was a full compromise of every connected Meta account.

``EncryptedString`` is a SQLAlchemy ``TypeDecorator``: models declare it in place
of ``Text`` and every read/write goes through Fernet (AES-128-CBC + HMAC)
automatically. No call site changes — ``token.access_token`` still returns the
token.

The key is derived from ``SECRET_KEY`` rather than configured separately, so
there is no second secret to distribute. **Rotating SECRET_KEY makes stored
tokens unreadable**; those rows decrypt to ``None`` and the user reconnects Meta,
which is the safe failure and the reason decryption never raises.

Values written before this type existed are plaintext and are returned as-is —
that is what lets the migration re-encrypt them in place without a flag day.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    """A Fernet built from SECRET_KEY.

    Fernet wants 32 url-safe base64 bytes; SECRET_KEY is an arbitrary string, so
    it is hashed to exactly that. The digest is not a KDF — SECRET_KEY is already
    a high-entropy deployment secret, not a password.
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str | None:
    """Plaintext, or ``None`` when the value cannot be decrypted."""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def looks_encrypted(value: str) -> bool:
    """Is this a Fernet token we can read? Used to leave legacy plaintext alone.

    Checked by decrypting rather than by shape: a Meta access token is opaque
    base64-ish text and any prefix test would eventually misfire on one.
    """
    return decrypt(value) is not None


class EncryptedString(TypeDecorator):
    """``Text`` that is encrypted in the database and plain in Python."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plain = decrypt(value)
        if plain is not None:
            return plain
        # Either written before this column was encrypted, or encrypted under a
        # SECRET_KEY that has since changed. Returning it unchanged keeps legacy
        # rows working; a rotated key yields a token Meta rejects, and the user
        # is asked to reconnect.
        return value
