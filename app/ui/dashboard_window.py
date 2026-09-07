from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QGridLayout,
    QApplication,
    QMessageBox
)

from PySide6.QtCore import Qt

import qtawesome as qta
import sys



class MenuButton(QPushButton):

    def __init__(self, icon, text):

        super().__init__(text)

        self.setObjectName(
            "menu_button"
        )

        self.setIcon(
            qta.icon(
                icon,
                color="#CBD5E1"
            )
        )



class KPI_Card(QFrame):

    def __init__(self, title, value, icon):

        super().__init__()

        self.setObjectName(
            "kpi_card"
        )


        layout = QVBoxLayout()


        icon_label = QLabel()

        icon_label.setPixmap(
            qta.icon(
                icon,
                color="#2563EB"
            ).pixmap(
                28,
                28
            )
        )


        title_label = QLabel(
            title
        )

        title_label.setObjectName(
            "card_title"
        )


        value_label = QLabel(
            value
        )

        value_label.setObjectName(
            "card_value"
        )


        layout.addWidget(icon_label)
        layout.addWidget(title_label)
        layout.addWidget(value_label)


        self.setLayout(layout)




class DashboardWindow(QWidget):

    def __init__(
        self,
        username="Nadee",
        role="Owner"
    ):

        super().__init__()


        self.username = username
        self.role = role

        self.dark_mode = False


        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )


        self.showFullScreen()


        self.apply_theme()


        self.create_ui()



    def create_ui(self):


        main = QVBoxLayout()

        main.setContentsMargins(
            0,
            0,
            0,
            0
        )


        # =====================
        # TOP BAR
        # =====================

        top = QFrame()

        top.setObjectName(
            "topbar"
        )


        top_layout = QHBoxLayout()


        logo = QLabel(
            "SmartPOS"
        )

        logo.setObjectName(
            "top_logo"
        )


        theme_btn = QPushButton(
            "☾"
        )

        theme_btn.setObjectName(
            "theme_btn"
        )

        theme_btn.clicked.connect(
            self.toggle_theme
        )


        user = QLabel(
            f"{self.username} | {self.role}"
        )

        user.setObjectName(
            "user"
        )


        exit_btn = QPushButton(
            "✕"
        )

        exit_btn.setObjectName(
            "exit"
        )

        exit_btn.clicked.connect(
            self.close_app
        )


        top_layout.addWidget(
            logo
        )

        top_layout.addStretch()

        top_layout.addWidget(
            theme_btn
        )

        top_layout.addWidget(
            user
        )

        top_layout.addWidget(
            exit_btn
        )


        top.setLayout(
            top_layout
        )



        # =====================
        # BODY
        # =====================


        body = QHBoxLayout()


        # Sidebar

        sidebar = QFrame()

        sidebar.setObjectName(
            "sidebar"
        )


        side_layout = QVBoxLayout()


        side_layout.setContentsMargins(
            20,
            30,
            20,
            20
        )


        menu_items = [

            ("fa5s.home","Dashboard"),

            ("fa5s.cash-register","POS"),

            ("fa5s.box","Products"),

            ("fa5s.warehouse","Inventory"),

            ("fa5s.users","Customers"),

            ("fa5s.truck","Suppliers"),

            ("fa5s.book","Ledger"),

            ("fa5s.money-bill","Expenses"),

            ("fa5s.chart-line","Reports"),

            ("fa5s.cog","Settings"),

        ]


        for icon,text in menu_items:

            side_layout.addWidget(
                MenuButton(
                    icon,
                    text
                )
            )


        side_layout.addStretch()


        logout = MenuButton(
            "fa5s.sign-out-alt",
            "Logout"
        )


        side_layout.addWidget(
            logout
        )


        sidebar.setLayout(
            side_layout
        )



        # Main Content


        content = QFrame()


        content_layout = QVBoxLayout()


        welcome = QLabel(
            f"Good Morning, {self.username} 👋"
        )

        welcome.setObjectName(
            "welcome"
        )


        subtitle = QLabel(
            f"{self.role} Dashboard"
        )

        subtitle.setObjectName(
            "subtitle"
        )



        cards = QGridLayout()


        items = [

            (
                "Today's Sales",
                "SAR 20,000",
                "fa5s.shopping-cart"
            ),

            (
                "Net Profit",
                "SAR 6,000",
                "fa5s.chart-line"
            ),

            (
                "Receivables",
                "SAR 15,000",
                "fa5s.book"
            ),

            (
                "Payables",
                "SAR 8,000",
                "fa5s.money-bill"
            )

        ]


        for i,item in enumerate(items):

            cards.addWidget(
                KPI_Card(
                    item[0],
                    item[1],
                    item[2]
                ),
                0,
                i
            )



        health = QFrame()

        health.setObjectName(
            "panel"
        )


        health_layout = QVBoxLayout()


        health_layout.addWidget(
            QLabel(
                "Business Health"
            )
        )


        health_layout.addWidget(
            QLabel(
                "✓ Business is currently profitable\n"
                "✓ Expenses are under control\n"
                "⚠ Customer receivables need attention"
            )
        )


        health.setLayout(
            health_layout
        )



        activity = QFrame()

        activity.setObjectName(
            "panel"
        )


        activity_layout = QVBoxLayout()


        activity_layout.addWidget(
            QLabel(
                "Recent Activity"
            )
        )


        activity_layout.addWidget(
            QLabel(
                "No activity yet"
            )
        )


        activity.setLayout(
            activity_layout
        )



        content_layout.addWidget(
            welcome
        )

        content_layout.addWidget(
            subtitle
        )

        content_layout.addSpacing(
            30
        )

        content_layout.addLayout(
            cards
        )

        content_layout.addSpacing(
            25
        )

        content_layout.addWidget(
            health
        )

        content_layout.addSpacing(
            20
        )

        content_layout.addWidget(
            activity
        )


        content.setLayout(
            content_layout
        )



        body.addWidget(
            sidebar
        )

        body.addWidget(
            content
        )


        main.addWidget(
            top
        )

        main.addLayout(
            body
        )


        self.setLayout(
            main
        )



    def toggle_theme(self):

        self.dark_mode = not self.dark_mode

        self.apply_theme()



    def apply_theme(self):

        if self.dark_mode:

            bg = "#111827"
            card = "#1F2937"
            text = "#F8FAFC"


        else:

            bg = "#DCDCDD"
            card = "#FEFEFE"
            text = "#0F172A"



        self.setStyleSheet(
            f"""

            QWidget {{

                background:{bg};

                color:{text};

                font-family:Segoe UI;

            }}


            #topbar {{

                background:#062B5B;

            }}


            #top_logo {{

                color:white;

                font-size:24px;

                font-weight:bold;

            }}


            #sidebar {{

                background:#062B5B;

                min-width:230px;

            }}


            #menu_button {{

                background:transparent;

                color:#CBD5E1;

                padding:12px;

                border-radius:10px;

                text-align:left;

            }}


            #menu_button:hover {{

                background:#0B3A73;

            }}


            #kpi_card {{

                background:{card};

                border-radius:18px;

                padding:25px;

            }}


            #card_title {{

                color:#64748B;

            }}


            #card_value {{

                font-size:28px;

                font-weight:bold;

            }}


            #welcome {{

                font-size:32px;

                font-weight:bold;

            }}


            #subtitle {{

                color:#64748B;

            }}


            #panel {{

                background:{card};

                border-radius:18px;

                padding:20px;

            }}


            #exit {{

                background:#DC2626;

                color:white;

                border-radius:8px;

                width:40px;

                height:35px;

            }}


            """

        )



    def close_app(self):

        result = QMessageBox.question(
            self,
            "Exit",
            "Close SmartPOS?"
        )


        if result == QMessageBox.StandardButton.Yes:

            QApplication.quit()




if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = DashboardWindow()

    window.show()

    sys.exit(
        app.exec()
    )