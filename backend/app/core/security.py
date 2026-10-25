"""Security primitives: password hashing, token creation and verification.

Placeholder functions are intentionally unimplemented so the dependency choice
(passlib/argon2, PyJWT, ...) is made once, in one file.
"""

from datetime import datetime, timedelta, timezone


def hash_password(plain_password: str) -> str:
    raise NotImplementedError("Choose a hashing library (argon2-cffi or passlib).")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    raise NotImplementedError("Pair with hash_password once a library is chosen.")


def create_access_token(subject: str, expires_minutes: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    raise NotImplementedError(f"Encode token for {subject!r}, expiring {expires_at}.")
