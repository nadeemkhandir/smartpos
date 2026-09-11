"""
Errors raised by the service layer.

Each carries a message written for the person at the terminal, so a screen can
show ``str(error)`` without translating anything.
"""

from __future__ import annotations


class SmartPOSError(Exception):
    """Base class for every error SmartPOS raises deliberately."""


class DatabaseError(SmartPOSError):
    """The database could not be opened, migrated or written to."""


class ValidationError(SmartPOSError):
    """User-supplied input failed a rule (blank field, weak password, ...)."""


class AuthenticationError(SmartPOSError):
    """Sign-in was refused."""


class InvalidCredentialsError(AuthenticationError):
    def __init__(self, message: str = "Invalid username or password. Please try again."):
        super().__init__(message)


class AccountLockedError(AuthenticationError):
    """Too many failed attempts; the account is cooling off."""

    def __init__(self, message: str, seconds_remaining: int = 0):
        super().__init__(message)
        self.seconds_remaining = seconds_remaining


class AccountDisabledError(AuthenticationError):
    def __init__(self, message: str = "This account has been deactivated. Contact an administrator."):
        super().__init__(message)


class UserNotFoundError(SmartPOSError):
    def __init__(self, message: str = "No account matches those details."):
        super().__init__(message)


class DuplicateUserError(SmartPOSError):
    """Username or e-mail is already taken."""


class AccountPendingError(AuthenticationError):
    """Registered, but no administrator has approved the account yet."""

    def __init__(
        self,
        message: str = (
            "Your account is still waiting for approval. An administrator has to "
            "let you in before you can sign in."
        ),
    ):
        super().__init__(message)


class AccountRejectedError(AuthenticationError):
    """An administrator turned this registration down."""

    def __init__(
        self,
        message: str = (
            "This registration was not approved. Speak to your manager if you "
            "think that is a mistake."
        ),
    ):
        super().__init__(message)


class RegistrationError(SmartPOSError):
    """A sign-up could not be completed."""


class PhoneNotVerifiedError(RegistrationError):
    def __init__(self, message: str = "Confirm the code sent to your mobile first."):
        super().__init__(message)
