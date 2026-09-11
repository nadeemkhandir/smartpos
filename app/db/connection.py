"""
SQLite connection management.

One :class:`Database` object owns the file. It hands out a *separate* connection
per thread, because a sqlite3 connection may not be shared across threads and
SmartPOS signs users in and sends mail on worker threads while the Qt event loop
keeps painting.

Usage::

    from app.db import database

    with database.cursor() as cur:                 # commits, or rolls back
        cur.execute("UPDATE users SET ...", (...))

    row = database.fetch_one("SELECT * FROM users WHERE id = ?", (1,))
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from app.core.config import settings
from app.core.exceptions import DatabaseError


class Database:
    """A thin, thread-aware wrapper around a single SQLite file."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or settings.db_path)
        self._local = threading.local()
        self._lock = threading.Lock()

    # -------------------------------------------------- connections

    @property
    def connection(self) -> sqlite3.Connection:
        """The calling thread's connection, opened on first use."""
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing

        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            connection = sqlite3.connect(
                self.path,
                timeout=15.0,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
        except sqlite3.Error as error:
            raise DatabaseError(f"Could not open the database at {self.path}: {error}") from error

        # Rows behave like dicts, so repositories can read row["email"].
        connection.row_factory = sqlite3.Row

        connection.execute("PRAGMA foreign_keys = ON")
        # WAL lets a report read while the till writes, instead of blocking.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 15000")

        self._local.connection = connection
        return connection

    def close(self) -> None:
        """Close this thread's connection, if it has one."""
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    # -------------------------------------------------- transactions

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        """Run statements inside one transaction.

        Commits on a clean exit, rolls back on any exception, and always closes
        the cursor.
        """
        connection = self.connection
        cursor = connection.cursor()
        try:
            yield cursor
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Group several repository calls into one all-or-nothing unit."""
        connection = self.connection
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    # -------------------------------------------------- queries

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Run a write statement and commit it."""
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor

    def execute_many(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        with self.cursor() as cursor:
            cursor.executemany(sql, seq_of_params)

    def execute_script(self, script: str) -> None:
        with self.cursor() as cursor:
            cursor.executescript(script)

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        cursor = self.connection.execute(sql, params)
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        cursor = self.connection.execute(sql, params)
        try:
            return cursor.fetchall()
        finally:
            cursor.close()

    def fetch_value(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        """First column of the first row — for COUNT(*) and friends."""
        row = self.fetch_one(sql, params)
        return default if row is None else row[0]

    # -------------------------------------------------- introspection

    def table_exists(self, name: str) -> bool:
        return (
            self.fetch_one(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (name,),
            )
            is not None
        )

    def column_names(self, table: str) -> list[str]:
        return [row["name"] for row in self.fetch_all(f"PRAGMA table_info({table})")]

    @property
    def user_version(self) -> int:
        """SQLite's built-in schema version counter, used by the migrator."""
        return int(self.fetch_value("PRAGMA user_version", default=0) or 0)

    @user_version.setter
    def user_version(self, value: int) -> None:
        # PRAGMA will not accept a bound parameter, hence the f-string; the
        # value is an int we produced ourselves, never user input.
        self.connection.execute(f"PRAGMA user_version = {int(value)}")
        self.connection.commit()


#: The application-wide instance. Import this, do not build your own.
database = Database()
