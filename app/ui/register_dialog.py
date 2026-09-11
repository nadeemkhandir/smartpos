"""
SmartPOS - the "Create an account" dialog.

Two pages in a stack:

    1. Your details -> the account is created, switched off and PENDING
    2. Done         -> it is in the approval queue and cannot sign in yet

The dialog owns no rules of its own. It never decides that a username is free
or that a password is strong enough; it asks
:class:`~app.services.registration_service.RegistrationService` and shows the
answer. Creating the account is slow — PBKDF2 is deliberately expensive — so it
runs on a worker thread and the window keeps painting.

Nobody gets in by finishing this dialog. The last page says so plainly, because
a sign-up that looks like a sign-in is how someone ends up standing at a till
believing they have an account.

    dialog = RegisterDialog(parent, dark_mode=True)
    dialog.exec()
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
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
from app.services.registration_service import registration_service
from app.ui.sizing import fit_stack_to_current_page, let_label_wrap
from app.ui.theme import dialog_stylesheet, tokens_for
from app.ui.workers import run_async

STEP_DETAILS = 0
STEP_DONE = 1

#: What the primary button says on each step. Kept in one place because both
#: the step machine and the busy state need to put it back.
PRIMARY_LABELS = {
    STEP_DETAILS: "Create account",
    STEP_DONE: "Back to sign in",
}


class RegisterDialog(QDialog):
    """Guides one person through registering themselves."""

    #: Emitted with the username once a sign-up has reached the approval queue.
    registered = Signal(str)

    def __init__(self, parent=None, *, dark_mode: bool = False):
        super().__init__(parent)

        self._dark_mode = dark_mode
        self._tokens = tokens_for(dark_mode)
        self._busy = False
        self._drag_origin = None

        #: Set once the account has actually been created.
        self.registered_username = ""

        self.setWindowTitle("Create an account")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(560)

        self._build_ui()
        self._wire_events()
        self._apply_theme()

        self._show_step(STEP_DETAILS)

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
        layout.addSpacing(16)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_details_page())
        self.pages.addWidget(self._build_done_page())
        layout.addWidget(self.pages)

        layout.addSpacing(14)
        layout.addWidget(self._build_banner())
        layout.addSpacing(18)
        layout.addLayout(self._build_footer())

    def _build_header(self) -> QVBoxLayout:
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(40, 40)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_icon.setObjectName("header_icon")

        self.close_btn = QPushButton()
        self.close_btn.setObjectName("chrome")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Close")

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.header_icon)
        top.addStretch()
        top.addWidget(self.close_btn)

        self.title = QLabel("Create an account")
        self.title.setObjectName("dialog_title")
        self.title.setWordWrap(True)

        header = QVBoxLayout()
        header.setSpacing(12)
        header.addLayout(top)
        header.addWidget(self.title)
        return header

    # ---------------------------------------------------- step 1

    def _build_details_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(
            self._subtitle(
                "Tell us who you are. A manager has to approve the account "
                "before you can sign in."
            )
        )
        layout.addSpacing(12)

        # Two columns for the identity fields: six stacked rows would make the
        # dialog taller than a small till screen.
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("e.g. Nadeem Khan")
        self.full_name.setMinimumHeight(42)

        self.username = QLineEdit()
        self.username.setPlaceholderText("e.g. nadeem")
        self.username.setMinimumHeight(42)
        # Mirrors the service's own rule, so the field simply will not accept
        # a character the service would reject a moment later.
        self.username.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,31}"))
        )

        self.email = QLineEdit()
        self.email.setPlaceholderText("e.g. nadeem@yourshop.com")
        self.email.setMinimumHeight(42)

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("e.g. 0300 1234821")
        self.phone.setMinimumHeight(42)

        grid.addWidget(self._field_label("Full name"), 0, 0)
        grid.addWidget(self.full_name, 1, 0)
        grid.addWidget(self._field_label("Username"), 0, 1)
        grid.addWidget(self.username, 1, 1)

        grid.addWidget(self._field_label("E-mail address"), 2, 0)
        grid.addWidget(self.email, 3, 0)
        grid.addWidget(self._field_label("Mobile number"), 2, 1)
        grid.addWidget(self.phone, 3, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self.phone_hint = QLabel(
            "Your manager uses this number to reach you about the account. "
            f"Numbers without a country code are treated as "
            f"{settings.country_code}."
        )
        self.phone_hint.setObjectName("hint")
        self.phone_hint.setWordWrap(True)
        layout.addWidget(self.phone_hint)

        layout.addSpacing(10)
        layout.addWidget(self._field_label("Password"))
        self.password = self._password_field(
            f"At least {settings.security.min_password_length} characters"
        )
        layout.addWidget(self.password)

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

        layout.addSpacing(8)
        layout.addWidget(self._field_label("Confirm password"))
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

        self.done_title = QLabel("Account created")
        self.done_title.setObjectName("dialog_title")
        self.done_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.done_text = QLabel()
        self.done_text.setObjectName("dialog_subtitle")
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_text.setWordWrap(True)
        let_label_wrap(self.done_text)

        self.done_next = QLabel()
        self.done_next.setObjectName("done_next")
        self.done_next.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_next.setWordWrap(True)
        let_label_wrap(self.done_next)

        layout.addWidget(self.done_icon)
        layout.addWidget(self.done_title)
        layout.addWidget(self.done_text)
        layout.addSpacing(6)
        layout.addWidget(self.done_next)
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
        self.back_btn = QPushButton("Cancel")
        self.back_btn.setObjectName("ghost")
        self.back_btn.setMinimumHeight(44)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.primary_btn = QPushButton("Create account")
        self.primary_btn.setObjectName("primary")
        self.primary_btn.setMinimumHeight(44)
        self.primary_btn.setMinimumWidth(160)
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
        field.setMinimumHeight(42)

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
        self.back_btn.clicked.connect(self.reject)
        self.close_btn.clicked.connect(self.reject)

        for field in self._all_fields():
            field.returnPressed.connect(self._advance)
            field.textEdited.connect(self._clear_banner_on_typing)

        self.password.textChanged.connect(self._update_strength)
        self.confirm_password.textChanged.connect(self._update_strength)

    def _all_fields(self) -> tuple[QLineEdit, ...]:
        return (
            self.full_name,
            self.username,
            self.email,
            self.phone,
            self.password,
            self.confirm_password,
        )

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

            QLabel#done_next {{
                background: {t["primary_soft"]};
                border-radius: 10px;
                color: {t["text_secondary"]};
                font-size: 13px;
                padding: 12px 14px;
            }}
            """
        )

        self.header_icon.setPixmap(qta.icon("fa5s.user-plus", color=t["primary"]).pixmap(19, 19))
        self.close_btn.setIcon(qta.icon("fa5s.times", color=t["text_muted"]))
        self.done_icon.setPixmap(
            qta.icon("fa5s.check-circle", color=t["success"]).pixmap(48, 48)
        )

    # ==================================================================
    # Step machine
    # ==================================================================

    def _show_step(self, step: int, *, keep_banner: bool = False):
        self.pages.setCurrentIndex(step)
        self.primary_btn.setText(PRIMARY_LABELS[step])

        if not keep_banner:
            self._clear_banner()

        if step == STEP_DETAILS:
            self.title.setText("Create an account")
            self.back_btn.setVisible(True)
            self.full_name.setFocus()
        else:
            self.title.setText("Almost there")
            self.back_btn.setVisible(False)
            self.primary_btn.setFocus()

        fit_stack_to_current_page(self.pages, self)

    def _advance(self):
        """The primary button, whatever it happens to say right now."""
        if self._busy:
            return

        if self.pages.currentIndex() == STEP_DETAILS:
            self._submit_details()
        else:
            self.accept()

    # ------------------------------------------------------------------
    # Creating the account
    # ------------------------------------------------------------------

    def _submit_details(self):
        values = {
            "full_name": self.full_name.text().strip(),
            "username": self.username.text().strip(),
            "email": self.email.text().strip(),
            "phone": self.phone.text().strip(),
            "password": self.password.text(),
            "confirm_password": self.confirm_password.text(),
        }

        # Only the empty-field check happens here. Every other rule belongs to
        # the service, which is the one that has to be right.
        required = [
            (self.full_name, values["full_name"], "Enter your full name."),
            (self.username, values["username"], "Choose a username."),
            (self.email, values["email"], "Enter your e-mail address."),
            (self.phone, values["phone"], "Enter your mobile number."),
            (self.password, values["password"], "Choose a password."),
        ]

        for field, value, message in required:
            if not value:
                self._mark(field, True)
                self._show_error(message)
                field.setFocus()
                return
            self._mark(field, False)

        if values["password"] != values["confirm_password"]:
            self._mark(self.confirm_password, True)
            self._show_error("The two passwords do not match.")
            self.confirm_password.setFocus()
            self.confirm_password.selectAll()
            return

        self._mark(self.confirm_password, False)
        self._set_busy(True, "Creating...")

        run_async(
            registration_service.register,
            on_success=self._on_registered,
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
            **values,
        )

    def _on_registered(self, user: User):
        self.registered_username = user.username

        self.done_text.setText(
            f"Your account <b>{user.username}</b> was created successfully."
        )

        # Spelled out rather than implied. Someone who has just filled in a
        # sign-up form reasonably expects to be able to sign in, and finding
        # out otherwise at the password prompt is the worst place to learn it.
        self.done_next.setText(
            "An administrator still has to approve it. <b>Once your account is "
            "approved you can sign in and start using SmartPOS.</b> Until then "
            "the sign-in screen will turn you away."
        )

        self._show_step(STEP_DONE, keep_banner=True)
        self._show_success("Registration complete — waiting for approval.")
        self.registered.emit(user.username)

    # ------------------------------------------------------------------
    # Password strength
    # ------------------------------------------------------------------

    def _update_strength(self):
        password = self.password.text()
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

        for widget in (*self._all_fields(), self.back_btn):
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
        if isinstance(error, (SmartPOSError, PermissionError)):
            self._show_error(str(error))
        else:
            self._show_error("Something went wrong. Please try again.")

    def _show_error(self, message: str):
        self._set_banner("banner_error", "fa5s.exclamation-circle", self._tokens["danger"], message)

    def _show_success(self, message: str):
        self._set_banner("banner_success", "fa5s.check-circle", self._tokens["success"], message)

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
        # Escape closes, but never mid-request: the account may be half-written.
        if event.key() == Qt.Key.Key_Escape and self._busy:
            return
        super().keyPressEvent(event)

    def reject(self):
        if self._busy:
            return

        # An account that exists is in the approval queue now, and closing this
        # window must not quietly withdraw it.
        super().reject()
