"""
SmartPOS - the "Forgot password?" dialog.

Three pages in a stack, matching
:class:`~app.services.password_reset_service.PasswordResetService`:

    1. Who are you?      -> the account is found and a short-lived ticket opened
    2. Choose a password -> saved, and every remembered terminal signed out
    3. Done              -> back to the sign-in screen

There is no passcode step and no notification: naming the account is the only
thing this screen asks for, and nothing tells the account owner afterwards. The
service module explains the trade-off in full.

The dialog owns no rules of its own. It never decides that an account may be
reset or that a password is strong enough; it asks the service and shows the
answer. Hashing is slow by design, so saving runs on a worker thread and the
window keeps painting.

    dialog = ForgotPasswordDialog(parent, dark_mode=True, identifier="nadeem")
    dialog.exec()
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import settings
from app.core.exceptions import SmartPOSError
from app.core.security import password_strength
from app.models.user import User
from app.services.password_reset_service import ResetRequest, password_reset_service
from app.ui.sizing import fit_stack_to_current_page, let_label_wrap
from app.ui.theme import dialog_stylesheet, tokens_for
from app.ui.workers import run_async

STEP_IDENTIFY = 0
STEP_PASSWORD = 1
STEP_DONE = 2

#: What the primary button says on each step. Kept in one place because both
#: the step machine and the busy state need to put it back.
PRIMARY_LABELS = {
    STEP_IDENTIFY: "Continue",
    STEP_PASSWORD: "Update password",
    STEP_DONE: "Back to sign in",
}


class ForgotPasswordDialog(QDialog):
    """Guides one person through resetting a password."""

    #: Emitted with the username once a password has actually been changed.
    password_reset = Signal(str)

    def __init__(self, parent=None, *, dark_mode: bool = False, identifier: str = ""):
        super().__init__(parent)

        self._dark_mode = dark_mode
        self._tokens = tokens_for(dark_mode)
        self._request: ResetRequest | None = None
        self._busy = False
        self._drag_origin = None

        #: Set once the password has actually been changed.
        self.reset_username = ""

        self.setWindowTitle("Reset your password")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(500)

        self._build_ui()
        self._wire_events()
        self._apply_theme()

        self.identifier.setText(identifier)
        self._show_step(STEP_IDENTIFY)

    # ==================================================================
    # Construction
    # ==================================================================

    def _build_ui(self):
        self.card = QFrame(self)
        self.card.setObjectName("card")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 14)
        shadow.setColor(Qt.GlobalColor.black)
        self.card.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 26)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(30, 24, 30, 26)
        layout.setSpacing(0)

        layout.addLayout(self._build_header())
        layout.addSpacing(18)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_identify_page())
        self.pages.addWidget(self._build_password_page())
        self.pages.addWidget(self._build_done_page())
        layout.addWidget(self.pages)

        layout.addSpacing(14)
        layout.addWidget(self._build_banner())
        layout.addSpacing(18)
        layout.addLayout(self._build_footer())

    def _build_header(self) -> QVBoxLayout:
        """Icon, step and close on one row; the title gets a line of its own.

        Sharing a row with the step pill left nothing for the title, and
        "Reset your password" came out clipped to "Reset your passw". Titles
        change with the step, so giving them the full width is the only
        arrangement that cannot break.
        """
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(40, 40)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_icon.setObjectName("header_icon")

        self.step_pill = QLabel("Step 1 of 2")
        self.step_pill.setObjectName("step_pill")

        self.close_btn = QPushButton()
        self.close_btn.setObjectName("chrome")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Close")

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.header_icon)
        top.addStretch()
        top.addWidget(self.step_pill)
        top.addWidget(self.close_btn)

        self.title = QLabel("Reset your password")
        self.title.setObjectName("dialog_title")
        self.title.setWordWrap(True)

        header = QVBoxLayout()
        header.setSpacing(12)
        header.addLayout(top)
        header.addWidget(self.title)
        return header

    # ---------------------------------------------------- step 1

    def _build_identify_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(
            self._subtitle(
                "Enter your username or the e-mail address on your account, "
                "then choose a new password."
            )
        )
        layout.addSpacing(10)

        layout.addWidget(self._field_label("Username or e-mail"))

        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText("e.g. nadeem or nadeem@yourshop.com")
        self.identifier.setClearButtonEnabled(True)
        self.identifier.setMinimumHeight(44)
        layout.addWidget(self.identifier)

        layout.addStretch()
        return page

    # ---------------------------------------------------- step 2

    def _build_password_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.resetting_for = QLabel()
        self.resetting_for.setObjectName("dialog_subtitle")
        self.resetting_for.setWordWrap(True)
        layout.addWidget(self.resetting_for)
        layout.addSpacing(10)

        layout.addWidget(self._field_label("New password"))
        self.new_password = self._password_field(
            f"At least {settings.security.min_password_length} characters"
        )
        layout.addWidget(self.new_password)

        meter_row = QHBoxLayout()
        meter_row.setContentsMargins(0, 4, 0, 0)
        meter_row.setSpacing(10)

        self.strength_bar = QProgressBar()
        self.strength_bar.setRange(0, 4)
        self.strength_bar.setValue(0)
        self.strength_bar.setTextVisible(False)

        self.strength_label = QLabel()
        self.strength_label.setObjectName("hint")
        self.strength_label.setMinimumWidth(66)
        self.strength_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        meter_row.addWidget(self.strength_bar)
        meter_row.addWidget(self.strength_label)
        layout.addLayout(meter_row)

        layout.addSpacing(10)
        layout.addWidget(self._field_label("Confirm new password"))
        self.confirm_password = self._password_field("Type it once more")
        layout.addWidget(self.confirm_password)

        layout.addStretch()
        return page

    # ---------------------------------------------------- done

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        # Deliberately no layout-level AlignCenter. It sizes every child to its
        # preferred width instead of the card's, which squeezes a wrapped
        # message into half the dialog and clips the end of it. The labels
        # centre their own text, and the stretches below centre the group.
        layout.addStretch()

        self.done_icon = QLabel()
        self.done_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        done_title = QLabel("All done")
        done_title.setObjectName("dialog_title")
        done_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.done_text = QLabel()
        self.done_text.setObjectName("dialog_subtitle")
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_text.setWordWrap(True)
        let_label_wrap(self.done_text)

        layout.addWidget(self.done_icon)
        layout.addWidget(done_title)
        layout.addWidget(self.done_text)
        layout.addStretch()
        return page

    # ---------------------------------------------------- shared chrome

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("banner_error")
        self.banner.setVisible(False)

        self.banner_icon = QLabel()
        self.banner_icon.setFixedSize(16, 16)

        self.banner_text = QLabel()
        self.banner_text.setObjectName("banner_error_text")
        self.banner_text.setWordWrap(True)
        let_label_wrap(self.banner_text)

        layout = QHBoxLayout(self.banner)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        layout.addWidget(self.banner_icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.banner_text, 1)

        return self.banner

    def _build_footer(self) -> QHBoxLayout:
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("ghost")
        self.back_btn.setMinimumHeight(44)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.primary_btn = QPushButton("Continue")
        self.primary_btn.setObjectName("primary")
        self.primary_btn.setMinimumHeight(44)
        self.primary_btn.setMinimumWidth(150)
        self.primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_btn.setDefault(True)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.back_btn)
        row.addStretch()
        row.addWidget(self.primary_btn)
        return row

    def _subtitle(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("dialog_subtitle")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("field_label")
        return label

    def _password_field(self, placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(placeholder)
        field.setMinimumHeight(44)

        action = field.addAction(
            qta.icon("fa5s.eye", color=self._tokens["text_muted"]),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        action.setToolTip("Show password")
        action.triggered.connect(lambda: self._toggle_echo(field, action))

        return field

    # ==================================================================
    # Wiring
    # ==================================================================

    def _wire_events(self):
        self.primary_btn.clicked.connect(self._advance)
        self.back_btn.clicked.connect(self._go_back)
        self.close_btn.clicked.connect(self.reject)

        for field in (self.identifier, self.new_password, self.confirm_password):
            field.returnPressed.connect(self._advance)
            field.textEdited.connect(self._clear_banner_on_typing)

        self.new_password.textChanged.connect(self._update_strength)
        self.confirm_password.textChanged.connect(self._update_strength)

    # ==================================================================
    # Theming
    # ==================================================================

    def _apply_theme(self):
        t = self._tokens

        self.setStyleSheet(
            dialog_stylesheet(t)
            + f"""
            QFrame#card {{
                background: {t["surface"]};
                border: 1px solid {t["border"]};
                border-radius: 16px;
            }}

            QLabel#header_icon {{
                background: {t["primary_soft"]};
                border-radius: 12px;
            }}

            QPushButton#chrome {{
                background: transparent;
                border: none;
                border-radius: 8px;
            }}

            QPushButton#chrome:hover {{ background: {t["chrome_hover"]}; }}
            """
        )

        self.header_icon.setPixmap(qta.icon("fa5s.key", color=t["primary"]).pixmap(19, 19))
        self.close_btn.setIcon(qta.icon("fa5s.times", color=t["text_muted"]))
        self.done_icon.setPixmap(qta.icon("fa5s.check-circle", color=t["success"]).pixmap(48, 48))

    # ==================================================================
    # Step machine
    # ==================================================================

    def _show_step(self, step: int, *, keep_banner: bool = False):
        self.pages.setCurrentIndex(step)
        self.primary_btn.setText(PRIMARY_LABELS[step])

        if not keep_banner:
            self._clear_banner()

        if step == STEP_IDENTIFY:
            self.step_pill.setVisible(True)
            self.step_pill.setText("Step 1 of 2")
            self.title.setText("Reset your password")
            self.back_btn.setText("Cancel")
            self.back_btn.setVisible(True)
            self.identifier.setFocus()
            self.identifier.selectAll()

        elif step == STEP_PASSWORD:
            self.step_pill.setVisible(True)
            self.step_pill.setText("Step 2 of 2")
            self.title.setText("Choose a new password")
            self.back_btn.setText("Back")
            self.back_btn.setVisible(True)
            self.new_password.clear()
            self.confirm_password.clear()
            self._update_strength()
            self.new_password.setFocus()

        else:
            self.step_pill.setVisible(False)
            self.title.setText("Password updated")
            self.back_btn.setVisible(False)
            self.primary_btn.setFocus()

        fit_stack_to_current_page(self.pages, self)

    def _advance(self):
        """The primary button, whatever it happens to say right now."""
        if self._busy:
            return

        step = self.pages.currentIndex()

        if step == STEP_IDENTIFY:
            self._find_account()
        elif step == STEP_PASSWORD:
            self._save_password()
        else:
            self.accept()

    def _go_back(self):
        if self._busy:
            return

        if self.pages.currentIndex() == STEP_PASSWORD:
            self._discard_request()
            self._show_step(STEP_IDENTIFY)
        else:
            self.reject()

    # ------------------------------------------------------------------
    # Step 1 - find the account
    # ------------------------------------------------------------------

    def _find_account(self):
        identifier = self.identifier.text().strip()

        if not identifier:
            self._mark(self.identifier, True)
            self._show_error("Enter your username or e-mail address.")
            self.identifier.setFocus()
            return

        self._mark(self.identifier, False)
        self._set_busy(True, "Checking...")

        run_async(
            password_reset_service.begin,
            identifier,
            on_success=self._on_account_found,
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _on_account_found(self, request: ResetRequest):
        self._request = request

        self.resetting_for.setText(
            f"Setting a new password for <b>{request.display_name}</b> "
            f"({request.username})."
        )
        self._show_step(STEP_PASSWORD)

    # ------------------------------------------------------------------
    # Step 2 - save
    # ------------------------------------------------------------------

    def _save_password(self):
        if self._request is None:
            return

        new = self.new_password.text()
        confirm = self.confirm_password.text()

        if not new:
            self._mark(self.new_password, True)
            self._show_error("Choose a new password.")
            self.new_password.setFocus()
            return

        self._mark(self.new_password, False)
        self._mark(self.confirm_password, False)
        self._set_busy(True, "Saving...")

        run_async(
            password_reset_service.set_new_password,
            self._request.ticket,
            new,
            confirm,
            on_success=self._on_password_saved,
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _on_password_saved(self, user: User):
        self.reset_username = user.username
        self._request = None

        self.done_text.setText(
            f"The password for <b>{user.username}</b> has been reset successfully.<br><br>"
            "Sign in with the new password from now on."
        )

        self._show_step(STEP_DONE, keep_banner=True)
        self._show_success("Password updated successfully.")
        self.password_reset.emit(user.username)

    # ------------------------------------------------------------------
    # Password strength
    # ------------------------------------------------------------------

    def _update_strength(self):
        password = self.new_password.text()
        score, verdict = password_strength(password)

        colours = {
            0: self._tokens["border_strong"],
            1: self._tokens["danger"],
            2: self._tokens["warning"],
            3: self._tokens["primary"],
            4: self._tokens["success"],
        }

        self.strength_bar.setValue(score)
        self.strength_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {colours[score]}; border-radius: 3px; }}"
        )
        self.strength_label.setText(verdict if password else "")

    # ------------------------------------------------------------------
    # Busy state and messages
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool, label: str = ""):
        self._busy = busy

        for widget in (
            self.identifier,
            self.new_password,
            self.confirm_password,
            self.back_btn,
        ):
            widget.setEnabled(not busy)

        self.primary_btn.setEnabled(not busy)

        if busy:
            self.primary_btn.setText(label or "Working...")
            self.primary_btn.setIcon(
                qta.icon(
                    "fa5s.circle-notch",
                    color=self._tokens["disabled_text"],
                    animation=qta.Spin(self.primary_btn),
                )
            )
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            self.primary_btn.setIcon(QIcon())
            # The step may have moved on while the worker ran, so take the
            # label from where the dialog is now rather than where it was.
            self.primary_btn.setText(PRIMARY_LABELS[self.pages.currentIndex()])
            QApplication.restoreOverrideCursor()

    def _on_service_error(self, error: Exception):
        if isinstance(error, SmartPOSError):
            self._show_error(str(error))
        else:
            self._show_error("Something went wrong. Please try again.")

    def _show_error(self, message: str):
        self._set_banner("banner_error", "fa5s.exclamation-circle", self._tokens["danger"], message)

    def _show_success(self, message: str):
        self._set_banner("banner_success", "fa5s.check-circle", self._tokens["success"], message)

    def _show_info(self, message: str):
        self._set_banner("banner_info", "fa5s.info-circle", self._tokens["warning"], message)

    def _set_banner(self, style: str, icon: str, colour: str, message: str):
        self.banner.setObjectName(style)
        self.banner_text.setObjectName(f"{style}_text")

        # Object names feed the stylesheet, so the widgets need re-polishing.
        for widget in (self.banner, self.banner_text):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self.banner_icon.setPixmap(qta.icon(icon, color=colour).pixmap(16, 16))
        self.banner_text.setText(message)
        self.banner.setVisible(True)
        self.adjustSize()

    def _clear_banner(self):
        self.banner.setVisible(False)
        self.banner_text.clear()

    def _clear_banner_on_typing(self, _text: str):
        if self.banner.isVisible() and self.banner.objectName() == "banner_error":
            self._clear_banner()

    def _mark(self, field: QLineEdit, has_error: bool):
        if field.property("hasError") == has_error:
            return
        field.setProperty("hasError", has_error)
        field.style().unpolish(field)
        field.style().polish(field)

    @staticmethod
    def _toggle_echo(field: QLineEdit, action):
        showing = field.echoMode() == QLineEdit.EchoMode.Normal
        field.setEchoMode(
            QLineEdit.EchoMode.Password if showing else QLineEdit.EchoMode.Normal
        )
        action.setIcon(qta.icon("fa5s.eye" if showing else "fa5s.eye-slash"))
        action.setToolTip("Show password" if showing else "Hide password")

    # ==================================================================
    # Window behaviour
    # ==================================================================

    def _discard_request(self):
        """Drop the open ticket so it cannot be used after backing out."""
        if self._request is None:
            return

        ticket = self._request.ticket
        self._request = None
        password_reset_service.cancel(ticket)

    def showEvent(self, event):
        super().showEvent(event)
        self._centre_on_parent()

    def _centre_on_parent(self):
        reference = self.parentWidget()
        area = (
            reference.geometry()
            if reference
            else QGuiApplication.primaryScreen().availableGeometry()
        )

        geometry = self.frameGeometry()
        geometry.moveCenter(area.center())
        self.move(geometry.topLeft())

    def mousePressEvent(self, event):
        # Frameless, so the card itself has to be draggable.
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        # Escape closes, but never mid-request: the password may be half-saved.
        if event.key() == Qt.Key.Key_Escape and self._busy:
            return
        super().keyPressEvent(event)

    def reject(self):
        if self._busy:
            return

        # Close the ticket rather than leaving it usable until it expires.
        if self.pages.currentIndex() != STEP_DONE:
            self._discard_request()

        super().reject()
