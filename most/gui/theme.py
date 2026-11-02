"""Светлая и тёмная тема по настройке Windows."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

ICON_FONT = "Segoe MDL2 Assets"  # значки Windows 10/11

# значки из Segoe MDL2 Assets
I_ATTACH = "\ue723"
I_SEND = "\ue724"
I_QR = "\ued14"
I_FOLDER = "\ued25"
I_PHONE = "\ue8ea"
I_SOUND = "\ue767"
I_MUTE = "\ue74f"
I_CLEAR = "\ue74d"
I_HEART = "\ueb51"

LIGHT = {
    "bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#eceef2", "border": "#dfe2e8",
    "text": "#1b1d22", "muted": "#6b7280", "accent": "#2f6fed", "accent_text": "#ffffff",
    "out": "#dce8ff", "out_border": "#c4d6fb", "ok": "#1f9d55", "bad": "#d64545",
    "hover": "#e4e7ec", "track": "#d9dde5",
}
DARK = {
    "bg": "#16181d", "surface": "#22252c", "surface2": "#2a2e36", "border": "#30343d",
    "text": "#e8eaed", "muted": "#9aa0ab", "accent": "#5b8dff", "accent_text": "#ffffff",
    "out": "#253a63", "out_border": "#2f4a7d", "ok": "#3ccf7e", "bad": "#ff6b6b",
    "hover": "#323742", "track": "#3a3f4a",
}


def is_dark() -> bool:
    forced = os.environ.get("MOST_THEME")
    if forced in ("dark", "light"):
        return forced == "dark"
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme != Qt.ColorScheme.Unknown:
        return scheme == Qt.ColorScheme.Dark
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


def colors() -> dict[str, str]:
    return DARK if is_dark() else LIGHT


def apply(app) -> dict[str, str]:
    c = colors()
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "surface"),
                      (QPalette.AlternateBase, "surface2"), (QPalette.Text, "text"),
                      (QPalette.WindowText, "text"), (QPalette.Button, "surface"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "accent_text"), (QPalette.ToolTipBase, "surface"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted"),
                      (QPalette.Link, "accent")):
        pal.setColor(role, QColor(c[key]))
    app.setPalette(pal)
    app.setStyleSheet(STYLE.format(icon=ICON_FONT, **c))
    return c


STYLE = """
QWidget {{ color: {text}; font-family: "Segoe UI"; font-size: 10pt; }}
QMainWindow, #root {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }}

#header {{ background: {surface}; border-bottom: 1px solid {border}; }}
#avatar {{ background: {accent}; color: {accent_text}; border-radius: 20px;
          font-family: "{icon}"; font-size: 15pt; }}
#title {{ font-size: 12pt; font-weight: 600; }}
#status {{ color: {muted}; font-size: 9pt; }}
#status[online="true"] {{ color: {ok}; }}

QPushButton#iconBtn {{ font-family: "{icon}"; font-size: 13pt; border: none; border-radius: 8px;
                       background: transparent; min-width: 36px; min-height: 36px; }}
QPushButton#iconBtn:hover {{ background: {hover}; }}
QPushButton#iconBtn:pressed {{ background: {surface2}; }}
QPushButton#sendBtn {{ font-family: "{icon}"; font-size: 12pt; border: none; border-radius: 18px;
                       background: {accent}; color: {accent_text}; min-width: 36px; min-height: 36px; }}
QPushButton#sendBtn:hover {{ background: {accent}; border: 2px solid {out_border}; }}
QPushButton#textBtn {{ border: 1px solid {border}; border-radius: 8px; background: {surface};
                       padding: 6px 12px; min-height: 22px; }}
QPushButton#textBtn:hover {{ background: {hover}; }}

QScrollArea {{ border: none; background: {bg}; }}
#feed {{ background: {bg}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {track}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

#bubbleIn {{ background: {surface}; border: 1px solid {border}; border-radius: 14px; }}
#bubbleOut {{ background: {out}; border: 1px solid {out_border}; border-radius: 14px; }}
#meta {{ color: {muted}; font-size: 8.5pt; }}
#body {{ font-size: 10.5pt; }}
#fileName {{ font-weight: 600; }}
#fileInfo {{ color: {muted}; font-size: 9pt; }}
#fileInfo[state="ok"] {{ color: {ok}; }}
#fileInfo[state="bad"] {{ color: {bad}; }}
#dateSep {{ color: {muted}; font-size: 9pt; background: {surface2}; border-radius: 10px;
            padding: 2px 10px; }}
#empty {{ color: {muted}; font-size: 10.5pt; }}

QPushButton#action {{ border: none; border-radius: 6px; background: transparent; color: {accent};
                      padding: 3px 8px; font-size: 9pt; }}
QPushButton#action:hover {{ background: {hover}; }}
QPushButton#action:disabled {{ color: {muted}; }}

QProgressBar {{ background: {track}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}

#composer {{ background: {surface}; border-top: 1px solid {border}; }}
QPlainTextEdit#input {{ background: {surface2}; border: 1px solid {border}; border-radius: 10px;
                        padding: 6px 8px; selection-background-color: {accent}; }}
QPlainTextEdit#input:focus {{ border: 1px solid {accent}; }}
#toast {{ color: {muted}; font-size: 9pt; }}
#toast[state="bad"] {{ color: {bad}; }}
#dropHint {{ background: rgba(47, 111, 237, 0.12); border: 2px dashed {accent}; border-radius: 16px;
             color: {accent}; font-size: 13pt; font-weight: 600; }}

QDialog {{ background: {surface}; }}
#qrBox {{ background: #ffffff; border-radius: 12px; }}
#pin {{ font-size: 26pt; font-weight: 600; letter-spacing: 6px; }}
#hint {{ color: {muted}; font-size: 9pt; }}
#netWarn {{ color: {bad}; font-size: 9pt; }}
QComboBox {{ border: 1px solid {border}; border-radius: 6px; padding: 4px 8px; background: {surface2}; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; }}
"""
