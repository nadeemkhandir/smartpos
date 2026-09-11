"""
"Forgot password" — reset straight from the sign-in screen, with no passcode.

Two steps, tied together by a :class:`ResetRequest`::

    request = password_reset_service.begin("nadeem")
    password_reset_service.set_new_password(request.ticket, new, confirm)

The ticket lives in this process only and expires, so step two cannot be called
for an account step one never looked up, and a dialog left open all afternoon
stops working.

**There is deliberately nothing here that proves who is asking.** Knowing a
username or an e-mail address is the whole requirement, so anyone who can reach
this screen can set the password of any account they can name — including a
manager's or an administrator's — and then sign in as them. That is the
behaviour this module was asked for; it is written down here so nobody has to
infer it from the code. Two things narrow it slightly, and neither is a
substitute for a second factor:

* only an approved, active account can be reset, so the queue and the disable
  switch still mean something;
* finishing a reset clears the account's lockout and any remembered terminal.

Nothing warns the account owner. SmartPOS sends no e-mail and no SMS, so a
reset done by somebody else leaves no trace outside the log file. If a second
factor or a warning is ever wanted, this is the module to put it in — the
sign-in path, the repository and the dialog all go through here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    AccountPendingError,
    AccountRejectedError,
    UserNotFoundError,
    ValidationError,
)
from app.core.logger import get_logger
from app.core.security import generate_token, validate_password_strength
from app.core.utils import (
    is_expired,
    minutes_from_now,
    seconds_until,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository, user_repository
from app.services.session_service import SessionService, session_service

logger = get_logger(__name__)

#: How long someone has to choose the new password once the account has been
#: found. Short, because the only thing standing between the ticket and a
#: changed password is the person at the keyboard.
TICKET_MINUTES = 10


@dataclass
class ResetRequest:
    """One in-progress password reset."""

    ticket: str
    username: str
    display_name: str
    expires_at: datetime

    user_id: int | None = field(default=None, repr=False)

    @property
    def seconds_remaining(self) -> int:
        return seconds_until(self.expires_at)

    @property
    def is_decoy(self) -> bool:
        """True when no account matched and the flow is only going through the motions."""
        return self.user_id is None


class PasswordResetService:
    """Finds an account by name, then lets its password be replaced."""

    def __init__(
        self,
        users: UserRepository | None = None,
        session: SessionService | None = None,
    ):
        self.users = users or user_repository
        self.session = session or session_service
        self.policy = settings.security

        # Tickets are touched from the UI thread and from worker threads.
        self._requests: dict[str, ResetRequest] = {}
        self._lock = threading.Lock()

    # ==================================================================
    # Step 1 — find the account
    # ==================================================================

    def begin(self, identifier: str) -> ResetRequest:
        """Look an account up by username or e-mail and open a reset ticket."""
        identifier = (identifier or "").strip()

        if not identifier:
            raise ValidationError("Enter your username or e-mail address.")

        user = self.users.get_by_identifier(identifier)

        if user is None:
            if self.policy.reveal_unknown_account:
                logger.warning("Password reset requested for unknown account %r", identifier)
                raise UserNotFoundError(
                    "No account matches that username or e-mail address. "
                    "Check the spelling, or ask a manager to look it up."
                )
            # Otherwise hand back a ticket that looks exactly like a real one
            # but can never be completed, so the screen reveals nothing.
            return self._decoy(identifier)

        self._assert_resettable(user)

        request = ResetRequest(
            ticket=generate_token(24),
            username=user.username,
            display_name=user.display_name,
            expires_at=minutes_from_now(TICKET_MINUTES),
            user_id=user.id,
        )

        logger.warning(
            "Password reset started for %s with no second factor — "
            "whoever is at this terminal can now set that password.",
            user.username,
        )
        return self._remember(request)

    # ==================================================================
    # Step 2 — set the new password
    # ==================================================================

    def set_new_password(self, ticket: str, new_password: str, confirm_password: str) -> User:
        """Save the new password and close the request."""
        request = self._require_request(ticket)

        if request.is_decoy:
            # Behave exactly as a real reset would, right up to the last moment.
            raise ValidationError(
                "That account could not be updated. Ask a manager to reset it for you."
            )

        if new_password != confirm_password:
            raise ValidationError("The two passwords do not match.")

        user = self.users.get_by_id(request.user_id)

        if user is None:
            self._forget(ticket)
            raise UserNotFoundError("That account no longer exists.")

        # Re-checked here and not only in begin(): the ticket may have been
        # sitting open while an administrator disabled the account.
        self._assert_resettable(user)

        validate_password_strength(new_password, username=user.username)

        # set_password also clears the lockout and every remembered terminal
        # for this account.
        self.users.set_password(user.id, new_password)
        self._forget(ticket)

        # If this terminal was remembering the account whose password just
        # changed, its token is now dead — drop it rather than retry with it.
        remembered = self.session.remembered_credentials()
        if remembered and remembered[0].lower() == user.username.lower():
            self.session.forget()

        logger.info("Password reset completed for %s", user.username)
        return self.users.get_by_id(user.id)

    def cancel(self, ticket: str) -> None:
        """Abandon a reset — the person closed the dialog."""
        self._forget(ticket)

    # ==================================================================
    # Internals
    # ==================================================================

    def _assert_resettable(self, user: User) -> None:
        """Refuse accounts that have no business being reset from this screen."""
        if user.is_pending:
            raise AccountPendingError(
                "This account is still waiting for approval, so its password "
                "cannot be reset yet."
            )

        if user.is_rejected:
            raise AccountRejectedError(
                "This registration was not approved, so its password cannot be reset."
            )

        if not user.is_active:
            raise AccountDisabledError(
                "This account has been deactivated, so its password cannot be reset. "
                "Contact an administrator."
            )

    def _decoy(self, identifier: str) -> ResetRequest:
        """A request for an account that does not exist.

        Used when ``REVEAL_UNKNOWN_ACCOUNT`` is off: the screen behaves exactly
        as it would for a real account, and simply never saves anything.
        """
        logger.warning("Password reset requested for unknown account %r (decoy issued)", identifier)

        return self._remember(
            ResetRequest(
                ticket=generate_token(24),
                username=identifier,
                display_name=identifier,
                expires_at=minutes_from_now(TICKET_MINUTES),
            )
        )

    def _remember(self, request: ResetRequest) -> ResetRequest:
        with self._lock:
            self._prune()
            self._requests[request.ticket] = request
        return request

    def _forget(self, ticket: str) -> None:
        with self._lock:
            self._requests.pop(ticket, None)

    def _require_request(self, ticket: str) -> ResetRequest:
        with self._lock:
            self._prune()
            request = self._requests.get(ticket)

        if request is None:
            raise ValidationError(
                "This password reset has timed out. Start again from “Forgot password?”."
            )
        return request

    def _prune(self) -> None:
        """Drop requests nobody finished. Caller holds the lock."""
        for ticket, request in list(self._requests.items()):
            if is_expired(request.expires_at):
                del self._requests[ticket]


#: Shared instance.
password_reset_service = PasswordResetService()
