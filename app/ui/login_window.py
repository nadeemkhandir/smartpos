from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QApplication
)

from PySide6.QtCore import (
    Qt,
    QTimer,
    QTime,
    QDate
)

from PySide6.QtGui import (
    QPainter,
    QPen,
    QColor
)

import qtawesome as qta

import sys



# ==========================
# THEME COLORS
# ==========================

LIGHT_THEME = {

    "background": "#F8FAFC",
    "card": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
    "primary": "#1473EA",
    "border": "#CBD5E1"

}


DARK_THEME = {

    "background": "#111827",
    "card": "#1F2937",
    "text": "#F9FAFB",
    "muted": "#CBD5E1",
    "primary": "#3B82F6",
    "border": "#374151"

}



# ==========================
# ANALOG CLOCK
# ==========================

class AnalogClock(QWidget):

    def __init__(self):

        super().__init__()

        self.setFixedSize(
            170,
            170
        )


        self.timer = QTimer(
            self
        )

        self.timer.timeout.connect(
            self.update
        )

        self.timer.start(
            1000
        )



    def paintEvent(self, event):

        painter = QPainter(
            self
        )


        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )


        center = self.rect().center()


        radius = 70



        # Clock circle

        # clock outer ring
        painter.setPen(
            QPen(
                QColor("#2563EB"),
                4
            )
        )

        painter.drawEllipse(
            center,
            radius,
            radius
        )

        # clock ticks
        painter.setPen(
            QPen(
                QColor("#64748B"),
                2
            )
        )

        import math

        for i in range(12):
            angle = math.radians(i * 30 - 90)
            x1 = center.x() + int((radius - 10) * math.cos(angle))
            y1 = center.y() + int((radius - 10) * math.sin(angle))
            x2 = center.x() + int(radius * math.cos(angle))
            y2 = center.y() + int(radius * math.sin(angle))
            painter.drawLine(x1, y1, x2, y2)



        self.dark_mode = getattr(self.parent(), "dark_mode", False)
        current = QTime.currentTime()


        hour = current.hour() % 12

        minute = current.minute()

        second = current.second()



        # Hour hand

        painter.setPen(
            QPen(
                QColor("#FE16C1" if getattr(self, "dark_mode", False) else "#2969FF"),
                5
            )
        )


        hour_angle = (
            (hour + minute / 60) * 30
        )


        self.draw_hand(
            painter,
            center,
            radius * 0.45,
            hour_angle
        )



        # Minute hand

        painter.setPen(
            QPen(
                QColor("#60A5FA"),
                3
            )
        )


        minute_angle = (
            minute * 6
        )


        self.draw_hand(
            painter,
            center,
            radius * 0.65,
            minute_angle
        )



        # Second hand

        painter.setPen(
            QPen(
                QColor("#DC2626"),
                2
            )
        )


        second_angle = (
            second * 6
        )


        self.draw_hand(
            painter,
            center,
            radius * 0.75,
            second_angle
        )



        painter.setBrush(
            QColor("#2563EB")
        )


        painter.drawEllipse(
            center,
            5,
            5
        )



    def draw_hand(
        self,
        painter,
        center,
        length,
        angle
    ):

        import math


        rad = math.radians(
            angle - 90
        )


        x = (
            center.x()
            +
            length * math.cos(rad)
        )


        y = (
            center.y()
            +
            length * math.sin(rad)
        )


        painter.drawLine(
            center.x(),
            center.y(),
            int(x),
            int(y)
        )



# ==========================
# FEATURE CARD
# ==========================


class FeatureCard(QFrame):

    def __init__(
        self,
        title,
        subtitle,
        icon
    ):

        super().__init__()


        self.setObjectName(
            "feature_card"
        )


        layout = QVBoxLayout()


        layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )


        icon_label = QLabel()


        icon_label.setPixmap(
            qta.icon(
                icon,
                color="#D6E4F0"
            ).pixmap(
                32,
                32
            )
        )


        icon_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )



        title_label = QLabel(
            title
        )


        title_label.setObjectName(
            "feature_title"
        )


        title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )



        subtitle_label = QLabel(
            subtitle
        )


        subtitle_label.setObjectName(
            "feature_subtitle"
        )


        subtitle_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )



        layout.addWidget(
            icon_label
        )


        layout.addWidget(
            title_label
        )


        layout.addWidget(
            subtitle_label
        )


        self.setLayout(
            layout
        )



# ==========================
# LOGIN WINDOW
# ==========================


class LoginWindow(QWidget):

    def __init__(self):

        super().__init__()


        self.dark_mode = False


        self.setWindowTitle(
            "SmartPOS Login"
        )


        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )


        self.setStyleSheet(
            self.styles()
        )

        self.create_ui()

        self.showFullScreen()

    def create_ui(self):

        main = QHBoxLayout()

        main.setContentsMargins(
            0,
            0,
            0,
            0
        )


        # ==========================
        # LEFT BRAND PANEL
        # ==========================


        left = QFrame()

        left.setObjectName(
            "left_panel"
        )


        left_layout = QVBoxLayout()

        left_layout.setContentsMargins(
            60,
            50,
            60,
            40
        )


        logo = QLabel(
            "SmartPOS"
        )

        logo.setObjectName(
            "logo"
        )


        brand = QLabel(
            "BUSINESS MANAGEMENT SYSTEM"
        )

        brand.setObjectName(
            "brand"
        )


        headline = QLabel(
            "Simple.\nSmart.\nFor Your Business."
        )

        headline.setObjectName(
            "headline"
        )


        description = QLabel(
            "Manage sales, inventory, customers\n"
            "and grow your business — all in one place."
        )

        description.setObjectName(
            "description"
        )


        cards_layout = QHBoxLayout()

        cards_layout.setSpacing(
            12
        )


        features = [

            FeatureCard(
                "Point of Sale",
                "Fast & Easy",
                "fa5s.shopping-cart"
            ),

            FeatureCard(
                "Inventory",
                "Real-time Stock",
                "fa5s.cubes"
            ),

            FeatureCard(
                "Reports",
                "Insightful Data",
                "fa5s.chart-line"
            ),

            FeatureCard(
                "Ledger",
                "Customers & Suppliers",
                "fa5s.book"
            )

        ]


        for item in features:

            cards_layout.addWidget(
                item
            )


        trusted = QLabel(
            "TRUSTED BY BUSINESSES EVERYWHERE"
        )

        trusted.setObjectName(
            "trusted"
        )


        left_layout.addWidget(
            logo
        )

        left_layout.addWidget(
            brand
        )

        left_layout.addStretch()

        left_layout.addWidget(
            headline
        )

        left_layout.addWidget(
            description
        )

        left_layout.addSpacing(
            40
        )

        left_layout.addLayout(
            cards_layout
        )

        left_layout.addStretch()

        left_layout.addWidget(
            trusted
        )


        left.setLayout(
            left_layout
        )



        # ==========================
        # RIGHT PANEL
        # ==========================


        right = QFrame()

        right.setObjectName(
            "right_panel"
        )


        right_layout = QVBoxLayout()

        right_layout.setContentsMargins(
            70,
            30,
            70,
            30
        )



        # Top controls

        top = QHBoxLayout()


        date_box = QVBoxLayout()


        self.date_label = QLabel()

        self.date_label.setObjectName(
            "date_label"
        )


        date_box.addWidget(
            self.date_label
        )


        top.addLayout(
            date_box
        )


        top.addStretch()



        theme_btn = QPushButton(
            "🌙"
        )

        theme_btn.setObjectName(
            "theme_btn"
        )


        theme_btn.clicked.connect(
            self.toggle_theme
        )


        top.addWidget(
            theme_btn
        )


        close_btn = QPushButton(
            "X"
        )

        close_btn.setObjectName(
            "close_btn"
        )

        close_btn.setToolTip(
            "Close"
        )

        close_btn.clicked.connect(
            self.close
        )


        top.addWidget(
            close_btn
        )


        right_layout.addLayout(
            top
        )


        # Clock section


        clock_layout = QVBoxLayout()


        self.clock = AnalogClock()


        self.clock_time = QLabel()


        self.clock_time.setObjectName(
            "clock_time"
        )


        self.update_datetime()


        clock_layout.addWidget(
            self.clock,
            alignment=Qt.AlignmentFlag.AlignCenter
        )


        clock_layout.addWidget(
            self.clock_time,
            alignment=Qt.AlignmentFlag.AlignCenter
        )


        right_layout.addLayout(
            clock_layout
        )



        # Update timer

        self.date_timer = QTimer(
            self
        )

        self.date_timer.timeout.connect(
            self.update_datetime
        )

        self.date_timer.start(
            1000
        )



        # Login card


        card = QFrame()

        card.setObjectName(
            "login_card"
        )


        card_layout = QVBoxLayout()


        card_layout.setContentsMargins(
            45,
            35,
            45,
            35
        )



        welcome = QLabel(
            "Welcome Back"
        )

        welcome.setObjectName(
            "welcome"
        )


        subtitle = QLabel(
            "Please sign in to your account"
        )

        subtitle.setObjectName(
            "subtitle"
        )



        self.username = QLineEdit()

        self.username.setPlaceholderText(
            "Username"
        )



        self.password = QLineEdit()

        self.password.setPlaceholderText(
            "Password"
        )


        self.password.setEchoMode(
            QLineEdit.EchoMode.Password
        )


        show_password = QPushButton()

        show_password.setIcon(
            qta.icon(
                "fa5s.eye",
                color="#64748B"
            )
        )


        show_password.clicked.connect(
            self.toggle_password
        )


        password_row = QHBoxLayout()


        password_row.addWidget(
            self.password
        )


        password_row.addWidget(
            show_password
        )



        options = QHBoxLayout()


        remember = QCheckBox(
            "Remember me"
        )


        forgot = QLabel(
            "Forgot password?"
        )

        forgot.setObjectName(
            "forgot"
        )


        options.addWidget(
            remember
        )


        options.addStretch()


        options.addWidget(
            forgot
        )



        login = QPushButton(
            "Login"
        )


        login.setObjectName(
            "login"
        )



        card_layout.addWidget(
            welcome
        )


        card_layout.addWidget(
            subtitle
        )


        card_layout.addSpacing(
            20
        )


        card_layout.addWidget(
            self.username
        )


        card_layout.addLayout(
            password_row
        )


        card_layout.addLayout(
            options
        )


        card_layout.addSpacing(
            20
        )


        card_layout.addWidget(
            login
        )


        card.setLayout(
            card_layout
        )



        right_layout.addWidget(
            card
        )


        right.setLayout(
            right_layout
        )



        main.addWidget(
            left,
            1
        )


        main.addWidget(
            right,
            1
        )


        self.setLayout(
            main
        )



    def update_datetime(self):

        today = QDate.currentDate()

        now = QTime.currentTime()


        self.date_label.setText(
            today.toString(
                "dddd, dd MMMM yyyy"
            )
        )


        self.clock_time.setText(
            now.toString(
                "hh:mm:ss AP"
            )
        )



    def toggle_password(self):

        if self.password.echoMode() == QLineEdit.EchoMode.Password:

            self.password.setEchoMode(
                QLineEdit.EchoMode.Normal
            )

        else:

            self.password.setEchoMode(
                QLineEdit.EchoMode.Password
            )



    def toggle_theme(self):

        self.dark_mode = not self.dark_mode

        self.setStyleSheet(
            self.styles()
        )



    def styles(self):

        if self.dark_mode:

            bg = "#111827"
            card = "#1F2937"
            text = "#F9FAFB"

        else:

            bg = "#F8FAFC"
            card = "#FFFFFF"
            text = "#0F172A"



        return f"""

        QWidget {{

            font-family: Segoe UI;

            color:{text};

        }}


        #left_panel {{

            background:#062B5B;

        }}


        #right_panel {{

            background:{bg};

        }}


        #logo {{

            color:white;

            font-size:40px;

            font-weight:800;

        }}


        #brand {{

            color:#CBD5E1;

            letter-spacing:3px;

            font-size:12px;

        }}


        #headline {{

            color:white;

            font-size:42px;

            font-weight:bold;

        }}


        #description {{

            color:#D6E4F0;

            font-size:17px;

        }}


        #feature_card {{

            background:#0B3A73;

            border-radius:15px;

            padding:15px;

        }}


        #feature_title {{

            color:white;

            font-weight:bold;

        }}


        #feature_subtitle {{

            color:#CBD5E1;

        }}


        #login_card {{

            background:{card};

            border-radius:20px;

        }}


        #welcome {{

            font-size:32px;

            font-weight:bold;

        }}


        #subtitle {{

            color:#64748B;

        }}


        QLineEdit {{

            height:45px;

            border:1px solid #CBD5E1;

            border-radius:10px;

            padding-left:12px;

            background:{card};

            color:{text};

        }}


        QPushButton {{

            border-radius:8px;

        }}


        #login {{

            height:50px;

            background:#1473EA;

            color:white;

            font-size:16px;

            font-weight:bold;

        }}


        #theme_btn {{

            background:#2563EB;

            color:white;

            width:40px;

            height:35px;

        }}


        #close_btn {{

            background:#DC2626;

            color:white;

            width:40px;

            height:35px;

            font-size:18px;

            font-weight:bold;

        }}


        #date_label {{

            font-size:16px;

            color:{text};

        }}


        #clock_time {{

            font-size:20px;

            font-weight:bold;

            color:#2563EB;

        }}


        #forgot {{

            color:#2563EB;

        }}

        """




if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = LoginWindow()

    window.show()

    sys.exit(
        app.exec()
    )