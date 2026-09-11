"""
User administration: creating staff accounts, changing roles, deactivating.

Everything here is permission-checked against the *acting* user, so a screen
cannot skip the check by calling the repository directly. Sign-in itself is not
here — that lives in :mod:`app.services.auth_service`.
"""

from __future__ import annotations

from app.core.exceptions import ValidationError
from app.core.logger import get_logger
from app.core.roles import Permission, Role
from app.core.security import generate_token, validate_password_strength
from app.core.utils import is_email, normalise_email, normalise_username
from app.models.user import User
from app.repositories.user_repository import UserRepository, user_repository
from app.services.session_service import SessionService, session_service

logger = get_logger(__name__)


class UserService:
    """Account management for administrators and managers."""

    def __init__(
        self,
        users: UserRepository | None = None,
        session: SessionService | None = None,
    ):
        self.users = users or user_repository
        self.session = session or session_service

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_users(self, **filters) -> list[User]:
        self._require(Permission.MANAGE_USERS)
        return self.users.list_users(**filters)

    def get(self, user_id: int) -> User | None:
        self._require(Permission.MANAGE_USERS)
        return self.users.get_by_id(user_id)

    def counts_by_role(self) -> dict[Role, int]:
        """Head-count per role, for an admin overview panel."""
        self._require(Permission.MANAGE_USERS)
        return {role: self.users.count(role=role) for role in Role}

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password: str | None = None,
        role: Role | str = Role.CASHIER,
        full_name: str = "",
        phone: str | None = None,
        must_change_password: bool = True,
    ) -> tuple[User, str]:
        """Add a staff account.

        Returns the new user together with the password it was given, so a
        generated one can be read out once and then forgotten. Pass ``password``
        to choose it yourself; leave it out and a strong temporary one is made.
        """
        self._require(Permission.MANAGE_USERS)

        role = Role.parse(role, default=Role.CASHIER)
        username = normalise_username(username)
        email = normalise_email(email)

        if not is_email(email):
            raise ValidationError("Please enter a valid e-mail address.")

        if password is None:
            password = self.generate_temporary_password()
        else:
            validate_password_strength(password, username=username)

        user = self.users.create(
            username=username,
            email=email,
            password=password,
            role=role,
            full_name=full_name,
            phone=phone,
            # An administrator typed this number, which is the same standard of
            # proof the self-service flow reaches with a texted code. Without
            # this the account could never reset its own password, because
            # reset codes go by SMS and only to a confirmed number.
            phone_verified=bool(phone),
            must_change_password=must_change_password,
        )

        logger.info(
            "%s created the account %s (%s)",
            self.session.require_user().username,
            user.username,
            role.value,
        )
        return user, password

    def update_user(self, user_id: int, **fields) -> User | None:
        self._require(Permission.MANAGE_USERS)

        if "role" in fields and fields["role"] is not None:
            self._assert_not_last_admin_change(user_id, Role.parse(fields["role"]))

        return self.users.update_profile(user_id, **fields)

    def set_active(self, user_id: int, active: bool) -> None:
        self._require(Permission.MANAGE_USERS)

        if not active:
            self._assert_not_self(user_id, "deactivate your own account")
            self._assert_not_last_admin(user_id)

        self.users.set_active(user_id, active)
        logger.info("Account %s %s", user_id, "activated" if active else "deactivated")

    def delete_user(self, user_id: int) -> bool:
        self._require(Permission.MANAGE_USERS)
        self._assert_not_self(user_id, "delete your own account")
        self._assert_not_last_admin(user_id)

        logger.info("Account %s deleted by %s", user_id, self.session.require_user().username)
        return self.users.delete(user_id)

    def unlock_user(self, user_id: int) -> None:
        """Clear a lockout so someone can try again straight away."""
        self._require(Permission.RESET_PASSWORDS)
        self.users.clear_lockout(user_id)
        logger.info("Lockout cleared for account %s", user_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_temporary_password() -> str:
        """A random password that always satisfies the strength rules."""
        return f"Sp{generate_token(9)}7"

    def _require(self, permission: Permission) -> None:
        user = self.session.current_user

        if user is None:
            raise PermissionError("You must be signed in to manage users.")

        if not user.can(permission):
            raise PermissionError(
                f"{user.role.label}s are not allowed to do that. Ask an administrator."
            )

    def _assert_not_self(self, user_id: int, action: str) -> None:
        current = self.session.current_user
        if current and current.id == user_id:
            raise ValidationError(f"You cannot {action}.")

    def _assert_not_last_admin(self, user_id: int) -> None:
        """Refuse to remove the only way back into the system."""
        target = self.users.get_by_id(user_id)

        if target and target.is_admin and self.users.count(role=Role.ADMIN, active_only=True) <= 1:
            raise ValidationError(
                "This is the only active administrator. Promote another account first."
            )

    def _assert_not_last_admin_change(self, user_id: int, new_role: Role) -> None:
        if new_role is not Role.ADMIN:
            self._assert_not_last_admin(user_id)


#: Shared instance.
user_service = UserService()
