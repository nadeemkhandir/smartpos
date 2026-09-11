"""
Central configuration for SmartPOS.

Every tunable — where the database lives, what country phone numbers default
to, how long a sign-in lockout lasts — is resolved here once and read from
``settings`` everywhere else. Nothing else in the codebase should build a path
or reach for ``os.environ`` on its own.

Values come from three places, in order of priority:

    1. Real environment variables.
    2. A ``.env`` file at the project root (see ``.env.example``).
    3. The defaults written below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent      # .../smartpos/app
BASE_DIR = APP_DIR.parent                             # .../smartpos
DB_DIR = APP_DIR / "db"
LOG_DIR = BASE_DIR / "logs"
ENV_FILE = BASE_DIR / ".env"


# ------------------------------------------------------------------
# .env loading
# ------------------------------------------------------------------


def load_env_file(path: Path = ENV_FILE) -> None:
    """Read simple ``KEY=value`` pairs into ``os.environ``.

    A hand-rolled reader keeps the project dependency-free. Real environment
    variables always win, so a deployment can override the file without
    editing it.
    """
    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


def _str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _secret(key: str, default: str) -> str:
    """Like :func:`_str`, but with every space removed.

    Google displays an app password as four space-separated groups
    ("abcd efgh ijkl mnop"). Pasted verbatim those spaces reach ``login()``
    and the server answers with a plain "Username and Password not accepted",
    which reads like the wrong password rather than a formatting slip.
    """
    return _str(key, default).replace(" ", "")


def _bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


@dataclass(frozen=True)
class RegistrationSettings:
    """Rules for the self-service sign-up screen."""

    #: Turn the "Create account" link off entirely on a terminal that should
    #: only ever be used by staff an administrator has already entered.
    enabled: bool = field(default_factory=lambda: _bool("REGISTRATION_ENABLED", True))

    #: Role a newly approved account gets when the approver does not pick one.
    #: Never read directly — see ``Settings.registration_default_role``.
    default_role: str = field(default_factory=lambda: _str("REGISTRATION_DEFAULT_ROLE", "cashier"))



@dataclass(frozen=True)
class SecuritySettings:
    """Password hashing, lockout and one-time passcode rules."""

    # PBKDF2-HMAC-SHA256. High enough to be slow for an attacker, still well
    # under a tenth of a second on the counter hardware this runs on.
    pbkdf2_iterations: int = field(default_factory=lambda: _int("PBKDF2_ITERATIONS", 240_000))
    salt_bytes: int = 16

    min_password_length: int = field(default_factory=lambda: _int("MIN_PASSWORD_LENGTH", 8))

    # Brute-force protection on the sign-in form.
    max_failed_attempts: int = field(default_factory=lambda: _int("MAX_FAILED_ATTEMPTS", 5))
    lockout_minutes: int = field(default_factory=lambda: _int("LOCKOUT_MINUTES", 10))

    # "Remember me" token lifetime.
    remember_days: int = field(default_factory=lambda: _int("REMEMBER_ME_DAYS", 30))

    # Internal deployments usually want "no such account" spelled out so staff
    # can spot a typo. Flip to False on anything internet-facing to avoid
    # confirming which addresses exist.
    reveal_unknown_account: bool = field(
        default_factory=lambda: _bool("REVEAL_UNKNOWN_ACCOUNT", True)
    )


@dataclass(frozen=True)
class Settings:
    app_name: str = "SmartPOS"
    app_version: str = "1.0.0"
    organisation: str = field(default_factory=lambda: _str("ORGANISATION", "SmartPOS"))

    db_path: Path = field(default_factory=lambda: Path(_str("SMARTPOS_DB", str(DB_DIR / "smartpos.db"))))

    #: Assumed for any mobile number typed without one, so staff can enter
    #: "0300 1234821" and the account still stores "+923001234821". Nothing is
    #: sent to these numbers — they are contact details an approver can read.
    country_code: str = field(default_factory=lambda: _secret("COUNTRY_CODE", "+92"))

    # First-run administrator. Created only when the users table is empty.
    seed_admin_username: str = field(default_factory=lambda: _str("SEED_ADMIN_USERNAME", "admin"))
    seed_admin_email: str = field(default_factory=lambda: _str("SEED_ADMIN_EMAIL", "admin@smartpos.local"))
    seed_admin_password: str = field(default_factory=lambda: _str("SEED_ADMIN_PASSWORD", "Admin@123"))

    registration: RegistrationSettings = field(default_factory=RegistrationSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)

    @property
    def registration_default_role(self) -> "Role":
        """The configured default, falling back to Cashier if it is misspelt."""
        from app.core.roles import Role

        return Role.parse(self.registration.default_role, default=Role.CASHIER)


settings = Settings()

DB_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
