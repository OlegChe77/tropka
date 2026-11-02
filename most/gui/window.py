"""Окно «Лента»: шапка с телефоном и QR, лента сообщений, поле отправки."""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import qrcode
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .. import firewall
from ..config import DONATE_URL
from ..service import BridgeService
from ..sounds import Sounds
from . import theme
from .feed import FeedView, FileBubble, TextBubble


class EventRelay(QObject):
    """Переносит события шины из потока сервера в поток окна."""

    event = Signal(str, object)

    def __call__(self, kind: str, data: dict) -> None:
        self.event.emit(kind, data)


def _icon_button(glyph: str, tip: str, name: str = "iconBtn") -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName(name)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def qr_pixmap(text: str, size: int = 248) -> QPixmap:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    scale = max(1, size // n)
    pm = QPixmap(n * scale, n * scale)
    pm.fill(Qt.white)
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(x * scale, y * scale, scale, scale)
    p.end()
    return pm


def net_problem(status: firewall.Status) -> str:
    """Что мешает телефону подключиться — простыми словами."""
    parts = []
    if status.rule in ("missing", "block"):
        parts.append("Брандмауэр Windows не пускает телефон к «Тропке».")
    for n in status.public:
        parts.append(f"Сеть «{n['name']}» отмечена как общедоступная — "
                     "в ней Windows прячет компьютер от других устройств.")
    return " ".join(parts)


class QrDialog(QDialog):
    """QR и PIN для входа с телефона."""

    fix_requested = Signal()

    def __init__(self, service: BridgeService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Подключить телефон")
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(10)
        title = QLabel("Наведите камеру телефона на QR-код")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        box.addWidget(title)
        self.qr = QLabel()
        self.qr.setObjectName("qrBox")
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setFixedSize(272, 272)
        box.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.ip = QComboBox()
        self.ip.addItems(service.ips)
        self.ip.setVisible(len(service.ips) > 1)
        self.ip.setToolTip("Адрес компьютера в сети, к которой подключён телефон")
        self.ip.currentIndexChanged.connect(self.refresh)
        box.addWidget(self.ip)
        self.url = QLabel()
        self.url.setObjectName("hint")
        self.url.setAlignment(Qt.AlignCenter)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.url)
        cap = QLabel("PIN для входа вручную")
        cap.setObjectName("hint")
        cap.setAlignment(Qt.AlignCenter)
        box.addWidget(cap)
        self.pin = QLabel()
        self.pin.setObjectName("pin")
        self.pin.setAlignment(Qt.AlignCenter)
        self.pin.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.pin)
        hint = QLabel("Телефон и компьютер должны быть в одной сети Wi-Fi. "
                      "При первом входе браузер предупредит о сертификате — это нормально: "
                      "«Дополнительно» → «Перейти на сайт».")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        box.addWidget(hint)
        self.net_warn = QLabel()
        self.net_warn.setObjectName("netWarn")
        self.net_warn.setWordWrap(True)
        self.net_warn.setAlignment(Qt.AlignCenter)
        self.net_fix = QPushButton("Разрешить доступ телефону")
        self.net_fix.setObjectName("textBtn")
        self.net_fix.setToolTip("Windows попросит подтверждение администратора")
        self.net_fix.clicked.connect(self.fix_requested.emit)
        box.addWidget(self.net_warn)
        box.addWidget(self.net_fix, 0, Qt.AlignHCenter)
        self.set_net(None)
        row = QHBoxLayout()
        new_pin = QPushButton("Новый PIN")
        new_pin.setObjectName("textBtn")
        new_pin.setToolTip("Старый QR и PIN перестанут работать; вошедшие телефоны останутся")
        new_pin.clicked.connect(self.new_pin)
        done = QPushButton("Готово")
        done.setObjectName("textBtn")
        done.clicked.connect(self.accept)
        row.addWidget(new_pin)
        row.addStretch(1)
        row.addWidget(done)
        box.addLayout(row)
        self.setFixedWidth(360)
        self.refresh()

    def refresh(self) -> None:
        bridge = self.service.bridge
        ip = self.ip.currentText() or self.service.ips[0]
        self.qr.setPixmap(qr_pixmap(bridge.pair_url(ip)))
        self.url.setText(bridge.url(ip))
        pin = bridge.pin
        self.pin.setText(f"{pin[:3]} {pin[3:]}")

    def new_pin(self) -> None:
        self.service.bridge.regenerate_pin()
        self.refresh()

    def set_net(self, status: firewall.Status | None) -> None:
        bad = status is not None and not status.ok
        self.net_warn.setText(net_problem(status) if bad else "")
        self.net_warn.setVisible(bad)
        self.net_fix.setVisible(bad)
        self.adjustSize()


class InputEdit(QPlainTextEdit):
    """Поле ввода: Enter — отправить, Shift+Enter — новая строка; растёт до 5 строк."""

    submit = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("input")
        self.setPlaceholderText("Текст или перетащите файлы")
        self.setTabChangesFocus(True)
        self.setAcceptDrops(False)  # файлы ловит окно целиком
        self.textChanged.connect(self._fit)
        self._fit()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.submit.emit()
            return
        super().keyPressEvent(e)

    def _fit(self) -> None:
        lines = int(self.document().size().height())
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if lines > 5 else Qt.ScrollBarAlwaysOff)
        h = self.fontMetrics().lineSpacing() * max(1, min(5, lines)) + 22
        self.setFixedHeight(h)


class MainWindow(QMainWindow):
    show_requested = Signal()   # из трея и второго экземпляра программы
    qr_requested = Signal()
    quit_requested = Signal()
    net_checked = Signal(object, bool)  # firewall.Status, после ли исправления

    def __init__(self, service: BridgeService) -> None:
        super().__init__()
        self.service = service
        self.bridge = service.bridge
        self.tray = None  # ставит gui.run()
        self.online: dict[int, str] = {}
        self._offline_at: dict[int, float] = {}  # короткий обрыв связи — без звука
        self.sounds = Sounds(service.data_dir)
        self._quitting = False
        self._hint_shown = False
        self._qr: QrDialog | None = None
        self._qr_skip: set[int] = set()
        self.net: firewall.Status | None = None
        self._net_busy = False
        self.setWindowTitle("Тропка")
        self.resize(520, 720)
        self.setMinimumSize(380, 480)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("root")
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._header())
        self.feed = FeedView()
        col.addWidget(self.feed, 1)
        col.addWidget(self._composer())
        self.setCentralWidget(root)
        self.drop_hint = QLabel("Отпустите, чтобы отправить на телефон", root)
        self.drop_hint.setObjectName("dropHint")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.hide()

        self.relay = EventRelay()
        self.relay.event.connect(self.on_event)
        service.events.subscribe(self.relay)
        self.show_requested.connect(self.bring_up)
        self.qr_requested.connect(self.show_qr)
        self.quit_requested.connect(self.quit_app)
        self.net_checked.connect(self.on_net_checked)
        for r in service.store.history():
            self.feed.add_row(r, self.bridge.pc_name)
        self._update_header()

    # --- части окна ---

    def _header(self) -> QWidget:
        w = QFrame()
        w.setObjectName("header")
        row = QHBoxLayout(w)
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(10)
        avatar = QLabel(theme.I_PHONE)
        avatar.setObjectName("avatar")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignCenter)
        row.addWidget(avatar)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.status = QLabel()
        self.status.setObjectName("status")
        col.addWidget(self.title)
        col.addWidget(self.status)
        row.addLayout(col, 1)
        folder = _icon_button(theme.I_FOLDER, "Открыть папку с принятыми файлами")
        folder.clicked.connect(self.open_downloads)
        qr = _icon_button(theme.I_QR, "Подключить телефон: QR-код и PIN")
        qr.clicked.connect(self.show_qr)
        self.sound_btn = _icon_button("", "")
        self.sound_btn.clicked.connect(self.toggle_sound)
        self._show_sound()
        clear = _icon_button(theme.I_CLEAR, "Очистить ленту")
        clear.clicked.connect(self.clear_feed)
        donate = _icon_button(theme.I_HEART, "Помощь проекту")
        donate.clicked.connect(lambda: webbrowser.open(DONATE_URL))
        row.addWidget(donate)
        row.addWidget(self.sound_btn)
        row.addWidget(clear)
        row.addWidget(folder)
        row.addWidget(qr)
        return w

    def toggle_sound(self) -> None:
        self.sounds.set_enabled(not self.sounds.enabled)
        self._show_sound()
        self.sounds.play("text")

    def _show_sound(self) -> None:
        on = self.sounds.enabled
        self.sound_btn.setText(theme.I_SOUND if on else theme.I_MUTE)
        self.sound_btn.setToolTip("Звук включён — выключить" if on else "Звук выключен — включить")

    def _composer(self) -> QWidget:
        w = QFrame()
        w.setObjectName("composer")
        col = QVBoxLayout(w)
        col.setContentsMargins(10, 6, 10, 10)
        col.setSpacing(4)
        self.toast = QLabel()
        self.toast.setObjectName("toast")
        self.toast.hide()
        col.addWidget(self.toast)
        row = QHBoxLayout()
        row.setSpacing(6)
        attach = _icon_button(theme.I_ATTACH, "Выбрать файлы")
        attach.clicked.connect(self.pick_files)
        self.input = InputEdit()
        self.input.submit.connect(self.send_text)
        clip = QPushButton("Буфер")
        clip.setObjectName("textBtn")
        clip.setToolTip("Отправить то, что скопировано на компьютере: текст, картинку или файлы")
        clip.setCursor(Qt.PointingHandCursor)
        clip.clicked.connect(self.send_clipboard)
        send = _icon_button(theme.I_SEND, "Отправить (Enter)", "sendBtn")
        send.clicked.connect(self.send_text)
        row.addWidget(attach, 0, Qt.AlignBottom)
        row.addWidget(self.input, 1)
        row.addWidget(clip, 0, Qt.AlignBottom)
        row.addWidget(send, 0, Qt.AlignBottom)
        col.addLayout(row)
        return w

    def _update_header(self) -> None:
        names = list(dict.fromkeys(self.online.values()))
        self.title.setText(", ".join(names) if names else "Телефон")
        online = bool(names)
        self.status.setText("на связи" if online else "не подключён — нажмите QR, чтобы подключить")
        self.status.setProperty("online", "true" if online else "false")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def say(self, text: str, bad: bool = False) -> None:
        self.toast.setText(text)
        self.toast.setProperty("state", "bad" if bad else "")
        self.toast.style().unpolish(self.toast)
        self.toast.style().polish(self.toast)
        self.toast.show()
        QTimer.singleShot(4000, lambda: self.toast.text() == text and self.toast.hide())

    def clear_feed(self) -> None:
        ask = QMessageBox(QMessageBox.Question, "Тропка",
                          "Очистить ленту?\n\nОна очистится у всех: здесь и на телефонах. "
                          "Файлы останутся в папках.", parent=self)
        yes = ask.addButton("Очистить", QMessageBox.AcceptRole)
        ask.addButton("Отмена", QMessageBox.RejectRole)
        ask.exec()
        if ask.clickedButton() is yes:
            self.bridge.clear_feed()  # ленту очистит событие feed_cleared

    # --- отправка ---

    def send_files(self, paths: list[str]) -> None:
        skipped = 0
        for p in paths:
            if Path(p).is_dir():
                skipped += 1
                continue
            try:
                self.bridge.offer_file(p)
            except OSError as e:
                self.say(f"Не удалось отправить: {e}", bad=True)
        if skipped:
            self.say("Папки пока не поддерживаются — перетащите файлы", bad=True)

    def send_text(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.bridge.offer_text(text)
        self.input.clear()

    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Отправить на телефон")
        if files:
            self.send_files(files)

    def send_clipboard(self) -> None:
        mime = QGuiApplication.clipboard().mimeData()
        files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []
        if files:
            self.send_files(files)
        elif mime.hasImage():
            folder = self.service.data_dir / "Буфер"
            folder.mkdir(exist_ok=True)
            path = folder / f"Снимок {datetime.now():%Y-%m-%d %H-%M-%S}.png"
            QGuiApplication.clipboard().image().save(str(path), "PNG")
            self.send_files([str(path)])
        elif mime.hasText() and mime.text().strip():
            self.bridge.offer_text(mime.text())
        else:
            self.say("В буфере обмена ничего нет")

    # --- перетаскивание файлов ---

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self.drop_hint.setGeometry(self.feed.geometry().adjusted(12, 12, -12, -12))
            self.drop_hint.raise_()
            self.drop_hint.show()

    def dragLeaveEvent(self, e) -> None:
        self.drop_hint.hide()

    def dropEvent(self, e) -> None:
        self.drop_hint.hide()
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            e.acceptProposedAction()
            self.send_files(files)

    # --- события сервера (уже в потоке окна) ---

    def on_event(self, kind: str, d: dict) -> None:
        feed = self.feed
        pc = self.bridge.pc_name
        if (kind in ("device_joined", "device_online") and d["id"] not in self._qr_skip
                and self._qr and self._qr.isVisible()):
            self._qr.accept()  # подключился новый телефон — QR больше не нужен
        if kind == "device_joined":
            self.say(f"Подключился телефон: {d['name']}")
        elif kind == "feed_cleared":
            feed.clear()
            if d["device"]:
                self.say(f"Ленту очистили с телефона {d['device']}")
        elif kind == "device_online":
            if time.monotonic() - self._offline_at.get(d["id"], -1e9) > 30:
                self.sounds.play("online")
            self.online[d["id"]] = d["name"]
            self._update_header()
        elif kind == "device_offline":
            self.online.pop(d["id"], None)
            self._offline_at[d["id"]] = time.monotonic()
            self._update_header()
        elif kind == "upload_started":
            b = FileBubble(False, d["device"], datetime.now().timestamp(), d["name"], d["size"])
            b.set_progress(0, d["size"])
            feed.transfers[d["id"]] = b
            feed.add(b, False)
        elif kind == "upload_progress":
            if b := feed.transfers.get(d["id"]):
                b.set_progress(d["done"], d["total"])
        elif kind == "upload_failed":
            if b := feed.transfers.pop(d["id"], None):
                b.set_failed(d["reason"])
        elif kind == "file_received":
            b = feed.transfers.pop(d["id"], None)
            if b is None:
                b = FileBubble(False, d["device"], datetime.now().timestamp(), d["name"], d["size"])
                feed.add(b, False)
            b.set_name(d["name"])
            b.set_done(d["path"])
            feed.items[d["item"]] = b
            self.sounds.play("file")
            self._notify(f"{d['device']}: {d['name']}")
        elif kind == "text_received":
            feed.add(TextBubble(False, d["device"], datetime.now().timestamp(), d["text"]),
                     False, item=d["item"])
            self.sounds.play("text")
            self._notify(f"{d['device']}: {d['text'][:200]}")
        elif kind == "file_offered":
            b = FileBubble(True, pc, datetime.now().timestamp(), d["name"], d["size"], d["path"])
            feed.add(b, True, item=d["item"])
        elif kind == "text_offered":
            feed.add(TextBubble(True, pc, datetime.now().timestamp(), d["text"]), True,
                     item=d["item"])
        elif kind == "delivered":
            b = feed.items.get(d["item"])
            if isinstance(b, FileBubble):
                b.set_done(b.path, device=d["device"])
            self.sounds.play("delivered")

    def _notify(self, text: str) -> None:
        if self.tray and not (self.isVisible() and self.isActiveWindow()):
            self.tray.notify(text)

    # --- брандмауэр и тип сети ---

    def check_network(self) -> None:
        """Проверка в фоне (netsh и PowerShell — около секунды)."""
        program = sys.executable
        threading.Thread(target=lambda: self.net_checked.emit(
            firewall.check(program, self.service.ips), False), daemon=True).start()

    def on_net_checked(self, status: firewall.Status, after_fix: bool) -> None:
        self.net = status
        if self._qr:
            self._qr.set_net(status)
        if after_fix:
            self._net_busy = False
            if status.ok:
                self.say("Доступ для телефона открыт")
            else:
                self.say("Не получилось открыть доступ для телефона", bad=True)
            return
        if status.ok:
            return
        ask = QMessageBox(QMessageBox.Warning, "Тропка",
                          net_problem(status) + "\n\nТелефон не сможет подключиться. Разрешить?\n"
                          "Windows попросит подтверждение администратора. "
                          "Делайте это только в домашней сети.", parent=self)
        yes = ask.addButton("Разрешить", QMessageBox.AcceptRole)
        ask.addButton("Не сейчас", QMessageBox.RejectRole)
        ask.exec()
        if ask.clickedButton() is yes:
            self.fix_network()

    def fix_network(self) -> None:
        if self._net_busy or self.net is None:
            return
        self._net_busy = True
        program, public, ips = sys.executable, self.net.public, self.service.ips

        def work() -> None:
            firewall.fix(program, public)  # ждёт, пока пользователь ответит в окне UAC
            self.net_checked.emit(firewall.check(program, ips), True)

        threading.Thread(target=work, daemon=True).start()

    # --- окно, трей, выход ---

    def show_qr(self) -> None:
        self.bring_up()
        if self._qr is None:
            self._qr = QrDialog(self.service, self)
            self._qr.fix_requested.connect(self.fix_network)
        self._qr.set_net(self.net)
        self._qr_skip = set(self.online)  # их переподключение QR не закрывает
        self._qr.refresh()
        self._qr.show()
        self._qr.raise_()
        self._qr.activateWindow()

    def open_downloads(self) -> None:
        from .feed import open_file
        open_file(str(self.bridge.downloads))

    def bring_up(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:
        if self._quitting:
            e.accept()
            return
        e.ignore()
        self.hide()
        if self.tray and not self._hint_shown:
            self._hint_shown = True
            self.tray.notify("Тропка работает в фоне. Открыть или выйти — через значок в трее.")

    def quit_app(self) -> None:
        self._quitting = True
        if self._qr:
            self._qr.close()
        self.close()
        QGuiApplication.instance().quit()
