"""
Password hashing and "remember me" tokens.

Nothing reversible is ever stored. Passwords go through PBKDF2-HMAC-SHA256 with
a per-user random salt; remember-me tokens are stored as SHA-256 digests, so a
stolen copy of ``smartpos.db`` still cannot be used to sign in.

Only the standard library is used, which keeps the project installable with
nothing but PySide6 — no compiled bcrypt/argon2 wheel to ship to each till.

Hash format (a single self-describing column value)::

    pbkdf2_sha256$240000$<salt-b64>$<derived-key-b64>

The iteration count travels with the hash, so raising the cost later does not
invalidate existing passwords: ``needs_rehash`` spots the old ones and they are
upgraded silently on the owner's next successful sign-in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.core.config import settings
from app.core.exceptions import ValidationError

ALGORITHM = "pbkdf2_sha256"


# ------------------------------------------------------------------
# Passwords
# ------------------------------------------------------------------


def hash_password(password: str, *, iterations: int | None = None) -> str:
    """Derive a storable hash for ``password``."""
    if not password:
        raise ValidationError("Password cannot be empty.")

    iterations = iterations or settings.security.pbkdf2_iterations
    salt = secrets.token_bytes(settings.security.salt_bytes)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    return "{}${}${}${}".format(
        ALGORITHM,
        iterations,
        _b64(salt),
        _b64(derived),
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Check ``password`` against a stored hash in constant time.

    Returns False for anything malformed rather than raising: a corrupt row
    should read as "wrong password", not crash the sign-in screen.
    """
    if not password or not stored:
        return False

    try:
        algorithm, raw_iterations, raw_salt, raw_hash = stored.split("$")
        if algorithm != ALGORITHM:
            return False

        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _unb64(raw_salt),
            int(raw_iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(derived, _unb64(raw_hash))


def needs_rehash(stored: str | None) -> bool:
    """True when a hash was made with an older algorithm or a lower cost."""
    if not stored:
        return True

    try:
        algorithm, raw_iterations, _, _ = stored.split("$")
    except ValueError:
        return True

    if algorithm != ALGORITHM:
        return True

    try:
        return int(raw_iterations) < settings.security.pbkdf2_iterations
    except ValueError:
        return True


def validate_password_strength(password: str, *, username: str = "") -> None:
    """Raise :class:`ValidationError` describing the first unmet rule.

    Deliberately short: staff choose these at a counter, and a rule nobody can
    satisfy just becomes a sticky note on the monitor.
    """
    minimum = settings.security.min_password_length

    if not password:
        raise ValidationError("Please choose a password.")

    if len(password) < minimum:
        raise ValidationError(f"Password must be at least {minimum} characters long.")

    if password.strip() != password:
        raise ValidationError("Password cannot start or end with a space.")

    if not any(character.isalpha() for character in password):
        raise ValidationError("Password must contain at least one letter.")

    if not any(character.isdigit() for character in password):
        raise ValidationError("Password must contain at least one number.")

    if username and password.lower() == username.strip().lower():
        raise ValidationError("Password cannot be the same as the username.")

    if password.lower() in _COMMON_PASSWORDS:
        raise ValidationError("That password is too common. Please choose another.")


def password_strength(password: str) -> tuple[int, str]:
    """Score a password 0-4 with a one-word verdict, for a live meter."""
    if not password:
        return 0, "Empty"

    score = 0
    if len(password) >= settings.security.min_password_length:
        score += 1
    if len(password) >= 12:
        score += 1
    if any(c.isalpha() for c in password) and any(c.isdigit() for c in password):
        score += 1
    if any(not c.isalnum() for c in password):
        score += 1
    if password.lower() in _COMMON_PASSWORDS:
        score = min(score, 1)

    return score, ("Very weak", "Weak", "Fair", "Good", "Strong")[score]


_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789",
    "qwerty123", "letmein1", "welcome1", "admin123", "smartpos1",
    "iloveyou1", "abc12345", "1q2w3e4r",
}


# ------------------------------------------------------------------
# Opaque tokens ("remember me", reset tickets)
# ------------------------------------------------------------------


def generate_token(byte_length: int = 32) -> str:
    """A URL-safe random secret. This is the only copy the client keeps."""
    return secrets.token_urlsafe(byte_length)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, stored_hash: str | None) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_token(token), stored_hash)


# ------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))
