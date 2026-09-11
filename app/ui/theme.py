"""
Design tokens shared by every SmartPOS screen.

Semantic names (``surface`` / ``text_muted`` / ``danger``) instead of raw hex at
the call site, so a colour only ever has to change in one place and both themes
stay structurally identical. The sign-in window, the reset dialog and the
password dialog all read from here, which is what keeps them looking like one
application.
"""

from __future__ import annotations

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
    "success": "#0F7B3F",
    "success_soft": "#E7F6ED",
    "success_border": "#B7E2C6",
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
    "success": "#4ADE80",
    "success_soft": "#10241A",
    "success_border": "#1F4D33",
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


def tokens_for(dark_mode: bool) -> dict:
    return DARK if dark_mode else LIGHT


def dialog_stylesheet(t: dict) -> str:
    """Shared look for the modal dialogs that sit on top of the sign-in screen.

    Kept as one string rather than per-widget styling so a dialog only has to
    set object names and gets the whole theme for free.
    """
    return f"""
        QDialog {{
            background: {t["surface"]};
        }}

        QLabel {{
            color: {t["text"]};
            background: transparent;
        }}

        QLabel#dialog_title {{
            font-size: 21px;
            font-weight: 700;
            color: {t["text"]};
        }}

        QLabel#dialog_subtitle {{
            font-size: 13px;
            color: {t["text_secondary"]};
        }}

        QLabel#field_label {{
            font-size: 12px;
            font-weight: 600;
            color: {t["text_secondary"]};
        }}

        QLabel#hint {{
            font-size: 12px;
            color: {t["text_muted"]};
        }}

        QLabel#step_pill {{
            font-size: 11px;
            font-weight: 700;
            color: {t["primary"]};
            background: {t["primary_soft"]};
            border-radius: 9px;
            padding: 4px 10px;
        }}

        QLineEdit {{
            background: {t["field_bg"]};
            border: 1px solid {t["border"]};
            border-radius: 9px;
            padding: 10px 12px;
            font-size: 14px;
            color: {t["text"]};
            selection-background-color: {t["primary"]};
            selection-color: #FFFFFF;
        }}

        QLineEdit:hover {{
            border-color: {t["border_strong"]};
        }}

        QLineEdit:focus {{
            border: 2px solid {t["primary"]};
            padding: 9px 11px;
            background: {t["surface"]};
        }}

        QLineEdit:disabled {{
            color: {t["disabled_text"]};
            background: {t["field_bg"]};
        }}

        QLineEdit[hasError="true"] {{
            border: 2px solid {t["danger"]};
            padding: 9px 11px;
        }}

        QPushButton#primary {{
            background: {t["primary"]};
            color: #FFFFFF;
            border: none;
            border-radius: 9px;
            padding: 11px 20px;
            font-size: 14px;
            font-weight: 600;
        }}

        QPushButton#primary:hover  {{ background: {t["primary_hover"]}; }}
        QPushButton#primary:pressed {{ background: {t["primary_active"]}; }}
        QPushButton#primary:disabled {{
            background: {t["disabled_bg"]};
            color: {t["disabled_text"]};
        }}

        QPushButton#ghost {{
            background: transparent;
            color: {t["text_secondary"]};
            border: 1px solid {t["border"]};
            border-radius: 9px;
            padding: 11px 18px;
            font-size: 14px;
            font-weight: 600;
        }}

        QPushButton#ghost:hover {{
            background: {t["chrome_hover"]};
            color: {t["text"]};
        }}

        QPushButton#ghost:disabled {{
            color: {t["disabled_text"]};
            border-color: {t["border"]};
        }}

        QPushButton#link {{
            background: transparent;
            border: none;
            color: {t["link"]};
            font-size: 13px;
            font-weight: 600;
            padding: 4px 2px;
            text-align: left;
        }}

        QPushButton#link:hover {{ text-decoration: underline; }}
        QPushButton#link:disabled {{ color: {t["text_muted"]}; }}

        QFrame#banner_error {{
            background: {t["danger_soft"]};
            border: 1px solid {t["danger_border"]};
            border-radius: 9px;
        }}

        QFrame#banner_success {{
            background: {t["success_soft"]};
            border: 1px solid {t["success_border"]};
            border-radius: 9px;
        }}

        QFrame#banner_info {{
            background: {t["warning_soft"]};
            border: 1px solid {t["warning"]};
            border-radius: 9px;
        }}

        QLabel#banner_error_text   {{ color: {t["danger"]};  font-size: 13px; }}
        QLabel#banner_success_text {{ color: {t["success"]}; font-size: 13px; }}
        QLabel#banner_info_text    {{ color: {t["warning"]}; font-size: 13px; }}

        QFrame#separator {{
            background: {t["border"]};
            max-height: 1px;
            border: none;
        }}

        QProgressBar {{
            background: {t["field_bg"]};
            border: none;
            border-radius: 3px;
            max-height: 6px;
            text-align: center;
        }}

        QProgressBar::chunk {{
            border-radius: 3px;
        }}
    """
