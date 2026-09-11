"""
SmartPOS - the "change your password" dialog.

Used in two situations:

* **Forced** - the account is flagged ``must_change_password``, which is how
  every account created by an administrator (and the first-run ``admin``)
  starts life. The dialog cannot be dismissed; a temporary password handed over
  in person must not survive the first sign-in.
* **Voluntary** - someone changing their own password from the dashboard.

The current password is always re-checked, so an unattended terminal cannot be
used to lock the real owner out.
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
    QVBoxLayout,
)

from app.core.exceptions import SmartPOSError
from app.core.security import password_strength
from app.services.auth_service import auth_service
from app.ui.theme import dialog_stylesheet, tokens_for
from app.ui.workers import run_async


class ChangePasswordDialog(QDialog):
    """Collects the current password and a new one, then saves it."""

    #: Emitted once the password has been changed.
    password_changed = Signal()

    def __init__(self, parent=None, *, user, dark_mode: bool = False, forced: bool = False):
        super().__init__(parent)

        self.user = user
        self.forced = forced
        self._tokens = tokens_for(dark_mode)
        self._busy = False
        self._drag_origin = None

        #: True once the password has actually been changed. The dialog then
        #: shows a confirmation instead of closing straight away.
        self._saved = False

        self.setWindowTitle("Change password")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(452)

        self._build_ui()
        self._wire_events()
        self._apply_theme()

        self.current_password.setFocus()

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
        layout.setSpacing(8)

        layout.addLayout(self._build_header())
        layout.addSpacing(12)

        subtitle = QLabel(
            "Your account was set up with a temporary password. "
            "Choose one of your own to continue."
            if self.forced
            else f"Signed in as {self.user.display_name}."
        )
        subtitle.setObjectName("dialog_subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        layout.addWidget(self._label("Current password"))
        self.current_password = self._password_field("The password you signed in with")
        layout.addWidget(self.current_password)

        layout.addSpacing(6)
        layout.addWidget(self._label("New password"))
        self.new_password = self._password_field("At least 8 characters, with a number")
        layout.addWidget(self.new_password)

        meter = QHBoxLayout()
        meter.setContentsMargins(0, 4, 0, 0)
        meter.setSpacing(10)

        self.strength_bar = QProgressBar()
        self.strength_bar.setRange(0, 4)
        self.strength_bar.setTextVisible(False)

        self.strength_label = QLabel()
        self.strength_label.setObjectName("hint")
        self.strength_label.setMinimumWidth(66)
        self.strength_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        meter.addWidget(self.strength_bar)
        meter.addWidget(self.strength_label)
        layout.addLayout(meter)

        layout.addSpacing(6)
        layout.addWidget(self._label("Confirm new password"))
        self.confirm_password = self._password_field("Type it once more")
        layout.addWidget(self.confirm_password)

        layout.addSpacing(12)
        layout.addWidget(self._build_banner())
        layout.addSpacing(16)
        layout.addLayout(self._build_footer())

        # Everything the form is made of, so the success state can grey the
        # whole thing out in one go rather than naming widgets twice.
        self.form_widgets = (
            subtitle,
            self.current_password,
            self.new_password,
            self.confirm_password,
            self.strength_bar,
            self.strength_label,
        )

    def _build_header(self) -> QHBoxLayout:
        self.header_icon = QLabel()
        self.header_icon.setObjectName("header_icon")
        self.header_icon.setFixedSize(40, 40)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel("Set a new password" if self.forced else "Change your password")
        self.title.setObjectName("dialog_title")

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.header_icon)
        row.addWidget(self.title)
        row.addStretch()
        return row

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("banner_error")
        self.banner.setVisible(False)

        self.banner_icon = QLabel()
        self.banner_icon.setFixedSize(16, 16)

        self.banner_text = QLabel()
        self.banner_text.setObjectName("banner_error_text")
        self.banner_text.setWordWrap(True)

        layout = QHBoxLayout(self.banner)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        layout.addWidget(self.banner_icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.banner_text, 1)
        return self.banner

    def _build_footer(self) -> QHBoxLayout:
        # A forced change offers "Sign out" instead of "Cancel": there has to be
        # a way off the screen, but it must not be a way past it.
        self.cancel_btn = QPushButton("Sign out" if self.forced else "Cancel")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.save_btn = QPushButton("Save password")
        self.save_btn.setObjectName("primary")
        self.save_btn.setMinimumHeight(44)
        self.save_btn.setMinimumWidth(150)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setDefault(True)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.cancel_btn)
        row.addStretch()
        row.addWidget(self.save_btn)
        return row

    @staticmethod
    def _label(text: str) -> QLabel:
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
        action.triggered.connect(lambda: self._toggle_echo(field, action))
        return field

    # ==================================================================
    # Wiring
    # ==================================================================

    def _wire_events(self):
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn.clicked.connect(self.reject)

        for field in (self.current_password, self.new_password, self.confirm_password):
            field.returnPressed.connect(self._save)
            field.textEdited.connect(self._clear_banner)

        self.new_password.textChanged.connect(self._update_strength)

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
            """
        )

        self.header_icon.setPixmap(
            qta.icon("fa5s.user-shield", color=t["primary"]).pixmap(19, 19)
        )
        self._update_strength()

    # ==================================================================
    # Behaviour
    # ==================================================================

    def _save(self):
        if self._busy:
            return

        # After a successful change the same button reads "Done" and its only
        # job is to close the dialog.
        if self._saved:
            self.accept()
            return

        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.confirm_password.text()

        if not current:
            self._fail(self.current_password, "Enter your current password.")
            return

        if not new:
            self._fail(self.new_password, "Choose a new password.")
            return

        if new != confirm:
            self._fail(self.confirm_password, "The two passwords do not match.")
            return

        self._set_busy(True)

        run_async(
            auth_service.change_password,
            self.user.id,
            current,
            new,
            on_success=lambda _: self._on_saved(),
            on_error=self._on_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _on_saved(self):
        """Confirm the change on screen before closing.

        The dialog used to accept() the moment the save returned, so a password
        change looked exactly like a cancelled one — the window simply vanished
        and nothing said it had worked.
        """
        self.password_changed.emit()
        self._show_saved_state()

    def _show_saved_state(self):
        self.title.setText("Password updated")
        self._saved = True

        for widget in self.form_widgets:
            widget.setEnabled(False)

        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()

        self._show_success(
            "Your password has been updated. Use it the next time you sign in."
        )

        self.cancel_btn.setVisible(False)
        self.save_btn.setText("Done")
        self.save_btn.setEnabled(True)
        self.save_btn.setFocus()

    def _show_success(self, message: str):
        self.banner.setObjectName("banner_success")
        self.banner_text.setObjectName("banner_success_text")

        # Object names feed the stylesheet, so the widgets need re-polishing.
        for widget in (self.banner, self.banner_text):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self.banner_icon.setPixmap(
            qta.icon("fa5s.check-circle", color=self._tokens["success"]).pixmap(16, 16)
        )
        self.banner_text.setText(message)
        self.banner.setVisible(True)
        self.adjustSize()

    def _on_error(self, error: Exception):
        message = str(error) if isinstance(error, SmartPOSError) else "Could not change the password."

        if "current password" in message.lower():
            self._fail(self.current_password, message)
        else:
            self._fail(self.new_password, message)

    def _fail(self, field: QLineEdit, message: str):
        self.banner.setObjectName("banner_error")
        self.banner_text.setObjectName("banner_error_text")

        for widget in (self.banner, self.banner_text):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self._mark(field, True)
        field.setFocus()
        field.selectAll()

        self.banner_icon.setPixmap(
            qta.icon("fa5s.exclamation-circle", color=self._tokens["danger"]).pixmap(16, 16)
        )
        self.banner_text.setText(message)
        self.banner.setVisible(True)
        self.adjustSize()

    def _clear_banner(self, _text=None):
        self.banner.setVisible(False)
        for field in (self.current_password, self.new_password, self.confirm_password):
            self._mark(field, False)

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

    def _set_busy(self, busy: bool):
        self._busy = busy

        # Once the password is saved the dialog is showing its confirmation,
        # and this runs *after* that (the worker's "finished" signal follows
        # its "succeeded" one). Re-enabling the form here would put the fields
        # back and relabel the button, undoing the confirmation a moment after
        # it appeared.
        if self._saved:
            self.save_btn.setEnabled(True)
            self.save_btn.setIcon(QIcon())
            QApplication.restoreOverrideCursor()
            return

        for widget in (
            self.current_password,
            self.new_password,
            self.confirm_password,
            self.cancel_btn,
            self.save_btn,
        ):
            widget.setEnabled(not busy)

        if busy:
            self.save_btn.setText("Saving...")
            self.save_btn.setIcon(
                qta.icon(
                    "fa5s.circle-notch",
                    color=self._tokens["disabled_text"],
                    animation=qta.Spin(self.save_btn),
                )
            )
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            self.save_btn.setText("Save password")
            self.save_btn.setIcon(QIcon())
            QApplication.restoreOverrideCursor()

    def _mark(self, field: QLineEdit, has_error: bool):
        if field.property("hasError") == has_error:
            return
        field.setProperty("hasError", has_error)
        field.style().unpolish(field)
        field.style().polish(field)

    @staticmethod
    def _toggle_echo(field: QLineEdit, action):
        showing = field.echoMode() == QLineEdit.EchoMode.Normal
        field.setEchoMode(QLineEdit.EchoMode.Password if showing else QLineEdit.EchoMode.Normal)
        action.setIcon(qta.icon("fa5s.eye" if showing else "fa5s.eye-slash"))

    # ==================================================================
    # Window behaviour
    # ==================================================================

    def showEvent(self, event):
        super().showEvent(event)

        reference = self.parentWidget()
        area = reference.geometry() if reference else QGuiApplication.primaryScreen().availableGeometry()

        geometry = self.frameGeometry()
        geometry.moveCenter(area.center())
        self.move(geometry.topLeft())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and (self.forced or self._busy):
            return
        super().keyPressEvent(event)

    def reject(self):
        if self._busy:
            return
        super().reject()

    def mousePressEvent(self, event):
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
