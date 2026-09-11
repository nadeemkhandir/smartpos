"""
Sign-in, sign-out, automatic sign-in and password changes.

This is the only module allowed to decide that a set of credentials is good.
Screens call it, it returns a :class:`User` or raises one of the errors in
``app.core.exceptions`` with a message already written for the person at the
terminal.

**"Remember me" is currently dormant.** The sign-in screen no longer offers it,
so nothing passes ``remember=True`` and no tokens are issued;
:meth:`AuthService.discard_remembered_terminal` clears any an earlier build
left behind. The mechanism itself is kept and still works — restoring it means
putting the checkbox back on the sign-in screen, passing its value through to
:meth:`login`, and calling :meth:`login_with_remembered_token` at start-up
instead of discarding.

Two rules shape the code below:

* **Fail identically.** An unknown username and a wrong password produce the
  same error and take the same amount of time, so the form cannot be used to
  discover who has an account.
* **Never trust the caller.** Lockouts, active flags and token expiry are all
  re-checked here, not in the widget that happens to call in.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    AccountLockedError,
    AccountPendingError,
    AccountRejectedError,
    InvalidCredentialsError,
    ValidationError,
)
from app.core.logger import get_logger
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.core.utils import days_from_now, humanise_seconds, is_expired, minutes_from_now
from app.models.user import User
from app.repositories.user_repository import UserRepository, user_repository
from app.services.session_service import SessionService, session_service

logger = get_logger(__name__)

#: Verified against when no account matched, purely so that a failed sign-in
#: costs the same time whether or not the username exists.
_DUMMY_HASH = hash_password("smartpos-timing-equaliser")


class AuthService:
    """Credential checking and session lifecycle."""

    def __init__(
        self,
        users: UserRepository | None = None,
        session: SessionService | None = None,
    ):
        self.users = users or user_repository
        self.session = session or session_service
        self.policy = settings.security

    # ==================================================================
    # Sign in
    # ==================================================================

    def login(self, identifier: str, password: str, *, remember: bool = False) -> User:
        """Sign a user in with a username-or-e-mail and a password.

        On success the live session is started, the failure counter is cleared
        and — when ``remember`` is set — a rotation token is issued for this
        terminal.
        """
        identifier = (identifier or "").strip()

        if not identifier or not password:
            raise ValidationError("Please enter both your username and password.")

        user = self.users.get_by_identifier(identifier, with_secrets=True)

        if user is None:
            # Spend the same time as a real check before refusing.
            verify_password(password, _DUMMY_HASH)
            logger.warning("Sign-in refused: no account matches %r", identifier)
            raise InvalidCredentialsError()

        self._assert_not_locked(user)

        if not verify_password(password, user.password_hash):
            self._register_failure(user)
            raise InvalidCredentialsError()

        # The password is right; only now do admission and the on/off switch
        # matter, so these messages cannot be used to probe for valid usernames.
        self._assert_admitted(user)

        if not user.is_active:
            logger.warning("Sign-in refused: %s is deactivated", user.username)
            raise AccountDisabledError()

        self._finish_login(user, remember=remember, rehash_password=password)

        logger.info("%s signed in as %s", user.username, user.role.value)
        return self.session.current_user

    def login_with_remembered_token(self) -> User | None:
        """Sign in from this terminal's stored token, if it still holds.

        Returns None — never raises — when there is nothing valid to use, so
        start-up can simply fall through to the sign-in screen.

        Nothing calls this at the moment: see the note at the top of the module
        about "Remember me" being dormant. It is kept working so that putting
        the option back is a change to the sign-in screen, not a rewrite here.
        """
        credentials = self.session.remembered_credentials()
        if credentials is None:
            return None

        username, token = credentials
        user = self.users.get_by_remember_hash(hash_token(token), with_secrets=True)

        if user is None or user.username.lower() != username.lower():
            logger.info("Stored sign-in token no longer matches any account; discarding it.")
            self.session.forget()
            return None

        if is_expired(user.remember_expires_at):
            logger.info("Stored sign-in token for %s has expired.", user.username)
            self.users.clear_remember_token(user.id)
            self.session.forget()
            return None

        if not user.can_sign_in:
            logger.warning(
                "Automatic sign-in refused for %s (status %s, active=%s, locked=%s).",
                user.username,
                user.status.value,
                user.is_active,
                user.is_locked,
            )
            self.session.forget()
            return None

        if user.must_change_password:
            # A forced password change has to happen at the keyboard.
            logger.info("Automatic sign-in skipped for %s: password change required.", user.username)
            return None

        self._finish_login(user, remember=True)

        logger.info("%s signed in automatically on this terminal.", user.username)
        return self.session.current_user

    def discard_remembered_terminal(self) -> None:
        """Revoke whatever this terminal had stored, without signing anyone in.

        Called at start-up. Nothing issues these tokens any more — the sign-in
        screen has no "Remember me" — but a terminal that ran an earlier build
        may still hold one, and there is no longer any switch to turn it off
        with, so it is cleared instead of honoured.
        """
        credentials = self.session.remembered_credentials()

        if credentials is None:
            return

        username, token = credentials
        user = self.users.get_by_remember_hash(hash_token(token))

        if user is not None:
            self.users.clear_remember_token(user.id)

        self.session.forget()
        logger.info("Discarded the sign-in token this terminal held for %s.", username)

    def logout(self, *, forget_terminal: bool = True) -> None:
        """End the session. By default this terminal also stops remembering."""
        user = self.session.current_user

        if user and forget_terminal:
            self.users.clear_remember_token(user.id)

        if forget_terminal:
            self.session.forget()

        self.session.end()

    # ==================================================================
    # Passwords
    # ==================================================================

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        """Change a password after re-checking the current one."""
        user = self.users.get_by_id(user_id, with_secrets=True)

        if user is None:
            raise InvalidCredentialsError("That account no longer exists.")

        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Your current password is not correct.")

        if current_password == new_password:
            raise ValidationError("The new password must be different from the current one.")

        validate_password_strength(new_password, username=user.username)
        self.users.set_password(user_id, new_password)

        # set_password wipes the remembered token, so this terminal must forget
        # its copy too or it will keep offering a token the row no longer knows.
        if self.session.current_user and self.session.current_user.id == user_id:
            self.session.forget()

        logger.info("Password changed for %s", user.username)

    def admin_set_password(
        self,
        target_user_id: int,
        new_password: str,
        *,
        must_change: bool = True,
    ) -> None:
        """Set someone else's password, e.g. from a user-management screen.

        The caller is responsible for checking ``Permission.RESET_PASSWORDS``;
        this method only enforces the password rules.
        """
        user = self.users.get_by_id(target_user_id)
        if user is None:
            raise ValidationError("That account no longer exists.")

        validate_password_strength(new_password, username=user.username)
        self.users.set_password(target_user_id, new_password, must_change=must_change)

        logger.info("Password reset for %s by an administrator.", user.username)

    # ==================================================================
    # Internals
    # ==================================================================

    def _assert_not_locked(self, user: User) -> None:
        if not user.is_locked:
            return

        remaining = user.lock_seconds_remaining
        logger.warning("Sign-in refused: %s is locked for another %ss", user.username, remaining)

        raise AccountLockedError(
            "Too many failed attempts. Try again in "
            f"{humanise_seconds(remaining)}, or ask a manager to unlock the account.",
            seconds_remaining=remaining,
        )

    def _assert_admitted(self, user: User) -> None:
        """Refuse an account that was never let in.

        Only reached once the password has already been checked, so naming the
        exact state here tells the right person something useful without
        telling a stranger which usernames exist.
        """
        if user.is_pending:
            logger.warning("Sign-in refused: %s is still awaiting approval", user.username)
            raise AccountPendingError()

        if user.is_rejected:
            logger.warning("Sign-in refused: %s was rejected", user.username)
            raise AccountRejectedError()

    def _register_failure(self, user: User) -> None:
        """Count a bad password and lock the account once the limit is hit."""
        attempts = user.failed_attempts + 1
        lock_until = None

        if attempts >= self.policy.max_failed_attempts:
            lock_until = minutes_from_now(self.policy.lockout_minutes)

        self.users.register_failed_attempt(user.id, lock_until=lock_until)

        if lock_until is not None:
            logger.warning(
                "%s locked out for %s minutes after %s failed attempts.",
                user.username,
                self.policy.lockout_minutes,
                attempts,
            )
            raise AccountLockedError(
                f"Too many failed attempts. This account is locked for "
                f"{self.policy.lockout_minutes} minutes.",
                seconds_remaining=self.policy.lockout_minutes * 60,
            )

        logger.warning("Wrong password for %s (attempt %s).", user.username, attempts)

    def _finish_login(
        self,
        user: User,
        *,
        remember: bool,
        rehash_password: str | None = None,
    ) -> None:
        """Shared tail of every successful sign-in."""
        self.users.register_successful_login(user.id)

        # Quietly upgrade a hash made with a lower cost, now that the plain
        # password is in hand and known to be correct.
        if rehash_password and needs_rehash(user.password_hash):
            self.users.rehash_password(user.id, hash_password(rehash_password))
            logger.info("Upgraded the stored password hash for %s.", user.username)

        if remember:
            self._issue_remember_token(user)
        else:
            self.users.clear_remember_token(user.id)
            self.session.forget()
            self.session.set_remembered_username(None)

        # Re-read so the session carries the freshly written last_login_at.
        refreshed = self.users.get_by_id(user.id) or user
        self.session.start(refreshed)

    def _issue_remember_token(self, user: User) -> None:
        """Mint a new token for this terminal, invalidating the previous one."""
        token = generate_token()

        self.users.store_remember_token(
            user.id,
            hash_token(token),
            days_from_now(self.policy.remember_days),
        )
        self.session.remember(user.username, token)


#: Shared instance.
auth_service = AuthService()
