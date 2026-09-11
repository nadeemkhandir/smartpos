# SmartPOS

A PySide6 point-of-sale / inventory front end with a complete authentication
layer: SQLite storage, hashed passwords, roles, account lockout, "remember me",
and password reset by a one-time code sent to the account's e-mail address.

## Running it

```bash
pip install -r requirements.txt
python main.py
```

The database is created and seeded automatically on the first run.

**First sign-in:** `admin` / `Admin@123`. The account is flagged so a new
password must be chosen immediately; the dialog cannot be dismissed.

## Layout

```
app/
  core/          Configuration, roles, hashing, logging - no Qt, no SQL
    config.py            every setting, read from .env or the environment
    roles.py             Role and Permission enums, and the grants between them
    security.py          PBKDF2 hashing, passcode and token generation
    exceptions.py        the errors services raise, worded for the user
    account_status.py    pending / approved / rejected, and why it is not is_active
    background.py        fire-and-forget threads for notices nobody waits on
    phone.py             mobile numbers: E.164 normalising, validating, masking
    utils.py             UTC timestamps, e-mail masking, formatting
    logger.py            rotating file + console logging

  db/            The SQLite file and its schema
    connection.py        one connection per thread, transactions, queries
    schema.py            the users table, migrations, first-run admin
    smartpos.db          created on first run (not in version control)

  models/        Rows as objects
    user.py              User, with is_locked, role_label, initials, ...

  repositories/  All the SQL, and nothing else
    user_repository.py   CRUD plus the credential bookkeeping

  services/      The rules
    auth_service.py            sign in, sign out, auto sign-in, change password
    registration_service.py    self sign-up, phone proof, the approval queue
    password_reset_service.py  the three-step forgot-password flow
    session_service.py         who is signed in; the remembered token
    user_service.py            staff administration, permission-checked
    email_service.py           SMTP, with a log-file fallback
    sms_service.py             Twilio, with a log-file fallback

  ui/            Screens
    login_window.py                the sign-in screen
    register_dialog.py             details -> texted code -> awaiting approval
    pending_approvals_dialog.py    the approval queue, for admins and managers
    forgot_password_dialog.py      identify -> texted code -> new password
    change_password_dialog.py      forced and voluntary password changes
    dashboard_window.py            the main window after sign-in
    auth_controller.py             wires the screens to the services
    theme.py                       design tokens shared by every screen
    workers.py                     running slow work off the UI thread

tools/
  manage_users.py    command-line account administration
  check_email.py     SMTP diagnosis and a test message
  check_sms.py       SMS gateway diagnosis and a test message
```

The dependency direction is one-way: `ui -> services -> repositories -> db ->
core`. A screen never writes SQL, and a service never imports a widget.

## The `users` table

One table holds everything about an account, including the secrets that let
someone back in:

| Column | Purpose |
| --- | --- |
| `id`, `username`, `email`, `full_name`, `phone` | identity; all three of username, e-mail and phone are unique, and the first two case-insensitive |
| `password_hash` | `pbkdf2_sha256$240000$<salt>$<key>` - never the password |
| `role`, `is_active` | authorisation; `role` is constrained to the known list |
| `status`, `registered_at`, `approved_at`, `approved_by`, `rejected_at`, `rejection_reason` | admission: `pending`, `approved` or `rejected`, and who decided |
| `phone_verified_at` | set when an administrator vouched for the number; null on anything self-registered |
| `must_change_password`, `password_changed_at` | forces a change at next sign-in |
| `failed_attempts`, `locked_until` | lockout after 5 bad tries |
| `last_login_at`, `last_login_ip` | audit trail |
| `remember_token_hash`, `remember_expires_at` | this account's "remember me" token |
| `created_at`, `updated_at` | timestamps, ISO-8601 UTC |

`status` and `is_active` are deliberately separate. `status` is the one-way
story of whether an account was ever admitted; `is_active` is the ordinary
on/off switch for somebody who has left for the season. Sign-in needs both to be
favourable, so reinstating a suspended employee never re-opens the approval
question. `app/core/account_status.py` spells this out.

Schema changes go in `MIGRATIONS` in `app/db/schema.py`, with
`SCHEMA_VERSION` bumped; the migrator runs the missing steps at start-up. A step
may be a SQL string or a callable, and the columns added in version 2 are
applied only if missing, so the same step is a no-op on a database the current
`CREATE TABLE` just built.

## Configuration

Copy `.env.example` to `.env` and edit. Every value has a working default, so
the application runs without one.

### Sending e-mail (approval and password-change notices)

Password-reset codes go by SMS, not e-mail (see below); e-mail carries the
courtesy notices. Without SMTP settings a message is written to
`logs/sent_emails.log` instead of being sent. To send it for real with Gmail:

1. Switch on 2-step verification: <https://myaccount.google.com/security>
2. Create an **app password**: <https://myaccount.google.com/apppasswords>
3. Put those 16 letters in `.env`:

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
SMTP_FROM_ADDRESS=you@gmail.com
```

> **A normal Google account password will not work.** Google stopped accepting
> them over SMTP in 2022 and answers `535 5.7.8 ... BadCredentials`. An app
> password is always 16 letters; Google displays it as four groups of four, and
> the spaces are stripped for you.

Check it without going through the app:

```bash
python -m tools.check_email                  # inspect the settings and connect
python -m tools.check_email you@gmail.com    # also send a test message
```

It reports what `.env` was understood to say, flags the common mistakes (wrong
password shape, port 465 vs 587, a from-address that differs from the
username), then makes a real connection so the verdict comes from the mail
server.

### Texting notices

SmartPOS sends no one-time codes. SMS carries courtesy notices only — *your
account was approved*, *your request was turned down*, *your password was just
changed*. Without gateway settings they are written to `logs/sent_sms.log`
instead of being sent, and nothing else changes, so every flow works on a fresh
clone.

To send for real, with Twilio:

1. Create an account at <https://console.twilio.com>
2. Copy the **Account SID** and **Auth Token** from the dashboard
3. Use your Twilio number (or the trial one) as the sender

```ini
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+14155552671
SMS_DEFAULT_COUNTRY_CODE=+92
```

> **A trial Twilio account can only text numbers you have verified** in its
> console, and prefixes every message. Upgrade before staff depend on it.

`SMS_DEFAULT_COUNTRY_CODE` is what a number typed without one is assumed to be,
so staff can type `0300 1234821` and the account still stores
`+923001234821`. Every spelling of a number — `0300 123 4821`,
`+92-300-123-4821`, `0092 300 1234821` — normalises to that one string, which is
what the UNIQUE index on `phone` is enforcing.

Check it without going through the app:

```bash
python -m tools.check_sms                       # inspect settings, ask Twilio who we are
python -m tools.check_sms --send 0300 1234821   # also send a test message
python -m tools.check_sms --number 0300 1234821 # just show how a number normalises
```

Nothing in the application proves a phone number any more. A number is marked
confirmed only when an administrator enters it, which is what the notices are
sent to:

```bash
python -m tools.manage_users phone admin "0300 1234821"
```

## How someone gets an account

Two ways in, and only the second one can be done without an administrator.

**An administrator creates it.** `tools/manage_users.py create` (below), or a
manager acting through `UserService`. The account is approved from birth and
gets a temporary password to change at first sign-in.

**Someone registers themselves.** The sign-in screen offers *Create one*: full
name, username, e-mail, mobile number and a password, in one form. Usernames are
checked against a reserved list, and the username, e-mail and mobile number must
each be unclaimed. The account is then saved as `pending` and joins the approval
queue. The dialog then confirms the account was created **and** states that an
administrator has to approve it before it can be used — a sign-up that looks
like a sign-in is how somebody ends up at a till believing they have an account.
The sign-in screen repeats it in a green notice, not the red failure banner.

Nothing about a sign-up is verified — no code is sent, and the phone number and
e-mail address are whatever the person typed. **Approval is the only gate**, so
whoever approves is the one actually checking that this is a real member of
staff. The queue shows the details exactly as entered, for that reason.

An administrator or manager then opens **Approvals** in the dashboard sidebar —
the button carries a count, and is not built at all for a role that cannot use
it — picks the role, and approves or rejects. Approving is the only moment a
self-registered account gains any authority, and only an administrator may
approve another administrator.

Rejecting keeps the row, deactivated: the username, e-mail and mobile number
stay claimed, so the same person cannot simply register again into the queue.

The same decisions are available without the GUI:

```bash
python -m tools.manage_users pending
python -m tools.manage_users approve sara --role cashier
python -m tools.manage_users reject sara --reason "Not a member of staff"
```

Set `REGISTRATION_ENABLED=false` to remove self sign-up entirely; the link is
hidden rather than shown and refused.

## Resetting a forgotten password

*Forgot password?* on the sign-in screen asks for a username or e-mail address,
then for a new password. That is the entire flow — there is no code, no link and
no security question.

> **This means anyone standing at the terminal can take over any account they
> can name**, including a manager's or an administrator's, by resetting its
> password and signing in. A cashier who knows the manager's username can give
> themselves the manager's permissions. Treat physical access to a till as
> equivalent to full access to the system.

Three things narrow it, none of which is a second factor:

- only an **approved and active** account can be reset, so the approval queue
  and the disable switch still mean something;
- finishing a reset **signs out every remembered terminal** for that account;
- the owner is **told on both channels** — a text and an e-mail — that the
  password changed, so a takeover is noisy rather than silent. The reset screen
  names those destinations before the new password is saved.

The reset ticket lives in memory for ten minutes and is single-use, so step two
cannot be called for an account step one never looked up.

When the new password is saved the dialog says so — *"the password for X has
been reset successfully"* — and the sign-in screen repeats it in a green notice.
The owner's warning notices go out through `app/core/background.py`, so a mail
server or SMS gateway that is slow cannot hold up that confirmation. Approving
and rejecting sign-ups send their notices the same way. Anything a person is
waiting on finishes in milliseconds; the messages follow behind.

Set `REVEAL_UNKNOWN_ACCOUNT=false` if this is ever exposed beyond a shop floor:
an unknown name is then accepted and quietly refused at the end, so the screen
cannot be used to discover which accounts exist.

If a second factor is wanted back, `app/services/password_reset_service.py` is
the one place to put it — the dialog, the repository and the sign-in path all go
through it.

## Managing accounts

```bash
python -m tools.manage_users list
python -m tools.manage_users create sara sara@shop.com --role cashier --name "Sara Malik"
python -m tools.manage_users passwd sara          # prompts, hidden
python -m tools.manage_users role sara manager
python -m tools.manage_users unlock sara          # clear a lockout
python -m tools.manage_users disable sara
python -m tools.manage_users roles                # what each role may do

python -m tools.manage_users pending              # sign-ups awaiting a decision
python -m tools.manage_users approve sara --role cashier
python -m tools.manage_users reject sara --reason "Not a member of staff"
python -m tools.manage_users phone sara "0300 1234821"
```

New accounts get a temporary password (generated unless you pass `--password`)
and must choose their own at the first sign-in.

`phone` stores the number and marks it confirmed, because whoever can run this
already has the database file. Pass `--unverified` to store it without that
claim.

## Roles

| Role | Who it is for |
| --- | --- |
| `admin` | Full control, including users, settings and audit history |
| `manager` | Sales, stock, staff passwords and reports |
| `cashier` | The till: sells, opens the drawer, reads stock |
| `inventory` | Receives stock, maintains products and suppliers |
| `accountant` | Reads reports and financials, closes the register |
| `viewer` | Read-only, for training or oversight |

Screens should ask `user.can(Permission.X)` rather than testing the role name,
so a new role only means editing `ROLE_PERMISSIONS` in `app/core/roles.py`.
Approving sign-ups is `Permission.APPROVE_REGISTRATIONS`, held by administrators
and managers; only an administrator can approve another administrator.

## How the security works

- **Passwords** are hashed with PBKDF2-HMAC-SHA256, 240,000 iterations and a
  random 16-byte salt. The cost travels inside the hash, so raising it later
  upgrades each password silently at its owner's next sign-in.
- **Sign-in failures** are identical for an unknown username and a wrong
  password, and take the same time, so the form cannot be used to find out who
  has an account. Five failures lock it for ten minutes.
- **Password reset has no second factor.** Naming an account is the whole
  requirement, so anyone who can reach the sign-in screen can set the password
  of any account they can name — a manager's or an administrator's included —
  and then sign in as them. This is a deliberate choice, not an oversight; see
  "Resetting a forgotten password" below.
- **There is no "Remember me".** The option was taken off the sign-in screen, so
  every launch asks for a password and no terminal signs anybody in by itself.
  Any token left by an earlier build is revoked at start-up, because there is no
  longer a switch to turn it off with. The mechanism still exists in
  `AuthService` and works; putting the option back means restoring the checkbox
  and calling `login_with_remembered_token()` at start-up again.
- **Changing a password** clears the lockout, invalidates every remembered
  terminal and burns any outstanding reset code.
- **Self-registered accounts** are refused at sign-in until approved, and the
  check runs *after* the password is verified, so the refusal cannot be used to
  discover which usernames exist. A wrong password on a pending account still
  reads as a wrong password.
- **Phone numbers** are stored in E.164 under a UNIQUE index, so one handset can
  hold at most one account. They are not proved — see above.

