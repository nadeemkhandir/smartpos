"""
SmartPOS - the approval queue.

Everyone who has registered themselves and confirmed a mobile number waits
here until somebody holding ``Permission.APPROVE_REGISTRATIONS`` decides what
they are. Approving is where a role is actually chosen, so this screen is the
one place a self-registered account gains any authority at all.

The table is the whole interface: pick a row, pick a role, approve or reject.
Both decisions are irreversible from here on purpose — a rejected row keeps its
username and number claimed, and an approved account is edited from user
management afterwards rather than un-approved.

    dialog = PendingApprovalsDialog(parent, dark_mode=True)
    dialog.exec()
"""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.exceptions import SmartPOSError
from app.core.roles import Role
from app.core.utils import utcnow
from app.models.user import User
from app.services.registration_service import registration_service
from app.services.session_service import session_service
from app.ui.theme import dialog_stylesheet, tokens_for
from app.ui.workers import run_async

PAGE_LIST = 0
PAGE_EMPTY = 1

COLUMNS = ("Name", "Username", "Mobile", "E-mail", "Requested")


class PendingApprovalsDialog(QDialog):
    """Lets an approver admit or refuse self-registered accounts."""

    #: Emitted after any decision, so a dashboard badge can re-count.
    queue_changed = Signal()

    def __init__(self, parent=None, *, dark_mode: bool = False):
        super().__init__(parent)

        self._dark_mode = dark_mode
        self._tokens = tokens_for(dark_mode)
        self._pending: list[User] = []
        self._busy = False
        self._drag_origin = None

        self.setWindowTitle("Account approvals")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(880)

        self._build_ui()
        self._wire_events()
        self._apply_theme()

        self.refresh()

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
        self.pages.addWidget(self._build_table())
        self.pages.addWidget(self._build_empty_state())
        layout.addWidget(self.pages, 1)

        layout.addSpacing(12)
        layout.addWidget(self._build_banner())
        layout.addSpacing(16)
        layout.addLayout(self._build_footer())

    def _build_header(self) -> QVBoxLayout:
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(40, 40)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_icon.setObjectName("header_icon")

        self.count_pill = QLabel("0 waiting")
        self.count_pill.setObjectName("step_pill")

        self.refresh_btn = QPushButton()
        self.refresh_btn.setObjectName("chrome")
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setToolTip("Refresh")

        self.close_btn = QPushButton()
        self.close_btn.setObjectName("chrome")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Close")

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.header_icon)
        top.addStretch()
        top.addWidget(self.count_pill)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.close_btn)

        self.title = QLabel("Account approvals")
        self.title.setObjectName("dialog_title")

        self.subtitle = QLabel(
            "These people registered themselves and confirmed a mobile number. "
            "Choose the role each one should have, then approve or reject."
        )
        self.subtitle.setObjectName("dialog_subtitle")
        self.subtitle.setWordWrap(True)

        header = QVBoxLayout()
        header.setSpacing(10)
        header.addLayout(top)
        header.addWidget(self.title)
        header.addWidget(self.subtitle)
        return header

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(240)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setHighlightSections(False)

        return self.table

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_title = QLabel("Nothing waiting")
        empty_title.setObjectName("dialog_title")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_text = QLabel("Every sign-up has been dealt with.")
        empty_text.setObjectName("dialog_subtitle")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.empty_icon)
        layout.addWidget(empty_title)
        layout.addWidget(empty_text)
        return page

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
        self.role_label = QLabel("Approve as")
        self.role_label.setObjectName("field_label")

        self.role_combo = QComboBox()
        self.role_combo.setMinimumHeight(44)
        self.role_combo.setMinimumWidth(190)
        self._fill_roles()

        self.reject_btn = QPushButton("Reject")
        self.reject_btn.setObjectName("ghost")
        self.reject_btn.setMinimumHeight(44)
        self.reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.approve_btn = QPushButton("Approve")
        self.approve_btn.setObjectName("primary")
        self.approve_btn.setMinimumHeight(44)
        self.approve_btn.setMinimumWidth(150)
        self.approve_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approve_btn.setDefault(True)

        self.done_btn = QPushButton("Close")
        self.done_btn.setObjectName("ghost")
        self.done_btn.setMinimumHeight(44)
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.done_btn)
        row.addStretch()
        row.addWidget(self.role_label)
        row.addWidget(self.role_combo)
        row.addSpacing(6)
        row.addWidget(self.reject_btn)
        row.addWidget(self.approve_btn)
        return row

    def _fill_roles(self):
        """Offer every role the signed-in approver is allowed to hand out.

        Only an administrator may mint another administrator, so for anybody
        else that entry is simply not in the list — the service refuses it too,
        but a choice that can only fail does not belong on screen.
        """
        approver = session_service.current_user
        self.role_combo.clear()

        for role in Role.choices():
            if role is Role.ADMIN and not (approver and approver.is_admin):
                continue
            self.role_combo.addItem(role.label, role)

        default = registration_service.default_role
        index = self.role_combo.findData(default)
        if index >= 0:
            self.role_combo.setCurrentIndex(index)

    # ==================================================================
    # Wiring
    # ==================================================================

    def _wire_events(self):
        self.close_btn.clicked.connect(self.reject)
        self.done_btn.clicked.connect(self.accept)
        self.refresh_btn.clicked.connect(self.refresh)
        self.approve_btn.clicked.connect(self._approve_selected)
        self.reject_btn.clicked.connect(self._reject_selected)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(self._approve_selected)

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

            QTableWidget {{
                background: {t["surface"]};
                alternate-background-color: {t["field_bg"]};
                border: 1px solid {t["border"]};
                border-radius: 10px;
                color: {t["text"]};
                font-size: 13px;
                gridline-color: transparent;
            }}

            QTableWidget::item {{
                padding: 10px 8px;
                border: none;
            }}

            QTableWidget::item:selected {{
                background: {t["primary_soft"]};
                color: {t["text"]};
            }}

            QHeaderView::section {{
                background: {t["field_bg"]};
                color: {t["text_muted"]};
                font-size: 12px;
                font-weight: 600;
                padding: 10px 8px;
                border: none;
                border-bottom: 1px solid {t["border"]};
            }}

            QComboBox {{
                background: {t["field_bg"]};
                border: 1px solid {t["border_strong"]};
                border-radius: 9px;
                color: {t["text"]};
                font-size: 13px;
                padding: 0 12px;
            }}

            QComboBox:focus {{ border-color: {t["primary"]}; }}
            QComboBox::drop-down {{ border: none; width: 26px; }}

            QComboBox QAbstractItemView {{
                background: {t["surface"]};
                border: 1px solid {t["border"]};
                color: {t["text"]};
                selection-background-color: {t["primary_soft"]};
                selection-color: {t["text"]};
                outline: none;
            }}
            """
        )

        self.header_icon.setPixmap(
            qta.icon("fa5s.user-check", color=t["primary"]).pixmap(19, 19)
        )
        self.close_btn.setIcon(qta.icon("fa5s.times", color=t["text_muted"]))
        self.refresh_btn.setIcon(qta.icon("fa5s.sync-alt", color=t["text_muted"]))
        self.empty_icon.setPixmap(
            qta.icon("fa5s.check-circle", color=t["success"]).pixmap(48, 48)
        )

    # ==================================================================
    # Loading
    # ==================================================================

    def refresh(self):
        """Re-read the queue. Runs off the UI thread — it touches the database."""
        if self._busy:
            return

        self._set_busy(True, "Loading...")

        run_async(
            registration_service.list_pending,
            on_success=self._on_loaded,
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _on_loaded(self, pending: list[User]):
        self._pending = pending
        self._clear_banner()

        self.table.setRowCount(0)

        for user in pending:
            row = self.table.rowCount()
            self.table.insertRow(row)

            for column, text in enumerate(
                (
                    user.display_name,
                    user.username,
                    user.phone or "—",
                    user.email,
                    _ago(user.registered_at),
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)

        count = len(pending)
        self.count_pill.setText("1 waiting" if count == 1 else f"{count} waiting")
        self.pages.setCurrentIndex(PAGE_LIST if count else PAGE_EMPTY)

        if count:
            self.table.selectRow(0)

        self._update_actions()

    # ==================================================================
    # Decisions
    # ==================================================================

    def _selected_user(self) -> User | None:
        row = self.table.currentRow()

        if not self._pending or row < 0 or row >= len(self._pending):
            return None

        return self._pending[row]

    def _update_actions(self):
        has_selection = self._selected_user() is not None and not self._busy

        for widget in (self.approve_btn, self.reject_btn, self.role_combo, self.role_label):
            widget.setEnabled(has_selection)

    def _approve_selected(self):
        user = self._selected_user()

        if user is None or self._busy:
            return

        role = self.role_combo.currentData()
        self._set_busy(True, "Approving...")

        run_async(
            registration_service.approve,
            user.id,
            role=role,
            on_success=lambda approved: self._on_decided(approved, "approved"),
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _reject_selected(self):
        user = self._selected_user()

        if user is None or self._busy:
            return

        reason, confirmed = QInputDialog.getText(
            self,
            "Reject this sign-up",
            f"Why is {user.display_name} being turned down?\n"
            "This is texted to them, so keep it short and civil.",
            QLineEdit.EchoMode.Normal,
            "",
        )

        if not confirmed:
            return

        self._set_busy(True, "Rejecting...")

        run_async(
            registration_service.reject,
            user.id,
            reason=reason,
            on_success=lambda rejected: self._on_decided(rejected, "rejected"),
            on_error=self._on_service_error,
            on_finished=lambda: self._set_busy(False),
        )

    def _on_decided(self, user: User, verb: str):
        self.queue_changed.emit()
        self._show_success(f"{user.display_name} was {verb}.")

        # Re-read rather than dropping the row locally: somebody at another
        # till may have dealt with one of the others in the meantime.
        run_async(
            registration_service.list_pending,
            on_success=self._on_loaded_keeping_banner,
            on_error=self._on_service_error,
        )

    def _on_loaded_keeping_banner(self, pending: list[User]):
        message = self.banner_text.text()
        style = self.banner.objectName()

        self._on_loaded(pending)

        if message and style == "banner_success":
            self._show_success(message)

    # ==================================================================
    # Busy state and messages
    # ==================================================================

    def _set_busy(self, busy: bool, label: str = ""):
        self._busy = busy

        self.refresh_btn.setEnabled(not busy)
        self.table.setEnabled(not busy)

        if busy:
            self.approve_btn.setText(label or "Working...")
            self.approve_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            self.approve_btn.setText("Approve")
            self._update_actions()
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

    def _clear_banner(self):
        self.banner.setVisible(False)
        self.banner_text.clear()

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
            else QApplication.primaryScreen().availableGeometry()
        )

        geometry = self.frameGeometry()
        geometry.moveCenter(area.center())
        self.move(geometry.topLeft())

    def mousePressEvent(self, event):
        # Frameless, so the card itself has to be draggable. The table handles
        # its own clicks, so dragging only starts outside it.
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
        if event.key() == Qt.Key.Key_Escape and self._busy:
            return
        super().keyPressEvent(event)


def _ago(moment) -> str:
    """``2 hours ago`` — how long a sign-up has been kept waiting."""
    if moment is None:
        return "—"

    seconds = int((utcnow() - moment).total_seconds())

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"
