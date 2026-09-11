"""
The glue between the sign-in screen and the services behind it.

``LoginWindow`` collects credentials and emits a signal; ``AuthService`` decides
whether they are good. Neither knows about the other — this controller is what
connects them, and it is also what owns the answer to "what happens next":

    start()
      `-- always the sign-in window
            |-- signed in, password change required -> forced dialog first
            |-- signed in                           -> dashboard
            |-- forgot password                     -> reset dialog
            `-- no account yet                      -> registration dialog

Keeping this in one class means the flow can be read top to bottom, and neither
window has to grow a reference to the other.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Slot

from app.core.exceptions import SmartPOSError
from app.core.logger import get_logger
from app.core.roles import Permission
from app.db.schema import initialise
from app.models.user import User
from app.repositories.user_repository import user_repository
from app.services.auth_service import auth_service
from app.services.registration_service import registration_service
from app.services.session_service import session_service
from app.ui.change_password_dialog import ChangePasswordDialog
from app.ui.dashboard_window import DashboardWindow
from app.ui.forgot_password_dialog import ForgotPasswordDialog
from app.ui.login_window import LoginWindow
from app.ui.pending_approvals_dialog import PendingApprovalsDialog
from app.ui.register_dialog import RegisterDialog
from app.ui.workers import run_async

logger = get_logger(__name__)


class AuthController(QObject):
    """Owns the sign-in window, the dashboard, and the path between them."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self.login_window: LoginWindow | None = None
        self.dashboard: DashboardWindow | None = None

    # ==================================================================
    # Start-up
    # ==================================================================

    def start(self) -> None:
        """Prepare the database, then open the sign-in window.

        There is no automatic sign-in. The "Remember me" option was taken off
        the sign-in screen, so every launch asks for a password — and any token
        a previous build left on this terminal is revoked here, or it would go
        on letting somebody in with no way left to switch it off.
        """
        initialise()

        auth_service.discard_remembered_terminal()
        self._open_login()

    # ==================================================================
    # Sign-in window
    # ==================================================================

    def _open_login(self, *, prefill: str = "") -> None:
        if self.login_window is None:
            self.login_window = LoginWindow()
            self.login_window.login_attempted.connect(self._on_login_attempted)
            self.login_window.forgot_password_requested.connect(self._on_forgot_password)
            self.login_window.register_requested.connect(self._on_register)

        self.login_window.prefill(prefill or session_service.suggested_username())

        self.login_window.reset()
        self.login_window.show()
        self.login_window.raise_()
        self.login_window.activateWindow()

    @Slot(str, str)
    def _on_login_attempted(self, username: str, password: str) -> None:
        """Check credentials on a worker thread — PBKDF2 is slow by design."""
        window = self.login_window
        window.set_busy(True)

        run_async(
            auth_service.login,
            username,
            password,
            on_success=self._on_login_succeeded,
            on_error=self._on_login_failed,
            on_finished=lambda: window.set_busy(False),
        )

    def _on_login_succeeded(self, user: User) -> None:
        if user.must_change_password:
            # Signed in, but not let through until the temporary password is
            # replaced. The dialog is modal and cannot be dismissed.
            self._force_password_change(user)
            return

        self._enter_application(user)

    def _on_login_failed(self, error: Exception) -> None:
        message = (
            str(error)
            if isinstance(error, SmartPOSError)
            else "Could not sign in. Please try again."
        )

        if not isinstance(error, SmartPOSError):
            logger.exception("Unexpected sign-in failure", exc_info=error)

        self.login_window.show_error(message)

    # ==================================================================
    # Forced password change
    # ==================================================================

    def _force_password_change(self, user: User) -> None:
        dialog = ChangePasswordDialog(
            self.login_window,
            user=user,
            dark_mode=self.login_window.dark_mode,
            forced=True,
        )

        if dialog.exec() != ChangePasswordDialog.DialogCode.Accepted:
            # They chose to sign out rather than set a password.
            auth_service.logout()
            self.login_window.reset()
            self.login_window.show_error(
                "Your password must be changed before you can sign in."
            )
            return

        # The row has changed underneath us; carry the fresh copy forward.
        refreshed = user_repository.get_by_id(user.id)
        session_service.start(refreshed)

        # No message box here: the dialog now confirms the change on screen
        # before it closes, and a second popup saying the same thing is just
        # another click between somebody and the till.
        self._enter_application(refreshed)

    # ==================================================================
    # Dashboard
    # ==================================================================

    def _enter_application(self, user: User) -> None:
        if self.login_window is not None:
            self.login_window.hide()

        self._open_dashboard(user)

    def _open_dashboard(self, user: User) -> None:
        # A fresh dashboard each time, so nothing from the previous user is
        # left on screen.
        if self.dashboard is not None:
            self.dashboard.deleteLater()

        self.dashboard = DashboardWindow(
            username=user.display_name,
            role=user.role.label,
            can_approve=user.can(Permission.APPROVE_REGISTRATIONS),
        )
        self.dashboard.logout_requested.connect(self._on_logout)
        self.dashboard.approvals_requested.connect(self._on_approvals)
        self.dashboard.show()

        # Only an approver ever sees the queue, and the count is what tells
        # them there is anything to look at.
        self.dashboard.set_pending_count(registration_service.pending_count())

    @Slot()
    def _on_logout(self) -> None:
        username = session_service.current_user.username if session_service.current_user else ""

        auth_service.logout()

        if self.dashboard is not None:
            self.dashboard.hide()

        self._open_login(prefill=username)

    # ==================================================================
    # Forgot password
    # ==================================================================

    @Slot()
    def _on_forgot_password(self) -> None:
        window = self.login_window

        dialog = ForgotPasswordDialog(
            window,
            dark_mode=window.dark_mode,
            identifier=window.username.text().strip(),
        )

        if dialog.exec() == ForgotPasswordDialog.DialogCode.Accepted and dialog.reset_username:
            # Drop them back on the sign-in screen with the username filled in,
            # the cursor in the password box and a clean slate.
            window.prefill(dialog.reset_username)
            window.reset()

            # reset() clears the banner, so the confirmation goes up after it —
            # otherwise a completed reset lands on a blank screen and looks
            # like nothing happened.
            window.show_notice(
                f"Password updated for {dialog.reset_username}. "
                "Sign in with the new password."
            )

            QTimer.singleShot(0, window.password.setFocus)

    # ==================================================================
    # Registration
    # ==================================================================

    @Slot()
    def _on_register(self) -> None:
        window = self.login_window

        dialog = RegisterDialog(window, dark_mode=window.dark_mode)
        dialog.exec()

        if not dialog.registered_username:
            return

        # Fill the username in, but do not pretend they can sign in yet — the
        # account is in the approval queue and the sign-in screen has to say so,
        # or the first thing they meet is a refusal they cannot explain.
        window.prefill(dialog.registered_username)
        window.reset()

        # A notice, not an error: the sign-up succeeded. Saying so in the red
        # failure banner made a completed registration look like a problem.
        window.show_notice(
            f"Account created for {dialog.registered_username}. Once an administrator "
            "approves it you can sign in and start using SmartPOS."
        )

    # ==================================================================
    # Approval queue
    # ==================================================================

    @Slot()
    def _on_approvals(self) -> None:
        if self.dashboard is None:
            return

        dialog = PendingApprovalsDialog(
            self.dashboard,
            dark_mode=getattr(self.dashboard, "dark_mode", False),
        )
        dialog.exec()

        self.dashboard.set_pending_count(registration_service.pending_count())
