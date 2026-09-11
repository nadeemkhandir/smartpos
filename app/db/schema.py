"""
The SmartPOS schema, and the migrator that keeps a file up to date with it.

There is exactly one table — ``users``. Everything the sign-in flow needs lives
on the row it belongs to: the password hash, the reset passcode, the
"remember me" token and the lockout counters. Keeping them here rather than in
side tables means a user's secrets vanish the moment their row is deleted, and
there is no orphan token table to sweep.

Versioning uses SQLite's own ``PRAGMA user_version``. Bump ``SCHEMA_VERSION``
and add an entry to ``MIGRATIONS`` to change the shape of the table later; the
migrator runs the missing steps in order on every start-up.
"""

from __future__ import annotations

import sqlite3

from app.core.account_status import AccountStatus
from app.core.config import settings
from app.core.exceptions import DatabaseError
from app.core.roles import Role
from app.core.security import hash_password
from app.core.utils import to_iso, utcnow
from app.db.connection import Database, database as default_database

SCHEMA_VERSION = 3

#: Written into the CHECK constraint so SQLite itself rejects a bad role.
_ROLE_LIST = ", ".join(f"'{role.value}'" for role in Role)

#: Same idea for the admission state.
_STATUS_LIST = ", ".join(f"'{status.value}'" for status in AccountStatus)

CREATE_USERS_TABLE = f"""
CREATE TABLE IF NOT EXISTS users (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity. COLLATE NOCASE makes the UNIQUE index case-insensitive, so
    -- "Nadeem" and "nadeem" cannot both be registered.
    username               TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    email                  TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    full_name              TEXT    NOT NULL DEFAULT '',
    phone                  TEXT,

    -- Credentials. Never the password itself:
    -- pbkdf2_sha256$<iterations>$<salt>$<key>
    password_hash          TEXT    NOT NULL,
    must_change_password   INTEGER NOT NULL DEFAULT 0,
    password_changed_at    TEXT,

    -- Authorisation.
    role                   TEXT    NOT NULL DEFAULT 'cashier'
                                   CHECK (role IN ({_ROLE_LIST})),
    is_active              INTEGER NOT NULL DEFAULT 1,

    -- Admission. A self-service sign-up lands here as 'pending' and cannot
    -- sign in until an administrator approves it. Deliberately separate from
    -- is_active; app/core/account_status.py explains why.
    status                 TEXT    NOT NULL DEFAULT 'approved'
                                   CHECK (status IN ({_STATUS_LIST})),
    registered_at          TEXT,
    approved_at            TEXT,
    approved_by            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    rejected_at            TEXT,
    rejection_reason       TEXT,

    -- Set when an administrator vouched for the number. Self-registered
    -- numbers are claimed, not proved, and stay null.
    phone_verified_at      TEXT,

    -- Brute-force protection.
    failed_attempts        INTEGER NOT NULL DEFAULT 0,
    locked_until           TEXT,
    last_login_at          TEXT,
    last_login_ip          TEXT,

    -- "Remember me" (SHA-256 of the token held by this terminal).
    remember_token_hash    TEXT,
    remember_expires_at    TEXT,

    created_at             TEXT    NOT NULL,
    updated_at             TEXT    NOT NULL
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_users_email    ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_role     ON users (role);
CREATE INDEX IF NOT EXISTS idx_users_active   ON users (is_active);
CREATE INDEX IF NOT EXISTS idx_users_remember ON users (remember_token_hash);
CREATE INDEX IF NOT EXISTS idx_users_status   ON users (status);

-- SQLite lets a UNIQUE index hold any number of NULLs, which is exactly what
-- is wanted: at most one account per handset, and no limit on accounts with no
-- number on file at all.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users (phone);
"""

# Safety net for any UPDATE that forgets to stamp the row. The WHEN guard stops
# the trigger from recursing into itself.
CREATE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_users_touch_updated_at
AFTER UPDATE ON users
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE users
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
     WHERE id = NEW.id;
END;
"""

#: Columns added in schema 2, as ``name -> the DDL fragment ALTER TABLE needs``.
#: SQLite cannot add a UNIQUE or PRIMARY KEY column after the fact, but CHECK
#: constraints and foreign keys are fine as long as the default is constant.
_V2_COLUMNS: dict[str, str] = {
    "status": f"TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ({_STATUS_LIST}))",
    "registered_at": "TEXT",
    "approved_at": "TEXT",
    "approved_by": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
    "rejected_at": "TEXT",
    "rejection_reason": "TEXT",
    "phone_verified_at": "TEXT",
    "verify_otp_hash": "TEXT",
    "verify_otp_expires_at": "TEXT",
    "verify_otp_sent_at": "TEXT",
    "verify_otp_attempts": "INTEGER NOT NULL DEFAULT 0",
}


def _migration_2(db: "Database") -> None:
    """Add self-registration and phone verification to a schema-1 file.

    Every account that already exists was entered by an administrator, so the
    ``'approved'`` default is the truthful answer for all of them and no
    back-fill is needed. Existing numbers are taken as vouched-for by the same
    reasoning: an administrator typed every one of them.
    """
    _add_missing_columns(db, "users", _V2_COLUMNS)

    db.execute(
        "UPDATE users SET registered_at = created_at WHERE registered_at IS NULL"
    )
    db.execute(
        """
        UPDATE users
           SET phone_verified_at = created_at
         WHERE phone IS NOT NULL AND phone <> '' AND phone_verified_at IS NULL
        """
    )


def _add_missing_columns(db: "Database", table: str, columns: dict[str, str]) -> None:
    """``ALTER TABLE ... ADD COLUMN`` for whichever columns are not there yet.

    Checking first is what lets the same migration run against a file created
    by an older build *and* be a harmless no-op on a database the current
    ``CREATE TABLE`` just built with every column already in place.
    """
    existing = set(db.column_names(table))

    for name, ddl in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


#: Columns that schema 2 added and schema 3 took away again, plus the passcode
#: columns that were there from the beginning. A file upgrading straight from
#: version 1 gains them in step 2 and loses them in step 3, which costs one
#: rewrite of a table that only ever holds a handful of rows.
_OTP_COLUMNS = (
    "verify_otp_hash",
    "verify_otp_expires_at",
    "verify_otp_sent_at",
    "verify_otp_attempts",
    "reset_otp_hash",
    "reset_otp_expires_at",
    "reset_otp_sent_at",
    "reset_otp_attempts",
)


def _migration_3(db: "Database") -> None:
    """Drop the one-time-passcode columns.

    Sign-up no longer texts a code to prove a number, and "forgot password" no
    longer sends one at all, so nothing reads or writes these. Dropping them
    keeps the table honest about what the application actually does.
    """
    _drop_columns(db, "users", _OTP_COLUMNS)


def _drop_columns(db: "Database", table: str, columns: "tuple[str, ...]") -> None:
    """``ALTER TABLE ... DROP COLUMN`` for whichever columns are still there.

    Checking first is what lets this run against a file written by an older
    build *and* be a harmless no-op on a database the current ``CREATE TABLE``
    just built without them. Needs SQLite 3.35 or newer, which every Python
    that can run this application ships with.
    """
    existing = set(db.column_names(table))

    for name in columns:
        if name in existing:
            db.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


#: version -> the steps that migrate *to* that version. Each step is either a
#: SQL string or a callable taking the database. Version 1 is the initial
#: schema above, so it has no upgrade steps.
MIGRATIONS: dict[int, list[object]] = {
    2: [_migration_2],
    3: [_migration_3],
}


def initialise(db: Database | None = None, *, seed: bool = True) -> Database:
    """Create the database file if needed, migrate it, and seed the first admin.

    Safe to call on every start-up; each step is a no-op once it has run.
    """
    db = db or default_database

    try:
        db.execute_script(CREATE_USERS_TABLE)
        # Migrations run before the indexes, because an index added in a later
        # schema version names columns that only exist once its migration has.
        _migrate(db)
        db.execute_script(CREATE_INDEXES)
        db.execute_script(CREATE_TRIGGERS)
    except sqlite3.Error as error:
        raise DatabaseError(f"Could not prepare the database: {error}") from error

    if seed:
        seed_default_admin(db)

    return db


def _migrate(db: Database) -> None:
    """Apply every migration newer than the file's recorded version."""
    current = db.user_version

    if current > SCHEMA_VERSION:
        raise DatabaseError(
            f"The database at {db.path} was written by a newer version of SmartPOS "
            f"(schema {current}, this build understands {SCHEMA_VERSION}). Please update."
        )

    for version in range(current + 1, SCHEMA_VERSION + 1):
        for step in MIGRATIONS.get(version, []):
            if callable(step):
                step(db)
            else:
                db.execute_script(str(step))

    if current != SCHEMA_VERSION:
        db.user_version = SCHEMA_VERSION


def seed_default_admin(db: Database | None = None) -> bool:
    """Create the first administrator when the table is empty.

    Returns True if an account was created. The seeded admin is flagged
    ``must_change_password`` so the shipped default cannot quietly stay in use.
    """
    db = db or default_database

    if db.fetch_value("SELECT COUNT(*) FROM users", default=0):
        return False

    stamp = to_iso(utcnow())

    db.execute(
        """
        INSERT INTO users (
            username, email, full_name, password_hash,
            must_change_password, role, is_active,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, 1, ?, ?)
        """,
        (
            settings.seed_admin_username,
            settings.seed_admin_email,
            "System Administrator",
            hash_password(settings.seed_admin_password),
            Role.ADMIN.value,
            stamp,
            stamp,
        ),
    )
    return True


def reset_database(db: Database | None = None) -> None:
    """Drop and rebuild everything. Development helper — it destroys all users."""
    db = db or default_database
    db.execute_script(
        "DROP TRIGGER IF EXISTS trg_users_touch_updated_at; DROP TABLE IF EXISTS users;"
    )
    db.user_version = 0
    initialise(db)
