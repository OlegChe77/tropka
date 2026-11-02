"""Лента сообщений: пузыри с текстом, файлами и ходом передачи."""
from __future__ import annotations

import html
import os
import re
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileIconProvider, QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

BUBBLE_WIDTH = 440
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
_URL = re.compile(r"(https?://[^\s<]+)")


def human_size(n: int | None) -> str:
    if n is None:
        return ""
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def day_label(d: date) -> str:
    today = date.today()
    if d == today:
        return "Сегодня"
    if (today - d).days == 1:
        return "Вчера"
    text = f"{d.day} {MONTHS[d.month - 1]}"
    return text if d.year == today.year else f"{text} {d.year}"


def open_file(path: str) -> None:
    os.startfile(path)  # noqa: S606 — открыть программой по умолчанию


def show_in_folder(path: str) -> None:
    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')


def _action(text: str, slot) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("action")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class Bubble(QFrame):
    """Пузырь сообщения. outgoing — отправлено с ПК (справа)."""

    def __init__(self, outgoing: bool, sender: str, ts: float) -> None:
        super().__init__()
        self.setObjectName("bubbleOut" if outgoing else "bubbleIn")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(12, 8, 12, 6)
        self.box.setSpacing(4)
        meta = QLabel(f"{sender} · {datetime.fromtimestamp(ts):%H:%M}")
        meta.setObjectName("meta")
        self.box.addWidget(meta)

    def fit(self, width: int) -> None:
        """Ширина пузыря зависит от ширины окна."""
        self.setMaximumWidth(width)

    def actions(self, *buttons: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        for b in buttons:
            row.addWidget(b)
        row.addStretch(1)
        self.box.addLayout(row)
        return row


class TextBubble(Bubble):
    def __init__(self, outgoing: bool, sender: str, ts: float, text: str) -> None:
        super().__init__(outgoing, sender, ts)
        self.text = text
        body = QLabel(_URL.sub(r'<a href="\1">\1</a>', html.escape(text)).replace("\n", "<br>"))
        body.setObjectName("body")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        body.setOpenExternalLinks(True)
        self.body = body
        self.box.addWidget(body)
        self.copy_btn = _action("Копировать", self.copy)
        self.actions(self.copy_btn)

    def fit(self, width: int) -> None:
        super().fit(width)
        # иначе QLabel с переносом сжимается до узкой колонки;
        # шрифт из стилей известен только после ensurePolished()
        self.body.ensurePolished()
        fm = self.body.fontMetrics()
        natural = max(fm.horizontalAdvance(line) for line in self.text.splitlines() or [""])
        self.body.setMinimumWidth(min(natural + 4, width - 26))

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.copy_btn.setText("Скопировано")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("Копировать"))


class FileBubble(Bubble):
    """Файл: идёт передача (полоса) → готов (Открыть / Показать в папке) или ошибка."""

    def __init__(self, outgoing: bool, sender: str, ts: float, name: str,
                 size: int | None, path: str | None = None) -> None:
        super().__init__(outgoing, sender, ts)
        self.outgoing = outgoing
        self.size = size
        self.path = path
        row = QHBoxLayout()
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(32, 32)
        row.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = QLabel()
        self.name.setObjectName("fileName")
        self.name.setWordWrap(True)
        self.info = QLabel()
        self.info.setObjectName("fileInfo")
        col.addWidget(self.name)
        col.addWidget(self.info)
        row.addLayout(col, 1)
        self.box.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.box.addWidget(self.bar)
        self.open_btn = _action("Открыть", lambda: open_file(self.path))
        self.folder_btn = _action("Показать в папке", lambda: show_in_folder(self.path))
        self.actions(self.open_btn, self.folder_btn)
        self.name.setText(name)
        self.set_done(path, delivered=None)

    def fit(self, width: int) -> None:
        super().fit(width)
        self.setMinimumWidth(min(260, width))

    def set_name(self, name: str) -> None:
        self.name.setText(name)

    def _set_icon(self) -> None:
        info = QFileInfo(self.path or self.name.text())
        icon = QFileIconProvider().icon(info)
        self.icon.setPixmap(icon.pixmap(QSize(32, 32)))

    def _set_info(self, text: str, state: str = "") -> None:
        self.info.setText(text)
        self.info.setProperty("state", state)
        self.info.style().unpolish(self.info)
        self.info.style().polish(self.info)

    def set_progress(self, done: int, total: int) -> None:
        self.bar.show()
        self.bar.setValue(int(done * 1000 / total) if total else 0)
        self._set_info(f"{human_size(done)} из {human_size(total)}")
        self.open_btn.hide()
        self.folder_btn.hide()

    def set_done(self, path: str | None, delivered: bool | None = None,
                 device: str | None = None) -> None:
        self.path = path
        self.bar.hide()
        exists = bool(path) and Path(path).is_file()
        self.open_btn.setVisible(exists)
        self.folder_btn.setVisible(exists)
        self._set_icon()
        size = human_size(self.size)
        if not exists and path:
            self._set_info(f"{size} · файла больше нет", "bad")
        elif self.outgoing and device:
            self._set_info(f"{size} · ✓ скачал {device}", "ok")
        elif self.outgoing and delivered:
            self._set_info(f"{size} · ✓ скачано", "ok")
        elif self.outgoing:
            self._set_info(f"{size} · ждёт, пока телефон скачает")
        else:
            self._set_info(size)

    def set_failed(self, reason: str) -> None:
        self.bar.hide()
        self.open_btn.hide()
        self.folder_btn.hide()
        self._set_info(f"Не принят: {reason}", "bad")


class FeedView(QScrollArea):
    """Прокручиваемая лента; новые сообщения внизу."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().rangeChanged.connect(self._on_range)
        self.clear()

    def clear(self) -> None:
        """Пустая лента. При очистке старый виджет со всеми пузырями удаляет Qt."""
        inner = QWidget()
        inner.setObjectName("feed")
        self.box = QVBoxLayout(inner)
        self.box.setContentsMargins(16, 12, 16, 12)
        self.box.setSpacing(8)
        self.box.addStretch(1)
        self.empty = QLabel("Здесь появятся файлы и сообщения.\n"
                            "Нажмите QR вверху и наведите камеру телефона.")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.box.addWidget(self.empty)
        self.box.addStretch(1)
        self.setWidget(inner)
        self._last_day: date | None = None
        self.transfers: dict[str, FileBubble] = {}  # передачи с телефона по id
        self.items: dict[int, Bubble] = {}          # сообщения по id в истории
        self._stick = True
        self.bubbles: list[Bubble] = []

    def _bubble_width(self) -> int:
        return min(BUBBLE_WIDTH, int(self.viewport().width() * 0.8))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        width = self._bubble_width()
        for b in self.bubbles:
            b.fit(width)

    def _on_range(self, _min: int, maximum: int) -> None:
        if self._stick:
            self.verticalScrollBar().setValue(maximum)

    def add(self, bubble: Bubble, outgoing: bool, ts: float | None = None,
            item: int | None = None) -> Bubble:
        bar = self.verticalScrollBar()
        self._stick = outgoing or bar.value() >= bar.maximum() - 40
        if not self.empty.isHidden():
            self.empty.hide()
            self.box.takeAt(self.box.count() - 1)  # нижний отступ пустой ленты
        day = datetime.fromtimestamp(ts or time.time()).date()
        if day != self._last_day:
            self._last_day = day
            sep = QLabel(day_label(day))
            sep.setObjectName("dateSep")
            self.box.addWidget(sep, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if outgoing:
            row.addStretch(1)
        row.addWidget(bubble)
        if not outgoing:
            row.addStretch(1)
        self.box.addLayout(row)
        bubble.fit(self._bubble_width())
        self.bubbles.append(bubble)
        if item is not None:
            self.items[item] = bubble
        return bubble

    # --- из истории и событий ---

    def add_row(self, r: dict, pc_name: str) -> None:
        out = r["direction"] == "out"
        sender = pc_name if out else (r["device"] or "Телефон")
        if r["kind"] == "text":
            self.add(TextBubble(out, sender, r["ts"], r["text"] or ""), out, r["ts"], r["id"])
        else:
            b = FileBubble(out, sender, r["ts"], r["name"] or "файл", r["size"], r["path"])
            b.set_done(r["path"], delivered=bool(r.get("delivered")))
            self.add(b, out, r["ts"], r["id"])
