"""
The ``User`` value object.

Rows leave the repository as one of these, so the rest of the app works with
``user.is_locked`` and ``user.role.label`` instead of remembering column names
and re-parsing timestamps. It is a snapshot, not a live record: changing a field
here changes nothing in the database.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.core.account_status import AccountStatus
from app.core.roles import Permission, Role
from app.core.utils import from_iso, is_expired, seconds_until


@dataclass(slots=True)
class User:
    id: int | None = None
    username: str = ""
    email: str = ""
    full_name: str = ""
    phone: str | None = None

    role: Role = Role.CASHIER
    is_active: bool = True
    must_change_password: bool = False

    #: Admission state. ``is_active`` is the separate on/off switch — see
    #: ``app/core/account_status.py`` for why both exist.
    status: AccountStatus = AccountStatus.APPROVED
    registered_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: int | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None

    phone_verified_at: datetime | None = None

    failed_attempts: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    password_changed_at: datetime | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None

    #: Never populated from a plain SELECT — only ``UserRepository`` fills these
    #: in, and only for the row it is about to check a secret against.
    password_hash: str | None = field(default=None, repr=False)
    remember_token_hash: str | None = field(default=None, repr=False)
    remember_expires_at: datetime | None = field(default=None, repr=False)

    # -------------------------------------------------- derived state

    @property
    def display_name(self) -> str:
        """What the dashboard greets them with."""
        return self.full_name.strip() or self.username

    @property
    def role_label(self) -> str:
        return self.role.label

    @property
    def is_locked(self) -> bool:
        """True while a lockout from failed sign-ins is still in force."""
        return self.locked_until is not None and not is_expired(self.locked_until)

    @property
    def lock_seconds_remaining(self) -> int:
        return seconds_until(self.locked_until) if self.is_locked else 0

    @property
    def is_pending(self) -> bool:
        """Registered by the person themselves, still waiting on an approver."""
        return self.status is AccountStatus.PENDING

    @property
    def is_approved(self) -> bool:
        return self.status is AccountStatus.APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status is AccountStatus.REJECTED

    @property
    def phone_verified(self) -> bool:
        """True when an administrator entered this number rather than the owner.

        Self-registration takes a number on trust and never proves it, so this
        stays False for a sign-up until somebody with the database in front of
        them confirms it. Nothing is ever sent to the number — it is a contact
        detail for an approver to ring.
        """
        return bool(self.phone) and self.phone_verified_at is not None

    @property
    def can_sign_in(self) -> bool:
        """Every admission condition at once, ignoring the password itself.

        Approved, switched on and not cooling off from failed attempts. The
        sign-in path still checks each of these separately so it can say which
        one failed; this is for screens that only need a yes or no.
        """
        return self.is_approved and self.is_active and not self.is_locked

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    def can(self, permission: Permission) -> bool:
        return self.role.can(permission)

    @property
    def initials(self) -> str:
        """Up to two letters for an avatar chip."""
        parts = [p for p in self.display_name.replace("_", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    # -------------------------------------------------- conversion

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any] | None) -> "User | None":
        """Build a User from a database row, or None if there was no row."""
        if row is None:
            return None

        data = dict(row)

        return cls(
            id=data.get("id"),
            username=data.get("username", ""),
            email=data.get("email", ""),
            full_name=data.get("full_name") or "",
            phone=data.get("phone"),
            role=Role.parse(data.get("role"), default=Role.CASHIER),
            is_active=bool(data.get("is_active", 1)),
            must_change_password=bool(data.get("must_change_password", 0)),
            status=AccountStatus.parse(data.get("status"), default=AccountStatus.APPROVED),
            registered_at=from_iso(data.get("registered_at")),
            approved_at=from_iso(data.get("approved_at")),
            approved_by=data.get("approved_by"),
            rejected_at=from_iso(data.get("rejected_at")),
            rejection_reason=data.get("rejection_reason"),
            phone_verified_at=from_iso(data.get("phone_verified_at")),
            failed_attempts=int(data.get("failed_attempts") or 0),
            locked_until=from_iso(data.get("locked_until")),
            last_login_at=from_iso(data.get("last_login_at")),
            last_login_ip=data.get("last_login_ip"),
            password_changed_at=from_iso(data.get("password_changed_at")),
            created_at=from_iso(data.get("created_at")),
            updated_at=from_iso(data.get("updated_at")),
            password_hash=data.get("password_hash"),
            remember_token_hash=data.get("remember_token_hash"),
            remember_expires_at=from_iso(data.get("remember_expires_at")),
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Everything safe to log, print or hand to a screen — no secrets."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "phone": self.phone,
            "role": self.role.value,
            "role_label": self.role.label,
            "is_active": self.is_active,
            "status": self.status.value,
            "status_label": self.status.label,
            "phone_verified": self.phone_verified,
            "must_change_password": self.must_change_password,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def scrubbed(self) -> "User":
        """A copy with every secret dropped, for handing to the UI layer."""
        clone = User(**{
            f: getattr(self, f)
            for f in (
                "id", "username", "email", "full_name", "phone", "role",
                "is_active", "status", "must_change_password", "failed_attempts",
                "locked_until", "last_login_at", "last_login_ip",
                "password_changed_at", "created_at", "updated_at",
                "registered_at", "approved_at", "approved_by",
                "rejected_at", "rejection_reason", "phone_verified_at",
            )
        })
        return clone

    def __str__(self) -> str:
        return f"{self.display_name} ({self.role.label})"
