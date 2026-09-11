"""
Command-line user administration for SmartPOS.

For the jobs that are awkward or impossible from inside the app: creating the
first staff accounts, unlocking someone who is locked out of the sign-in screen,
or resetting a password when nobody can reach the e-mail address on file.

Run it from the project root::

    python -m tools.manage_users list
    python -m tools.manage_users create nadeem nadeem@shop.com --role manager
    python -m tools.manage_users passwd nadeem
    python -m tools.manage_users role nadeem admin
    python -m tools.manage_users unlock nadeem
    python -m tools.manage_users disable nadeem
    python -m tools.manage_users roles
    python -m tools.manage_users pending
    python -m tools.manage_users approve nadeem --role cashier
    python -m tools.manage_users reject nadeem --reason "Not staff"
    python -m tools.manage_users phone nadeem "0300 1234821"

It talks to the repository directly rather than to ``UserService``, because
there is no signed-in user to check permissions against — whoever can run this
already has the database file.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.exceptions import SmartPOSError  # noqa: E402
from app.core.phone import mask_phone, require_phone  # noqa: E402
from app.core.roles import ROLE_PERMISSIONS, Role  # noqa: E402
from app.core.security import validate_password_strength  # noqa: E402
from app.core.utils import humanise_seconds  # noqa: E402
from app.db.schema import initialise  # noqa: E402
from app.repositories.user_repository import user_repository as users  # noqa: E402


def cmd_list(args) -> int:
    accounts = users.list_users(role=args.role, active_only=args.active)

    if not accounts:
        print("No accounts match.")
        return 0

    header = f"{'ID':>3}  {'USERNAME':<16} {'ROLE':<14} {'E-MAIL':<30} {'STATUS':<22} LAST SIGN-IN"
    print(header)
    print("-" * len(header))

    for user in accounts:
        if user.is_pending:
            status = "awaiting approval"
        elif user.is_rejected:
            status = "rejected"
        elif not user.is_active:
            status = "disabled"
        elif user.is_locked:
            status = f"locked ({humanise_seconds(user.lock_seconds_remaining)})"
        elif user.must_change_password:
            status = "must change password"
        else:
            status = "active"

        last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"

        print(
            f"{user.id:>3}  {user.username:<16} {user.role.value:<14} "
            f"{user.email:<30} {status:<22} {last}"
        )

    print(f"\n{len(accounts)} account(s) in {settings.db_path}")
    return 0


def cmd_create(args) -> int:
    password = args.password or _prompt_new_password(args.username)

    user = users.create(
        username=args.username,
        email=args.email,
        password=password,
        role=args.role or Role.CASHIER,
        full_name=args.name or "",
        phone=args.phone,
        # Typed by whoever runs this tool, so it is trusted the same way the
        # texted-code flow trusts a confirmed number. Use the "phone" command
        # with --unverified if that is not wanted.
        phone_verified=bool(args.phone),
        must_change_password=not args.no_change,
    )

    print(f"Created {user.username} ({user.role.label}) <{user.email}>")
    if not args.no_change:
        print("They will be asked to choose their own password at the first sign-in.")
    return 0


def cmd_passwd(args) -> int:
    user = _find(args.username)
    password = args.password or _prompt_new_password(user.username)

    users.set_password(user.id, password, must_change=not args.no_change)

    print(f"Password updated for {user.username}.")
    print("Every remembered terminal for this account has been signed out.")
    return 0


def cmd_role(args) -> int:
    user = _find(args.username)
    users.update_profile(user.id, role=args.role)

    print(f"{user.username} is now a {Role.parse(args.role).label}.")
    return 0


def cmd_pending(args) -> int:
    """Show self-registered accounts waiting for a decision."""
    waiting = users.list_pending()

    if not waiting:
        print("Nothing is waiting for approval.")
        return 0

    header = f"{'ID':>3}  {'USERNAME':<16} {'NAME':<22} {'MOBILE':<17} {'E-MAIL':<26} REGISTERED"
    print(header)
    print("-" * len(header))

    for user in waiting:
        registered = user.registered_at.strftime("%Y-%m-%d %H:%M") if user.registered_at else "?"

        print(
            f"{user.id:>3}  {user.username:<16} {user.display_name[:22]:<22} "
            f"{(user.phone or '-'):<17} {user.email[:26]:<26} {registered}"
        )

    print()
    print(f"{len(waiting)} sign-up(s) awaiting approval.")
    print("Nothing here has been verified — these are details somebody typed into")
    print("the sign-up form. Check them against the person before approving.")
    print()
    print("Approve with:  python -m tools.manage_users approve <username> --role cashier")
    return 0


def cmd_approve(args) -> int:
    """Admit a pending sign-up and give it a role.

    Unlike the dialog, this does not ask who is approving — whoever can run
    this already has the database file — so ``approved_by`` is left empty.
    """
    user = _find(args.username)

    if not user.is_pending:
        print(f"{user.username} is not waiting for approval (status: {user.status.label}).")
        return 1

    approved = users.approve(user.id, role=args.role, approved_by=None)

    print(f"Approved {approved.username} as {approved.role.label}.")
    print("They can sign in now.")
    return 0


def cmd_reject(args) -> int:
    """Turn a pending sign-up down, keeping its username and number claimed."""
    user = _find(args.username)

    if not user.is_pending:
        print(f"{user.username} is not waiting for approval (status: {user.status.label}).")
        return 1

    users.reject(user.id, reason=args.reason or "", rejected_by=None)

    print(f"Rejected {user.username}.")
    print("The row is kept and deactivated, so the username and number stay claimed.")
    return 0


def cmd_phone(args) -> int:
    """Set someone's mobile number, and say whether it counts as confirmed.

    Confirmed here means an administrator vouched for it. Nothing in the
    application proves a number any more, so this is the only way one becomes
    trusted — it is what the approval and password-change notices are texted to.
    """
    user = _find(args.username)
    number = require_phone(args.phone, default_country_code=settings.country_code)

    users.update_profile(user.id, phone=number)

    if args.unverified:
        print(f"{user.username} now has the number {number}, marked unconfirmed.")
        return 0

    # update_profile deliberately clears the verified stamp for any new number,
    # so trusting this one is a separate, explicit step.
    users.mark_phone_verified(user.id)

    print(f"{user.username} now has the confirmed number {number} ({mask_phone(number)}).")
    print("Account notices will be texted there.")
    return 0


def cmd_unlock(args) -> int:
    user = _find(args.username)
    users.clear_lockout(user.id)

    print(f"{user.username} can sign in again.")
    return 0


def cmd_enable(args) -> int:
    return _set_active(args.username, True)


def cmd_disable(args) -> int:
    return _set_active(args.username, False)


def cmd_delete(args) -> int:
    user = _find(args.username)

    if user.is_admin and users.count(role=Role.ADMIN, active_only=True) <= 1:
        print("Refusing: this is the only active administrator.", file=sys.stderr)
        return 1

    confirm = input(f"Delete {user.username} <{user.email}> permanently? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return 0

    users.delete(user.id)
    print(f"Deleted {user.username}.")
    return 0


def cmd_roles(_args) -> int:
    for role in Role:
        permissions = sorted(p.value for p in ROLE_PERMISSIONS[role])
        print(f"\n{role.value:<12} {role.label}")
        print(f"             {role.description}")
        print(f"             {', '.join(permissions)}")
    print()
    return 0


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _set_active(username: str, active: bool) -> int:
    user = _find(username)

    if not active and user.is_admin and users.count(role=Role.ADMIN, active_only=True) <= 1:
        print("Refusing: this is the only active administrator.", file=sys.stderr)
        return 1

    users.set_active(user.id, active)
    print(f"{user.username} is now {'active' if active else 'disabled'}.")
    return 0


def _find(username: str):
    user = users.get_by_identifier(username)

    if user is None:
        raise SmartPOSError(f"No account named '{username}'.")
    return user


def _prompt_new_password(username: str) -> str:
    """Ask twice, without echoing, and hold out for one that passes the rules."""
    while True:
        password = getpass.getpass("New password: ")
        again = getpass.getpass("Repeat password: ")

        if password != again:
            print("They do not match. Try again.\n")
            continue

        try:
            validate_password_strength(password, username=username)
        except SmartPOSError as error:
            print(f"{error}\n")
            continue

        return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_users",
        description="SmartPOS user administration.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    roles = [role.value for role in Role]

    p = sub.add_parser("list", help="show every account")
    p.add_argument("--role", choices=roles, help="only this role")
    p.add_argument("--active", action="store_true", help="hide disabled accounts")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("create", help="add an account")
    p.add_argument("username")
    p.add_argument("email")
    p.add_argument("--role", choices=roles, default=Role.CASHIER.value)
    p.add_argument("--name", help="full name shown in the app")
    p.add_argument("--phone")
    p.add_argument("--password", help="skip the prompt (visible in shell history)")
    p.add_argument("--no-change", action="store_true", help="do not force a change at first sign-in")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("passwd", help="set someone's password")
    p.add_argument("username")
    p.add_argument("--password", help="skip the prompt (visible in shell history)")
    p.add_argument("--no-change", action="store_true", help="do not force a change at next sign-in")
    p.set_defaults(func=cmd_passwd)

    p = sub.add_parser("role", help="change someone's role")
    p.add_argument("username")
    p.add_argument("role", choices=roles)
    p.set_defaults(func=cmd_role)

    p = sub.add_parser("unlock", help="clear a sign-in lockout")
    p.add_argument("username")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("enable", help="reactivate an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("disable", help="deactivate an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("delete", help="remove an account permanently")
    p.add_argument("username")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("pending", help="show sign-ups waiting for approval")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("approve", help="admit a pending sign-up")
    p.add_argument("username")
    p.add_argument("--role", choices=roles, default=Role.CASHIER.value)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="turn a pending sign-up down")
    p.add_argument("username")
    p.add_argument("--reason", help="texted to them, so keep it short and civil")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("phone", help="set someone's mobile number")
    p.add_argument("username")
    p.add_argument("phone", help='e.g. "0300 1234821" or +923001234821')
    p.add_argument(
        "--unverified",
        action="store_true",
        help="store it without treating it as confirmed",
    )
    p.set_defaults(func=cmd_phone)

    p = sub.add_parser("roles", help="list the roles and what each may do")
    p.set_defaults(func=cmd_roles)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    initialise()

    try:
        return args.func(args)
    except SmartPOSError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
