"""
Where an account sits in its lifecycle.

Separate from ``is_active`` on purpose, because the two answer different
questions and a single flag cannot hold both:

* **status** — how the account came to exist and whether it was ever let in.
  A self-registered account starts :attr:`AccountStatus.PENDING` and an
  administrator moves it to :attr:`AccountStatus.APPROVED` or
  :attr:`AccountStatus.REJECTED`. This is a one-way story about admission.
* **is_active** — the ordinary on/off switch an administrator flips when
  somebody leaves for the season and comes back. It says nothing about how
  the account was created.

Sign-in needs both to be favourable: approved *and* active. Keeping them apart
means reinstating a suspended employee does not re-open the approval question,
and rejecting a sign-up does not masquerade as an ordinary deactivation.
"""

from __future__ import annotations

from enum import Enum


class AccountStatus(str, Enum):
    """Admission state of a user account."""

    #: Registered by the person themselves, waiting for an administrator.
    PENDING = "pending"

    #: Allowed to sign in — either approved, or created by an administrator.
    APPROVED = "approved"

    #: Refused by an administrator. The row is kept so the username and phone
    #: number stay claimed and the same person cannot simply register again.
    REJECTED = "rejected"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]

    @classmethod
    def parse(cls, value: "str | AccountStatus | None", default: "AccountStatus | None" = None) -> "AccountStatus":
        """Turn a stored string into a status, tolerating case and stray spaces."""
        if isinstance(value, cls):
            return value
        if value:
            try:
                return cls(str(value).strip().lower())
            except ValueError:
                pass
        if default is not None:
            return default
        raise ValueError(f"Unknown account status: {value!r}")


_LABELS = {
    AccountStatus.PENDING: "Awaiting approval",
    AccountStatus.APPROVED: "Approved",
    AccountStatus.REJECTED: "Rejected",
}

_DESCRIPTIONS = {
    AccountStatus.PENDING: "Signed up and verified a phone number; cannot sign in yet.",
    AccountStatus.APPROVED: "Cleared by an administrator and able to sign in.",
    AccountStatus.REJECTED: "Turned down by an administrator and permanently refused.",
}
