"""
Every SQL statement that touches the ``users`` table lives here.

The layer above (services) decides *whether* an account should be locked; this
layer only knows *how* to write that down. Nothing in ``app/ui`` should import
sqlite3 or write SQL — it goes through a service, which comes through here.

Secrets are handled carefully: ordinary lookups return a :class:`User` without
``password_hash`` or token columns. Pass ``with_secrets=True`` only where a
secret is about to be verified.
"""

from __future__ import annotations

import sqlite3

from app.core.account_status import AccountStatus
from app.core.config import settings
from app.core.exceptions import DuplicateUserError, ValidationError
from app.core.phone import normalise_phone
from app.core.roles import Role
from app.core.security import hash_password
from app.core.utils import (
    is_email,
    normalise_email,
    normalise_username,
    to_iso,
    utcnow,
)
from app.db.connection import Database, database as default_database
from app.models.user import User

#: Columns safe to hand out anywhere.
PUBLIC_COLUMNS = """
    id, username, email, full_name, phone, role, is_active, status,
    must_change_password, failed_attempts, locked_until, last_login_at,
    last_login_ip, password_changed_at, created_at, updated_at,
    registered_at, approved_at, approved_by, rejected_at, rejection_reason,
    phone_verified_at
"""

ALL_COLUMNS = "*"


class UserRepository:
    """CRUD and credential bookkeeping for user accounts."""

    def __init__(self, db: Database | None = None):
        self.db = db or default_database

    # ============================================================
    # Reads
    # ============================================================

    def get_by_id(self, user_id: int, *, with_secrets: bool = False) -> User | None:
        return User.from_row(
            self.db.fetch_one(
                f"SELECT {self._columns(with_secrets)} FROM users WHERE id = ?",
                (user_id,),
            )
        )

    def get_by_username(self, username: str, *, with_secrets: bool = False) -> User | None:
        return User.from_row(
            self.db.fetch_one(
                f"SELECT {self._columns(with_secrets)} FROM users WHERE username = ?",
                (normalise_username(username),),
            )
        )

    def get_by_email(self, email: str, *, with_secrets: bool = False) -> User | None:
        return User.from_row(
            self.db.fetch_one(
                f"SELECT {self._columns(with_secrets)} FROM users WHERE email = ?",
                (normalise_email(email),),
            )
        )

    def get_by_identifier(self, identifier: str, *, with_secrets: bool = False) -> User | None:
        """Look up by username *or* e-mail — the sign-in box accepts either."""
        identifier = (identifier or "").strip()
        if not identifier:
            return None

        return User.from_row(
            self.db.fetch_one(
                f"""
                SELECT {self._columns(with_secrets)}
                  FROM users
                 WHERE username = ? OR email = ?
                 LIMIT 1
                """,
                (identifier, identifier.lower()),
            )
        )

    def get_by_remember_hash(self, token_hash: str, *, with_secrets: bool = False) -> User | None:
        if not token_hash:
            return None

        return User.from_row(
            self.db.fetch_one(
                f"SELECT {self._columns(with_secrets)} FROM users WHERE remember_token_hash = ?",
                (token_hash,),
            )
        )

    def get_by_phone(self, phone: str, *, with_secrets: bool = False) -> User | None:
        """Look an account up by handset. ``phone`` may be in any spelling."""
        normalised = self._normalise_phone(phone)

        if not normalised:
            return None

        return User.from_row(
            self.db.fetch_one(
                f"SELECT {self._columns(with_secrets)} FROM users WHERE phone = ?",
                (normalised,),
            )
        )

    def phone_exists(self, phone: str, *, exclude_id: int | None = None) -> bool:
        normalised = self._normalise_phone(phone)
        return bool(normalised) and self._exists("phone", normalised, exclude_id)

    def list_pending(self) -> list[User]:
        """Sign-ups awaiting a decision, oldest first so nobody is forgotten."""
        rows = self.db.fetch_all(
            f"""
            SELECT {PUBLIC_COLUMNS} FROM users
             WHERE status = ?
             ORDER BY registered_at ASC, id ASC
            """,
            (AccountStatus.PENDING.value,),
        )
        return [User.from_row(row) for row in rows]

    def list_users(
        self,
        *,
        role: Role | str | None = None,
        active_only: bool = False,
        status: AccountStatus | str | None = None,
        search: str = "",
    ) -> list[User]:
        """All accounts, optionally filtered, for a user-management screen."""
        clauses: list[str] = []
        params: list[object] = []

        if role is not None:
            clauses.append("role = ?")
            params.append(Role.parse(role).value)

        if active_only:
            clauses.append("is_active = 1")

        if status is not None:
            clauses.append("status = ?")
            params.append(AccountStatus.parse(status).value)

        if search:
            clauses.append("(username LIKE ? OR email LIKE ? OR full_name LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle])

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        rows = self.db.fetch_all(
            f"SELECT {PUBLIC_COLUMNS} FROM users {where} ORDER BY role, username COLLATE NOCASE",
            params,
        )
        return [User.from_row(row) for row in rows]

    def count(
        self,
        *,
        role: Role | str | None = None,
        active_only: bool = False,
        status: AccountStatus | str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []

        if role is not None:
            clauses.append("role = ?")
            params.append(Role.parse(role).value)

        if active_only:
            clauses.append("is_active = 1")

        if status is not None:
            clauses.append("status = ?")
            params.append(AccountStatus.parse(status).value)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        return int(self.db.fetch_value(f"SELECT COUNT(*) FROM users {where}", params, default=0))

    def username_exists(self, username: str, *, exclude_id: int | None = None) -> bool:
        return self._exists("username", normalise_username(username), exclude_id)

    def email_exists(self, email: str, *, exclude_id: int | None = None) -> bool:
        return self._exists("email", normalise_email(email), exclude_id)

    # ============================================================
    # Writes
    # ============================================================

    def create(
        self,
        *,
        username: str,
        email: str,
        password: str,
        role: Role | str = Role.CASHIER,
        full_name: str = "",
        phone: str | None = None,
        is_active: bool = True,
        must_change_password: bool = False,
        status: AccountStatus | str = AccountStatus.APPROVED,
        phone_verified: bool = False,
    ) -> User:
        """Insert a new account. The password is hashed here, never stored raw."""
        username = normalise_username(username)
        email = normalise_email(email)
        phone = self._normalise_phone(phone)
        status = AccountStatus.parse(status, default=AccountStatus.APPROVED)

        if not username:
            raise ValidationError("A username is required.")
        if len(username) < 3:
            raise ValidationError("Username must be at least 3 characters long.")
        if not is_email(email):
            raise ValidationError("Please enter a valid e-mail address.")

        if self.username_exists(username):
            raise DuplicateUserError(f"The username '{username}' is already taken.")
        if self.email_exists(email):
            raise DuplicateUserError(f"'{email}' is already registered to another account.")
        if phone and self.phone_exists(phone):
            raise DuplicateUserError("That mobile number is already registered to another account.")

        stamp = to_iso(utcnow())

        try:
            cursor = self.db.execute(
                """
                INSERT INTO users (
                    username, email, full_name, phone, password_hash,
                    must_change_password, password_changed_at, role, is_active,
                    status, registered_at, phone_verified_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    (full_name or "").strip(),
                    phone or None,
                    hash_password(password),
                    int(must_change_password),
                    stamp,
                    Role.parse(role, default=Role.CASHIER).value,
                    int(is_active),
                    status.value,
                    stamp,
                    stamp if (phone and phone_verified) else None,
                    stamp,
                    stamp,
                ),
            )
        except sqlite3.IntegrityError as error:
            # The UNIQUE indexes are the real guard; the checks above only exist
            # to produce a friendlier message first.
            raise DuplicateUserError(
                "That username, e-mail address or mobile number is already in use."
            ) from error

        return self.get_by_id(cursor.lastrowid)

    def update_profile(
        self,
        user_id: int,
        *,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        role: Role | str | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        """Patch the editable fields of an account. Omitted fields stay as they are."""
        updates: dict[str, object] = {}

        if full_name is not None:
            updates["full_name"] = full_name.strip()

        if email is not None:
            email = normalise_email(email)
            if not is_email(email):
                raise ValidationError("Please enter a valid e-mail address.")
            if self.email_exists(email, exclude_id=user_id):
                raise DuplicateUserError(f"'{email}' is already registered to another account.")
            updates["email"] = email

        if phone is not None:
            normalised = self._normalise_phone(phone)

            if phone.strip() and not normalised:
                raise ValidationError("That does not look like a mobile number.")

            if normalised and self.phone_exists(normalised, exclude_id=user_id):
                raise DuplicateUserError(
                    "That mobile number is already registered to another account."
                )

            updates["phone"] = normalised or None
            # A new number is an unproven one, whoever typed it.
            updates["phone_verified_at"] = None

        if role is not None:
            updates["role"] = Role.parse(role).value

        if is_active is not None:
            updates["is_active"] = int(is_active)

        if updates:
            self._apply(user_id, updates)

        return self.get_by_id(user_id)

    def set_password(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change: bool = False,
        clear_reset: bool = True,
    ) -> None:
        """Store a new password and clear everything that could bypass it.

        Changing a password ends the lockout, invalidates every remembered
        terminal and burns any outstanding passcode — the three ways an old
        secret could otherwise still let someone in.
        """
        updates: dict[str, object] = {
            "password_hash": hash_password(new_password),
            "password_changed_at": to_iso(utcnow()),
            "must_change_password": int(must_change),
            "failed_attempts": 0,
            "locked_until": None,
            "remember_token_hash": None,
            "remember_expires_at": None,
        }

        if clear_reset:
            updates.update(
            )

        self._apply(user_id, updates)

    def rehash_password(self, user_id: int, new_hash: str) -> None:
        """Swap in a stronger hash of the same password, after a good sign-in."""
        self._apply(user_id, {"password_hash": new_hash})

    def delete(self, user_id: int) -> bool:
        cursor = self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0

    def set_active(self, user_id: int, active: bool) -> None:
        updates: dict[str, object] = {"is_active": int(active)}

        if not active:
            # A disabled account must not be able to walk back in through a
            # terminal that still remembers it.
            updates.update(remember_token_hash=None, remember_expires_at=None)

        self._apply(user_id, updates)

    # ============================================================
    # Sign-in bookkeeping
    # ============================================================

    def register_failed_attempt(self, user_id: int, *, lock_until=None) -> int:
        """Count one bad password and return the new total."""
        assignments = "failed_attempts = failed_attempts + 1, updated_at = ?"
        params: list[object] = [to_iso(utcnow())]

        if lock_until is not None:
            assignments += ", locked_until = ?"
            params.append(to_iso(lock_until))

        params.append(user_id)
        self.db.execute(f"UPDATE users SET {assignments} WHERE id = ?", params)

        return int(
            self.db.fetch_value(
                "SELECT failed_attempts FROM users WHERE id = ?", (user_id,), default=0
            )
        )

    def register_successful_login(self, user_id: int, *, ip_address: str | None = None) -> None:
        self._apply(
            user_id,
            {
                "failed_attempts": 0,
                "locked_until": None,
                "last_login_at": to_iso(utcnow()),
                "last_login_ip": ip_address,
            },
        )

    def clear_lockout(self, user_id: int) -> None:
        self._apply(user_id, {"failed_attempts": 0, "locked_until": None})

    # ============================================================
    # Registration and approval
    # ============================================================

    def approve(self, user_id: int, *, role: Role | str, approved_by: int | None) -> User | None:
        """Let a pending sign-up in, with the role the approver chose."""
        self._apply(
            user_id,
            {
                "status": AccountStatus.APPROVED.value,
                "role": Role.parse(role, default=Role.CASHIER).value,
                "approved_at": to_iso(utcnow()),
                "approved_by": approved_by,
                "rejected_at": None,
                "rejection_reason": None,
                "is_active": 1,
            },
        )
        return self.get_by_id(user_id)

    def reject(self, user_id: int, *, reason: str = "", rejected_by: int | None = None) -> User | None:
        """Turn a sign-up down.

        The row stays, deactivated: it keeps the username, e-mail and phone
        number claimed so the same person cannot simply register again and
        land in the queue afresh.
        """
        self._apply(
            user_id,
            {
                "status": AccountStatus.REJECTED.value,
                "rejected_at": to_iso(utcnow()),
                "rejection_reason": (reason or "").strip() or None,
                "approved_at": None,
                "approved_by": rejected_by,
                "is_active": 0,
            },
        )
        return self.get_by_id(user_id)

    # ============================================================
    # Phone numbers
    # ============================================================

    def mark_phone_verified(self, user_id: int) -> None:
        """Record that an administrator vouched for the number on this row."""
        self._apply(user_id, {"phone_verified_at": to_iso(utcnow())})

    # ============================================================
    # "Remember me"
    # ============================================================

    def store_remember_token(self, user_id: int, token_hash: str, expires_at) -> None:
        self._apply(
            user_id,
            {
                "remember_token_hash": token_hash,
                "remember_expires_at": to_iso(expires_at),
            },
        )

    def clear_remember_token(self, user_id: int) -> None:
        self._apply(user_id, {"remember_token_hash": None, "remember_expires_at": None})

    # ============================================================
    # Internals
    # ============================================================

    @staticmethod
    def _normalise_phone(value: str | None) -> str:
        """E.164 or ``""``, using the country code configured for this shop."""
        return normalise_phone(value, default_country_code=settings.country_code)

    @staticmethod
    def _columns(with_secrets: bool) -> str:
        return ALL_COLUMNS if with_secrets else PUBLIC_COLUMNS

    def _apply(self, user_id: int, updates: dict[str, object]) -> None:
        """UPDATE one row from a column -> value mapping, stamping updated_at.

        Column names come from this module only, never from user input, so
        interpolating them into the statement is safe; the values stay bound.
        """
        if not updates:
            return

        updates = dict(updates)
        updates["updated_at"] = to_iso(utcnow())

        assignments = ", ".join(f"{column} = ?" for column in updates)
        params = list(updates.values()) + [user_id]

        self.db.execute(f"UPDATE users SET {assignments} WHERE id = ?", params)

    def _exists(self, column: str, value: str, exclude_id: int | None) -> bool:
        sql = f"SELECT 1 FROM users WHERE {column} = ?"
        params: list[object] = [value]

        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)

        return self.db.fetch_one(sql + " LIMIT 1", params) is not None


#: Shared instance — stateless, so one is enough.
user_repository = UserRepository()
