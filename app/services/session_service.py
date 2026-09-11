"""
Who is signed in on this terminal, and what it remembers between runs.

Two separate jobs, deliberately kept together because they are two views of the
same question:

* **The live session** — the :class:`User` currently signed in, held in memory
  only, gone the moment the process exits.
* **"Remember me"** — a long-lived random token stored in ``QSettings``
  (the Windows registry under ``HKCU\\Software\\SmartPOS``) whose SHA-256 digest
  is kept on the user's row. The token here is useless without the matching row,
  and the row cannot reveal the token, so a copy of either half alone gets
  nobody in.

The token is *rotated* on every automatic sign-in: the old one stops working the
instant it is used, which turns a stolen token into a single-use item that also
locks the thief out as soon as the real user comes back.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from app.core.config import settings
from app.core.logger import get_logger
from app.models.user import User

logger = get_logger(__name__)

# QSettings keys, in one place so nothing goes hunting for a string literal.
KEY_REMEMBER_TOKEN = "auth/remember_token"
KEY_REMEMBER_USERNAME = "auth/remembered_username"
KEY_LAST_USERNAME = "auth/last_username"


class SessionService:
    """The signed-in user plus this terminal's persisted sign-in state."""

    def __init__(self):
        self._settings = QSettings(settings.organisation, settings.app_name)
        self._user: User | None = None

    # ------------------------------------------------------------------
    # Live session
    # ------------------------------------------------------------------

    @property
    def current_user(self) -> User | None:
        return self._user

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None

    def start(self, user: User) -> None:
        """Mark a user as signed in on this terminal."""
        self._user = user.scrubbed()
        self._settings.setValue(KEY_LAST_USERNAME, user.username)
        logger.info("Session started for %s (%s)", user.username, user.role.value)

    def end(self) -> None:
        """Clear the live session. Does not touch the remembered token."""
        if self._user:
            logger.info("Session ended for %s", self._user.username)
        self._user = None

    def require_user(self) -> User:
        """The signed-in user, or an error — for code that cannot run without one."""
        if self._user is None:
            raise PermissionError("No user is signed in.")
        return self._user

    def can(self, permission) -> bool:
        """Permission check for the current user; False when nobody is signed in."""
        return self._user is not None and self._user.can(permission)

    # ------------------------------------------------------------------
    # "Remember me"
    # ------------------------------------------------------------------

    def remember(self, username: str, token: str) -> None:
        """Persist a freshly issued token for the next launch."""
        self._settings.setValue(KEY_REMEMBER_USERNAME, username)
        self._settings.setValue(KEY_REMEMBER_TOKEN, token)
        self._settings.sync()

    def remembered_credentials(self) -> tuple[str, str] | None:
        """The stored ``(username, token)`` pair, or None if there is none."""
        username = self._settings.value(KEY_REMEMBER_USERNAME, "", type=str)
        token = self._settings.value(KEY_REMEMBER_TOKEN, "", type=str)

        if username and token:
            return username, token
        return None

    def forget(self, *, keep_username: bool = True) -> None:
        """Drop the token so the next launch asks for a password again.

        The username is kept by default: it stays useful for pre-filling the
        sign-in box, and it is not a secret.
        """
        self._settings.remove(KEY_REMEMBER_TOKEN)
        if not keep_username:
            self._settings.remove(KEY_REMEMBER_USERNAME)
        self._settings.sync()

    # ------------------------------------------------------------------
    # Convenience for the sign-in screen
    # ------------------------------------------------------------------

    def suggested_username(self) -> str:
        """Pre-fill value for the username box."""
        return (
            self._settings.value(KEY_REMEMBER_USERNAME, "", type=str)
            or self._settings.value(KEY_LAST_USERNAME, "", type=str)
        )

    def set_remembered_username(self, username: str | None) -> None:
        if username:
            self._settings.setValue(KEY_REMEMBER_USERNAME, username)
        else:
            self._settings.remove(KEY_REMEMBER_USERNAME)
        self._settings.sync()


#: Shared instance — the whole application has exactly one session.
session_service = SessionService()
