"""
SmartPOS — sign-in screen.

Integration contract for the rest of the app:

    window = LoginWindow()
    window.login_attempted.connect(on_login)      # (username, password, remember)

    def on_login(username, password, remember):
        window.set_busy(True)                     # while authenticating
        ...
        window.show_error("Invalid username or password.")   # on failure
        window.set_busy(False)

The window never authenticates on its own: it validates that the fields are
filled, then hands the credentials over and waits.
"""

from __future__ import annotations

import sys

import qtawesome as qta
from PySide6.QtCore import (
    QDate,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTime,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "SmartPOS"
APP_VERSION = "1.0.0"
TERMINAL_ID = "01"


# ============================================================
# DESIGN TOKENS
# ============================================================
# Semantic names (surface / text_muted / danger) instead of raw hex at the
# call site, so a colour only ever has to change in one place and both themes
# stay structurally identical.

LIGHT = {
    "app_bg": "#EDF1F7",
    "surface": "#FFFFFF",
    "field_bg": "#F7F9FC",
    "border": "#E3E8F0",
    "border_strong": "#C9D3E0",
    "text": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#64748B",
    "primary": "#1473EA",
    "primary_hover": "#1065CF",
    "primary_active": "#0B54AD",
    "primary_soft": "#E6F0FD",
    "link": "#1364CE",
    "danger": "#C81E1E",
    "danger_soft": "#FDECEC",
    "danger_border": "#F5C2C2",
    "warning": "#9A5B06",
    "warning_soft": "#FDF3E3",
    "chrome_hover": "#E2E8F0",
    "disabled_bg": "#C9D3E0",
    "disabled_text": "#4E5E76",
    "brand_from": "#062B5B",
    "brand_to": "#0C4B93",
    "brand_chip": "#12457F",
    "brand_icon": "#A8CBF4",
    "brand_text": "#FFFFFF",
    "brand_text_muted": "#BFD5EE",
    "brand_divider": "#1B4E88",
    "shadow": (15, 23, 42, 46),
}

DARK = {
    "app_bg": "#070D18",
    "surface": "#121B2C",
    "field_bg": "#0D1524",
    "border": "#26324A",
    "border_strong": "#38475F",
    "text": "#EEF2F8",
    "text_secondary": "#A8B8CD",
    "text_muted": "#7C8FA9",
    "primary": "#3B82F6",
    "primary_hover": "#5896F8",
    "primary_active": "#2A6CDC",
    "primary_soft": "#152744",
    "link": "#8FBEFC",
    "danger": "#F87171",
    "danger_soft": "#2A1620",
    "danger_border": "#5B2731",
    "warning": "#FBBF24",
    "warning_soft": "#2A2113",
    "chrome_hover": "#1E293B",
    "disabled_bg": "#253148",
    "disabled_text": "#95A7BF",
    "brand_from": "#04101F",
    "brand_to": "#0A2E5A",
    "brand_chip": "#123256",
    "brand_icon": "#8FB6EC",
    "brand_text": "#F1F6FC",
    "brand_text_muted": "#A9C0DC",
    "brand_divider": "#153A66",
    "shadow": (0, 0, 0, 130),
}


def caps_lock_on() -> bool:
    """Best-effort Caps Lock probe. Qt exposes no cross-platform API for it."""
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.WinDLL("user32").GetKeyState(0x14) & 1)
        except Exception:
            return False
    return False


# ============================================================
# COMPONENTS
# ============================================================


class DragBar(QFrame):
    """Header strip that moves the frameless window, like a native title bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            self._offset = (
                event.globalPosition().toPoint() - window.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        window = self.window()
        if self._offset is not None and not window.isFullScreen():
            window.move(event.globalPosition().toPoint() - self._offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()
        super().mouseDoubleClickEvent(event)


class LinkLabel(QLabel):
    """Text link that is reachable by mouse and by keyboard."""

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class ThemedCheckBox(QCheckBox):
    """Checkbox painted by hand so the tick mark can follow the active theme.

    Qt stylesheets can only supply a tick through `image: url(...)`, which would
    mean shipping a PNG per theme; painting keeps it vector-crisp and recolourable.
    """

    BOX = 20
    GAP = 11

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._tokens = LIGHT

    def apply_theme(self, tokens):
        self._tokens = tokens
        self.update()

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(hint.width() + self.GAP, max(hint.height(), self.BOX + 8))

    def paintEvent(self, event):
        tokens = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box = QRectF(1, (self.height() - self.BOX) / 2, self.BOX, self.BOX)

        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["primary"]))
            painter.drawRoundedRect(box, 6, 6)

            tick = QPen(QColor("#FFFFFF"), 2.1)
            tick.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(tick)
            path = QPainterPath()
            path.moveTo(box.left() + 5.2, box.top() + 10.4)
            path.lineTo(box.left() + 8.4, box.top() + 13.6)
            path.lineTo(box.left() + 14.9, box.top() + 6.6)
            painter.drawPath(path)
        else:
            painter.setBrush(QColor(tokens["field_bg"]))
            edge = tokens["primary"] if self.underMouse() else tokens["border_strong"]
            painter.setPen(QPen(QColor(edge), 1.4))
            painter.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 6, 6)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens["primary"]), 1.3))
            painter.drawRoundedRect(box.adjusted(-3.5, -3.5, 3.5, 3.5), 9, 9)

        painter.setPen(QColor(tokens["text_secondary"]))
        painter.setFont(self.font())
        text_area = QRectF(
            self.BOX + self.GAP,
            0,
            self.width() - self.BOX - self.GAP,
            self.height(),
        )
        painter.drawText(
            text_area,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )


class FeatureRow(QWidget):
    """Icon chip + label pair used on the brand panel."""

    def __init__(self, icon_name, title, subtitle, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name

        self.chip = QLabel()
        self.chip.setObjectName("feature_chip")
        self.chip.setFixedSize(40, 40)
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel(title)
        title_label.setObjectName("feature_title")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("feature_subtitle")

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        text_column.addWidget(title_label)
        text_column.addWidget(subtitle_label)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.chip)
        row.addLayout(text_column)
        row.addStretch()

    def apply_theme(self, tokens):
        self.chip.setPixmap(
            qta.icon(self._icon_name, color=tokens["brand_icon"]).pixmap(18, 18)
        )


# ============================================================
# LOGIN WINDOW
# ============================================================


class LoginWindow(QWidget):
    #: Emitted once both fields are filled in. (username, password, remember)
    login_attempted = Signal(str, str, bool)

    #: Below this width the brand panel is dropped so the form keeps breathing room.
    BRAND_BREAKPOINT = 1040

    def __init__(self, parent=None):
        super().__init__(parent)

        self._settings = QSettings(APP_NAME, APP_NAME)
        self._dark_mode = self._settings.value("ui/dark_mode", False, type=bool)
        self._busy = False
        self._caps_visible = None
        self._reveal_anim = None

        self.setWindowTitle(f"{APP_NAME} — Sign in")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(900, 640)

        self._build_ui()
        self._wire_events()
        self._apply_theme()
        self._restore_preferences()

        self.showFullScreen()

    # ---------------------------------------------------------
    # Construction
    # ---------------------------------------------------------

    def _build_ui(self):
        self.brand_panel = self._build_brand_panel()
        self.form_panel = self._build_form_panel()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.brand_panel, 47)
        root.addWidget(self.form_panel, 53)

    def _build_brand_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("brand_panel")

        self.logo_chip = QLabel()
        self.logo_chip.setObjectName("logo_chip")
        self.logo_chip.setFixedSize(54, 54)
        self.logo_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)

        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("wordmark")

        overline = QLabel("BUSINESS MANAGEMENT SYSTEM")
        overline.setObjectName("overline")

        wordmark_column = QVBoxLayout()
        wordmark_column.setContentsMargins(0, 0, 0, 0)
        wordmark_column.setSpacing(2)
        wordmark_column.addWidget(wordmark)
        wordmark_column.addWidget(overline)

        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 0, 0, 0)
        logo_row.setSpacing(16)
        logo_row.addWidget(self.logo_chip)
        logo_row.addLayout(wordmark_column)
        logo_row.addStretch()

        headline = QLabel("Sell smarter.\nStock better.\nGrow faster.")
        headline.setObjectName("headline")

        description = QLabel(
            "Sales, inventory, customers and reporting —\n"
            "one system for the whole counter."
        )
        description.setObjectName("description")

        self.feature_rows = [
            FeatureRow("fa5s.shopping-cart", "Point of Sale", "Fast, keyboard-first checkout"),
            FeatureRow("fa5s.cubes", "Inventory", "Live stock levels and alerts"),
            FeatureRow("fa5s.chart-line", "Reports", "Daily takings at a glance"),
            FeatureRow("fa5s.book", "Ledger", "Customer and supplier balances"),
        ]

        features = QVBoxLayout()
        features.setContentsMargins(0, 0, 0, 0)
        features.setSpacing(18)
        for row in self.feature_rows:
            features.addWidget(row)

        divider = QFrame()
        divider.setObjectName("brand_divider")
        divider.setFixedHeight(1)

        self.trust_icon = QLabel()
        self.trust_icon.setFixedSize(16, 16)
        self.trust_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        trust_text = QLabel("TRUSTED BY BUSINESSES EVERYWHERE")
        trust_text.setObjectName("trust_text")

        trust_row = QHBoxLayout()
        trust_row.setContentsMargins(0, 0, 0, 0)
        trust_row.setSpacing(10)
        trust_row.addWidget(self.trust_icon)
        trust_row.addWidget(trust_text)
        trust_row.addStretch()

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(64, 52, 64, 44)
        layout.setSpacing(0)
        layout.addLayout(logo_row)
        layout.addStretch(2)
        layout.addWidget(headline)
        layout.addSpacing(20)
        layout.addWidget(description)
        layout.addSpacing(44)
        layout.addLayout(features)
        layout.addStretch(3)
        layout.addWidget(divider)
        layout.addSpacing(20)
        layout.addLayout(trust_row)

        return panel

    def _build_form_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("form_panel")

        titlebar = self._build_titlebar()

        self.card = self._build_card()

        footer = QLabel(
            f"{APP_NAME} v{APP_VERSION}   ·   Terminal {TERMINAL_ID}"
        )
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(titlebar)
        layout.addStretch(1)
        layout.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addWidget(footer)
        layout.addSpacing(28)

        return panel

    def _build_titlebar(self) -> DragBar:
        bar = DragBar()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(76)

        self.time_label = QLabel()
        self.time_label.setObjectName("time_label")

        self.date_label = QLabel()
        self.date_label.setObjectName("date_label")

        clock_column = QVBoxLayout()
        clock_column.setContentsMargins(0, 0, 0, 0)
        clock_column.setSpacing(1)
        clock_column.addWidget(self.time_label)
        clock_column.addWidget(self.date_label)

        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("chrome_btn")
        self.minimize_btn = QPushButton()
        self.minimize_btn.setObjectName("chrome_btn")
        self.close_btn = QPushButton()
        self.close_btn.setObjectName("chrome_close")

        for button, tip in (
            (self.theme_btn, "Toggle dark mode"),
            (self.minimize_btn, "Minimise"),
            (self.close_btn, "Close SmartPOS"),
        ):
            button.setFixedSize(44, 44)
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(40, 16, 28, 8)
        layout.setSpacing(8)
        layout.addLayout(clock_column)
        layout.addStretch()
        layout.addWidget(self.theme_btn)
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.close_btn)

        return bar

    def _build_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(452)

        self.card_mark = QLabel()
        self.card_mark.setObjectName("card_mark")
        self.card_mark.setFixedSize(52, 52)
        self.card_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        heading = QLabel("Welcome back")
        heading.setObjectName("heading")

        subheading = QLabel("Sign in to open your register.")
        subheading.setObjectName("subheading")

        username_label = QLabel("Username")
        username_label.setObjectName("field_label")

        self.username = QLineEdit()
        self.username.setPlaceholderText("Enter your username")
        self.username.setAccessibleName("Username")
        self.user_icon_action = self.username.addAction(
            qta.icon("fa5s.user"), QLineEdit.ActionPosition.LeadingPosition
        )

        password_label = QLabel("Password")
        password_label.setObjectName("field_label")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Enter your password")
        self.password.setAccessibleName("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.lock_icon_action = self.password.addAction(
            qta.icon("fa5s.lock"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.eye_action = self.password.addAction(
            qta.icon("fa5s.eye"), QLineEdit.ActionPosition.TrailingPosition
        )
        self.eye_action.setToolTip("Show password")

        for field in (self.username, self.password):
            field.setMinimumHeight(50)

        self.caps_row = QFrame()
        self.caps_row.setObjectName("caps_row")
        self.caps_icon = QLabel()
        self.caps_icon.setFixedSize(14, 14)
        caps_text = QLabel("Caps Lock is on")
        caps_text.setObjectName("caps_text")
        caps_layout = QHBoxLayout(self.caps_row)
        caps_layout.setContentsMargins(2, 0, 0, 0)
        caps_layout.setSpacing(8)
        caps_layout.addWidget(self.caps_icon)
        caps_layout.addWidget(caps_text)
        caps_layout.addStretch()
        self.caps_row.setVisible(False)

        self.remember = ThemedCheckBox("Remember me")
        self.remember.setAccessibleName("Remember me")

        self.forgot = LinkLabel("Forgot password?")
        self.forgot.setObjectName("forgot")
        self.forgot.setAccessibleName("Forgot password")

        options = QHBoxLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.addWidget(self.remember)
        options.addStretch()
        options.addWidget(self.forgot)

        self.error_banner = QFrame()
        self.error_banner.setObjectName("error_banner")
        self.error_icon = QLabel()
        self.error_icon.setFixedSize(16, 16)
        self.error_text = QLabel()
        self.error_text.setObjectName("error_text")
        self.error_text.setWordWrap(True)
        # QLabel leaves heightForWidth off its size policy, so a layout measures
        # wrapped text by a heuristic and clips longer messages. Opt in explicitly.
        for widget in (self.error_text, self.error_banner):
            policy = widget.sizePolicy()
            policy.setHeightForWidth(True)
            policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
            widget.setSizePolicy(policy)
        error_layout = QHBoxLayout(self.error_banner)
        error_layout.setContentsMargins(14, 11, 14, 11)
        error_layout.setSpacing(10)
        error_layout.addWidget(self.error_icon, 0, Qt.AlignmentFlag.AlignTop)
        error_layout.addWidget(self.error_text, 1)
        self.error_banner.setVisible(False)

        self.login_btn = QPushButton("Sign in")
        self.login_btn.setObjectName("login_btn")
        self.login_btn.setMinimumHeight(52)
        self.login_btn.setIconSize(QSize(15, 15))
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setDefault(True)
        # Qt draws a button's icon before its text; mirroring puts the arrow after
        # "Sign in", where it reads as forward motion rather than a bullet.
        self.login_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(44, 40, 44, 40)
        layout.setSpacing(0)
        layout.addWidget(self.card_mark)
        layout.addSpacing(22)
        layout.addWidget(heading)
        layout.addSpacing(6)
        layout.addWidget(subheading)
        layout.addSpacing(30)
        layout.addWidget(username_label)
        layout.addSpacing(8)
        layout.addWidget(self.username)
        layout.addSpacing(18)
        layout.addWidget(password_label)
        layout.addSpacing(8)
        layout.addWidget(self.password)
        layout.addSpacing(10)
        layout.addWidget(self.caps_row)
        layout.addSpacing(8)
        layout.addLayout(options)
        layout.addSpacing(20)
        layout.addWidget(self.error_banner)
        layout.addSpacing(14)
        layout.addWidget(self.login_btn)

        self.card_shadow = QGraphicsDropShadowEffect(self)
        self.card_shadow.setBlurRadius(56)
        self.card_shadow.setOffset(0, 18)
        card.setGraphicsEffect(self.card_shadow)

        return card

    def _wire_events(self):
        self.login_btn.clicked.connect(self.handle_login)
        self.username.returnPressed.connect(self.handle_login)
        self.password.returnPressed.connect(self.handle_login)
        self.username.textEdited.connect(self._on_typing)
        self.password.textEdited.connect(self._on_typing)

        self.eye_action.triggered.connect(self._toggle_password)
        self.forgot.clicked.connect(self.show_forgot_password_help)
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.minimize_btn.clicked.connect(self.showMinimized)
        self.close_btn.clicked.connect(self.confirm_close)

        self.setTabOrder(self.username, self.password)
        self.setTabOrder(self.password, self.remember)
        self.setTabOrder(self.remember, self.forgot)
        self.setTabOrder(self.forgot, self.login_btn)

        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._tick()

    def _restore_preferences(self):
        saved_user = self._settings.value("auth/remembered_username", "", type=str)
        if saved_user:
            self.username.setText(saved_user)
            self.remember.setChecked(True)
            self.password.setFocus()
        else:
            self.username.setFocus()

    # ---------------------------------------------------------
    # Theming
    # ---------------------------------------------------------

    @property
    def tokens(self) -> dict:
        return DARK if self._dark_mode else LIGHT

    def toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._settings.setValue("ui/dark_mode", self._dark_mode)
        self._apply_theme()

    def _apply_theme(self):
        tokens = self.tokens
        self.setStyleSheet(self._stylesheet(tokens))
        self._apply_icons(tokens)

        placeholder = QColor(tokens["text_muted"])
        for field in (self.username, self.password):
            palette = field.palette()
            palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder)
            field.setPalette(palette)

        self.card_shadow.setColor(QColor(*tokens["shadow"]))
        self.remember.apply_theme(tokens)
        for row in self.feature_rows:
            row.apply_theme(tokens)

    def _apply_icons(self, tokens):
        muted = tokens["text_muted"]

        self.logo_chip.setPixmap(
            qta.icon("fa5s.store", color=tokens["brand_text"]).pixmap(24, 24)
        )
        self.trust_icon.setPixmap(
            qta.icon("fa5s.shield-alt", color=tokens["brand_icon"]).pixmap(14, 14)
        )
        self.card_mark.setPixmap(
            qta.icon("fa5s.fingerprint", color=tokens["primary"]).pixmap(26, 26)
        )

        self.user_icon_action.setIcon(qta.icon("fa5s.user", color=muted))
        self.lock_icon_action.setIcon(qta.icon("fa5s.lock", color=muted))
        self._refresh_eye_icon()

        self.caps_icon.setPixmap(
            qta.icon("fa5s.exclamation-triangle", color=tokens["warning"]).pixmap(13, 13)
        )
        self.error_icon.setPixmap(
            qta.icon("fa5s.exclamation-circle", color=tokens["danger"]).pixmap(15, 15)
        )

        self.theme_btn.setIcon(
            qta.icon("fa5s.sun" if self._dark_mode else "fa5s.moon", color=muted)
        )
        self.theme_btn.setToolTip(
            "Switch to light mode" if self._dark_mode else "Switch to dark mode"
        )
        self.minimize_btn.setIcon(qta.icon("fa5s.minus", color=muted))
        self.close_btn.setIcon(qta.icon("fa5s.times", color=muted))

        if not self._busy:
            self.login_btn.setIcon(qta.icon("fa5s.arrow-right", color="#FFFFFF"))

    def _stylesheet(self, t) -> str:
        return f"""
        QWidget {{
            font-family: "Segoe UI", "Inter", sans-serif;
            font-size: 14px;
            color: {t['text']};
        }}
        LoginWindow {{
            background: {t['app_bg']};
        }}

        /* ---------- brand panel ---------- */
        #brand_panel {{
            background: qlineargradient(x1:0, y1:0, x2:0.9, y2:1,
                        stop:0 {t['brand_from']}, stop:1 {t['brand_to']});
        }}
        #logo_chip {{
            background: {t['brand_chip']};
            border-radius: 16px;
        }}
        #wordmark {{
            color: {t['brand_text']};
            font-size: 27px;
            font-weight: 800;
        }}
        #overline {{
            color: {t['brand_text_muted']};
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 2px;
        }}
        #headline {{
            color: {t['brand_text']};
            font-size: 40px;
            font-weight: 700;
            line-height: 130%;
        }}
        #description {{
            color: {t['brand_text_muted']};
            font-size: 15px;
            line-height: 150%;
        }}
        #feature_chip {{
            background: {t['brand_chip']};
            border-radius: 12px;
        }}
        #feature_title {{
            color: {t['brand_text']};
            font-size: 14px;
            font-weight: 600;
        }}
        #feature_subtitle {{
            color: {t['brand_text_muted']};
            font-size: 12px;
        }}
        #brand_divider {{
            background: {t['brand_divider']};
        }}
        #trust_text {{
            color: {t['brand_text_muted']};
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 1.5px;
        }}

        /* ---------- form panel ---------- */
        #form_panel, #titlebar {{
            background: {t['app_bg']};
        }}
        #time_label {{
            font-size: 19px;
            font-weight: 700;
            color: {t['text']};
        }}
        #date_label {{
            font-size: 12px;
            color: {t['text_muted']};
        }}
        #footer {{
            font-size: 11px;
            color: {t['text_muted']};
            letter-spacing: 0.4px;
        }}

        #chrome_btn, #chrome_close {{
            background: transparent;
            border: none;
            border-radius: 10px;
        }}
        #chrome_btn:hover {{
            background: {t['chrome_hover']};
        }}
        #chrome_close:hover {{
            background: {t['danger_soft']};
        }}

        /* ---------- card ---------- */
        #card {{
            background: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 22px;
        }}
        #card_mark {{
            background: {t['primary_soft']};
            border-radius: 15px;
        }}
        #heading {{
            font-size: 27px;
            font-weight: 700;
            color: {t['text']};
        }}
        #subheading {{
            font-size: 14px;
            color: {t['text_muted']};
        }}
        #field_label {{
            font-size: 12px;
            font-weight: 600;
            color: {t['text_secondary']};
        }}

        QLineEdit {{
            background: {t['field_bg']};
            border: 1px solid {t['border']};
            border-radius: 13px;
            padding: 0px 14px;
            color: {t['text']};
            selection-background-color: {t['primary']};
            selection-color: #FFFFFF;
        }}
        QLineEdit:hover {{
            border-color: {t['border_strong']};
        }}
        QLineEdit:focus {{
            background: {t['surface']};
            border: 1.6px solid {t['primary']};
        }}
        QLineEdit[hasError="true"] {{
            border: 1.6px solid {t['danger']};
            background: {t['danger_soft']};
        }}
        QLineEdit:disabled {{
            color: {t['text_muted']};
        }}
        QLineEdit QToolButton {{
            background: transparent;
            border: none;
            padding: 0px;
            margin: 0px 2px;
        }}

        #caps_row {{
            background: {t['warning_soft']};
            border-radius: 9px;
            padding: 7px 10px;
        }}
        #caps_text {{
            font-size: 12px;
            font-weight: 600;
            color: {t['warning']};
        }}

        #forgot {{
            color: {t['link']};
            font-size: 13px;
            font-weight: 600;
            background: transparent;
        }}
        #forgot:hover {{
            text-decoration: underline;
        }}
        #forgot:focus {{
            text-decoration: underline;
        }}

        #error_banner {{
            background: {t['danger_soft']};
            border: 1px solid {t['danger_border']};
            border-radius: 12px;
        }}
        #error_text {{
            color: {t['danger']};
            font-size: 13px;
            font-weight: 600;
            background: transparent;
        }}

        #login_btn {{
            background: {t['primary']};
            color: #FFFFFF;
            border: none;
            border-radius: 13px;
            font-size: 15px;
            font-weight: 700;
        }}
        #login_btn:hover {{
            background: {t['primary_hover']};
        }}
        #login_btn:pressed {{
            background: {t['primary_active']};
        }}
        #login_btn:disabled {{
            background: {t['disabled_bg']};
            color: {t['disabled_text']};
        }}

        QToolTip {{
            background: {t['text']};
            color: {t['surface']};
            border: none;
            padding: 6px 9px;
        }}

        /* Dialogs inherit this window's text colour but keep the OS dialog
           background, which goes dark-on-dark under a dark Windows theme.
           Painting both sides here keeps them readable in either theme. */
        QMessageBox {{
            background: {t['surface']};
        }}
        QMessageBox QLabel {{
            background: transparent;
            color: {t['text']};
            font-size: 14px;
        }}
        QMessageBox QPushButton {{
            background: {t['field_bg']};
            color: {t['text']};
            border: 1px solid {t['border_strong']};
            border-radius: 9px;
            padding: 8px 18px;
            min-width: 82px;
            font-weight: 600;
        }}
        QMessageBox QPushButton:hover {{
            background: {t['chrome_hover']};
            border-color: {t['primary']};
        }}
        QMessageBox QPushButton:default {{
            background: {t['primary']};
            border: 1px solid {t['primary']};
            color: #FFFFFF;
        }}
        QMessageBox QPushButton:default:hover {{
            background: {t['primary_hover']};
            border-color: {t['primary_hover']};
        }}
        """

    # ---------------------------------------------------------
    # Behaviour
    # ---------------------------------------------------------

    def _tick(self):
        now = QTime.currentTime()
        self.time_label.setText(now.toString("hh:mm AP"))
        self.date_label.setText(QDate.currentDate().toString("dddd, dd MMMM yyyy"))

        caps = caps_lock_on()
        if caps != self._caps_visible:
            self._caps_visible = caps
            self.caps_row.setVisible(caps)

    def _toggle_password(self):
        hidden = self.password.echoMode() == QLineEdit.EchoMode.Password
        self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self.eye_action.setToolTip("Hide password" if hidden else "Show password")
        self._refresh_eye_icon()

    def _refresh_eye_icon(self):
        showing = self.password.echoMode() == QLineEdit.EchoMode.Normal
        self.eye_action.setIcon(
            qta.icon(
                "fa5s.eye-slash" if showing else "fa5s.eye",
                color=self.tokens["text_muted"],
            )
        )

    def _on_typing(self, _text):
        if self.error_banner.isVisible():
            self.clear_error()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.brand_panel.setVisible(self.width() >= self.BRAND_BREAKPOINT)

    def handle_login(self):
        if self._busy:
            return

        username = self.username.text().strip()
        password = self.password.text()

        self._mark_field(self.username, not username)
        self._mark_field(self.password, not password)

        if not username or not password:
            missing = "username" if not username else "password"
            self.show_error(f"Please enter your {missing} to continue.")
            (self.username if not username else self.password).setFocus()
            return

        self.clear_error()

        if self.remember.isChecked():
            self._settings.setValue("auth/remembered_username", username)
        else:
            self._settings.remove("auth/remembered_username")

        self.login_attempted.emit(username, password, self.remember.isChecked())

    # ---------------------------------------------------------
    # Public API for the authentication layer
    # ---------------------------------------------------------

    def set_busy(self, busy: bool):
        """Lock the form while credentials are being checked."""
        self._busy = busy

        for widget in (self.username, self.password, self.remember, self.login_btn):
            widget.setEnabled(not busy)

        if busy:
            self.login_btn.setText("Signing in…")
            self.login_btn.setIcon(
                qta.icon(
                    "fa5s.circle-notch",
                    color=self.tokens["disabled_text"],
                    animation=qta.Spin(self.login_btn),
                )
            )
        else:
            self.login_btn.setText("Sign in")
            self.login_btn.setIcon(qta.icon("fa5s.arrow-right", color="#FFFFFF"))

    def show_error(self, message: str):
        """Show a failure message under the form and reveal it with a slide."""
        self.error_text.setText(message)
        animate = not self.error_banner.isVisible()

        self.error_text.setMinimumHeight(0)
        self.error_banner.setMaximumHeight(16777215)
        self.error_banner.setVisible(True)

        # First pass gives the label a real width; only then can the wrapped
        # height be measured, and a second pass grows the banner to fit it.
        self.card.layout().activate()
        self._fit_wrapped_label(self.error_text)
        self.card.layout().activate()

        if animate:
            self._reveal(self.error_banner, self.error_banner.height())

        self.password.selectAll()

    def clear_error(self):
        self.error_banner.setVisible(False)
        self.error_text.clear()
        self.error_text.setMinimumHeight(0)
        self._mark_field(self.username, False)
        self._mark_field(self.password, False)

    def reset(self):
        """Return the form to a clean state, e.g. after signing out."""
        self.clear_error()
        self.password.clear()
        self.set_busy(False)
        if self.username.text():
            self.password.setFocus()
        else:
            self.username.setFocus()

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def _mark_field(self, field: QLineEdit, has_error: bool):
        if field.property("hasError") == has_error:
            return
        field.setProperty("hasError", has_error)
        field.style().unpolish(field)
        field.style().polish(field)

    def _fit_wrapped_label(self, label: QLabel):
        """Pin a word-wrapped label to the height its text actually needs."""
        width = label.width()
        if width <= 1:
            return
        needed = label.fontMetrics().boundingRect(
            QRect(0, 0, width, 0),
            int(Qt.TextFlag.TextWordWrap),
            label.text(),
        ).height()
        label.setMinimumHeight(needed)

    def _reveal(self, widget: QWidget, target: int):
        widget.setMaximumHeight(0)

        anim = QPropertyAnimation(widget, b"maximumHeight", self)
        anim.setDuration(190)
        anim.setStartValue(0)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._reveal_anim = anim

    def show_forgot_password_help(self):
        QMessageBox.information(
            self,
            "Forgot password",
            "Passwords are reset by an administrator.\n\n"
            "Ask a manager to sign in and reset your password from "
            "Settings → Users, then sign in again.",
        )

    def confirm_close(self):
        answer = QMessageBox.question(
            self,
            f"Close {APP_NAME}",
            f"Close {APP_NAME} on this terminal?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoginWindow()

    def demo_auth(username, password, remember):
        window.set_busy(True)

        def finish():
            window.set_busy(False)
            if (username, password) != ("admin", "admin"):
                window.show_error("Invalid username or password. Please try again.")

        QTimer.singleShot(900, finish)

    window.login_attempted.connect(demo_auth)
    sys.exit(app.exec())
