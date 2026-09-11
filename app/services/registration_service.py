"""
Self-service sign-up, and the approval queue it feeds.

Someone at the terminal registers themselves; an administrator decides whether
they are actually staff. Those are the two halves of this module, and the
account row is the handover between them.

Signing up is a single call — fill the form in, and the account exists::

    user = registration_service.register(...)   # created as PENDING

The approval half is for whoever holds ``Permission.APPROVE_REGISTRATIONS``::

    registration_service.list_pending()
    registration_service.approve(user_id, role=Role.CASHIER)
    registration_service.reject(user_id, reason="Not a member of staff")

**Approval is the only gate.** Nothing is checked at sign-up time beyond the
shape of the fields and whether the username, e-mail and mobile number are
free — anybody can type anything into the form. What stops a stranger using the
till is that the account is created ``AccountStatus.PENDING`` and switched off,
and ``AuthService`` refuses it by name until somebody with the permission says
otherwise. The phone number on a self-registered account is therefore *claimed,
not proved*; only a number an administrator entered is marked verified.
"""

from __future__ import annotations

from app.core.account_status import AccountStatus
from app.core.config import settings
from app.core.exceptions import (
    DuplicateUserError,
    RegistrationError,
    UserNotFoundError,
    ValidationError,
)
from app.core.logger import get_logger
from app.core.phone import require_phone
from app.core.roles import Permission, Role
from app.core.security import validate_password_strength
from app.core.utils import is_email, normalise_email, normalise_username
from app.models.user import User
from app.repositories.user_repository import UserRepository, user_repository
from app.services.session_service import SessionService, session_service

logger = get_logger(__name__)

#: Usernames nobody may register, because they read as authority or collide
#: with the seeded account.
RESERVED_USERNAMES = {
    "admin", "administrator", "root", "system", "smartpos",
    "support", "manager", "owner", "superuser", "sysadmin",
}

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
MAX_FULL_NAME_LENGTH = 80


class RegistrationService:
    """Creates pending accounts, and admits or refuses them."""

    def __init__(
        self,
        users: UserRepository | None = None,
        session: SessionService | None = None,
    ):
        self.users = users or user_repository
        self.session = session or session_service
        self.rules = settings.registration

    @property
    def default_role(self) -> Role:
        """Role a newly approved account gets when the approver does not pick one."""
        return settings.registration_default_role

    # ==================================================================
    # Signing up
    # ==================================================================

    def register(
        self,
        *,
        full_name: str,
        username: str,
        email: str,
        phone: str,
        password: str,
        confirm_password: str,
    ) -> User:
        """Validate a sign-up and create the account, switched off and pending.

        Returns the new :class:`User`. It cannot sign in: that needs
        :meth:`approve`. Hashing the password is slow by design, so call this
        from a worker thread.
        """
        if not self.rules.enabled:
            raise RegistrationError(
                "Creating your own account is switched off on this terminal. "
                "Ask an administrator to make one for you."
            )

        full_name = self._clean_full_name(full_name)
        username = self._clean_username(username)
        email = self._clean_email(email)
        phone = require_phone(phone, default_country_code=settings.country_code)

        if password != confirm_password:
            raise ValidationError("The two passwords do not match.")

        validate_password_strength(password, username=username)

        self._assert_available(username=username, email=email, phone=phone)

        user = self.users.create(
            username=username,
            email=email,
            password=password,
            role=self.default_role,
            full_name=full_name,
            phone=phone,
            is_active=False,          # switched on by approve()
            status=AccountStatus.PENDING,
            # Nobody has proved this number belongs to whoever typed it. Only
            # an administrator entering one counts as vouching for it.
            phone_verified=False,
            must_change_password=False,
        )

        logger.info(
            "Sign-up received for %s (account %s) — awaiting approval", user.username, user.id
        )
        return user

    # ==================================================================
    # The approval queue
    # ==================================================================

    def list_pending(self) -> list[User]:
        """Everyone waiting on a decision, oldest first."""
        self._require(Permission.APPROVE_REGISTRATIONS)
        return self.users.list_pending()

    def pending_count(self) -> int:
        """How many are waiting — for a badge on the dashboard.

        Returns 0 rather than raising for anyone not allowed to approve, so a
        cashier's dashboard can call it without a permission check of its own.
        """
        user = self.session.current_user

        if user is None or not user.can(Permission.APPROVE_REGISTRATIONS):
            return 0

        return self.users.count(status=AccountStatus.PENDING)

    def approve(self, user_id: int, *, role: Role | str | None = None) -> User:
        """Let a pending sign-up in, with the role the approver chose."""
        self._require(Permission.APPROVE_REGISTRATIONS)

        approver = self.session.require_user()
        user = self._require_pending(user_id)

        role = Role.parse(role, default=self.default_role) if role is not None else self.default_role

        # Only an administrator may mint another administrator; a manager
        # approving staff must not be able to promote them past themselves.
        if role is Role.ADMIN and not approver.is_admin:
            raise PermissionError("Only an administrator can approve an administrator account.")

        approved = self.users.approve(user_id, role=role, approved_by=approver.id)

        logger.info(
            "%s approved the account %s as %s", approver.username, user.username, role.value
        )

        # Nobody is told. The person has to try signing in to find out, which
        # is why the queue shows their number: an approver can ring them.
        return approved

    def reject(self, user_id: int, *, reason: str = "") -> User:
        """Turn a sign-up down. The row stays so the name cannot be re-claimed."""
        self._require(Permission.APPROVE_REGISTRATIONS)

        approver = self.session.require_user()
        user = self._require_pending(user_id)

        rejected = self.users.reject(user_id, reason=reason, rejected_by=approver.id)

        logger.info(
            "%s rejected the account %s (%s)",
            approver.username,
            user.username,
            reason.strip() or "no reason given",
        )

        return rejected

    # ==================================================================
    # Internals
    # ==================================================================

    def _assert_available(self, *, username: str, email: str, phone: str) -> None:
        """Refuse a sign-up that collides with an account already on file.

        Checked here as well as by the UNIQUE indexes so the person is told
        *which* field clashes, rather than getting one message for all three.
        """
        if self.users.username_exists(username):
            raise DuplicateUserError(
                f"The username '{username}' is already taken. Please choose another."
            )

        if self.users.email_exists(email):
            raise DuplicateUserError(
                "That e-mail address is already registered. Use the sign-in screen, "
                "or 'Forgot password' if you cannot get in."
            )

        existing = self.users.get_by_phone(phone)

        if existing is not None:
            if existing.is_rejected:
                # Say no without explaining; the decision was already made and
                # re-litigating it at a till helps nobody.
                raise DuplicateUserError(
                    "That mobile number cannot be used to register. Speak to your manager."
                )
            raise DuplicateUserError(
                "That mobile number is already registered to an account."
            )

    def _require_pending(self, user_id: int) -> User:
        user = self.users.get_by_id(user_id)

        if user is None:
            raise UserNotFoundError("That account no longer exists.")

        if not user.is_pending:
            raise RegistrationError(
                f"{user.display_name} is not waiting for approval — "
                f"the account is already {user.status.label.lower()}."
            )

        return user

    def _require(self, permission: Permission) -> None:
        user = self.session.current_user

        if user is None:
            raise PermissionError("You must be signed in to do that.")

        if not user.can(permission):
            raise PermissionError(
                f"{user.role.label}s are not allowed to approve accounts. Ask an administrator."
            )

    # ---------------------------------------------------- field cleaning

    @staticmethod
    def _clean_full_name(value: str) -> str:
        name = " ".join((value or "").split())

        if not name:
            raise ValidationError("Please enter your full name.")

        if len(name) > MAX_FULL_NAME_LENGTH:
            raise ValidationError(f"Full name cannot be longer than {MAX_FULL_NAME_LENGTH} characters.")

        return name

    @staticmethod
    def _clean_username(value: str) -> str:
        username = normalise_username(value)

        if not username:
            raise ValidationError("Please choose a username.")

        if len(username) < MIN_USERNAME_LENGTH:
            raise ValidationError(f"Username must be at least {MIN_USERNAME_LENGTH} characters long.")

        if len(username) > MAX_USERNAME_LENGTH:
            raise ValidationError(f"Username cannot be longer than {MAX_USERNAME_LENGTH} characters.")

        if not all(character.isalnum() or character in "._-" for character in username):
            raise ValidationError(
                "Username can only contain letters, numbers, dots, dashes and underscores."
            )

        if not username[0].isalnum():
            raise ValidationError("Username must start with a letter or a number.")

        if username.lower() in RESERVED_USERNAMES:
            raise ValidationError("That username is reserved. Please choose another.")

        return username

    @staticmethod
    def _clean_email(value: str) -> str:
        email = normalise_email(value)

        if not email:
            raise ValidationError("Please enter your e-mail address.")

        if not is_email(email):
            raise ValidationError("Please enter a valid e-mail address.")

        return email


#: Shared instance.
registration_service = RegistrationService()
