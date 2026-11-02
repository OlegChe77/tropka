"""Окно «Тропка»: сервер в фоне, лента, значок в трее."""
from __future__ import annotations

import getpass
import json
import logging
import sys

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from ..service import BridgeService
from . import theme
from .tray import Tray, icon_png
from .window import MainWindow

INSTANCE = f"tropka-{getpass.getuser()}"


def _pass_to_running(files: list[str]) -> bool:
    """Если «Тропка» уже открыт — передать ему файлы и показать его окно."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE)
    if not sock.waitForConnected(500):
        return False
    sock.write(json.dumps({"files": files}).encode() + b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _listen(win: MainWindow) -> QLocalServer:
    server = QLocalServer(win)
    QLocalServer.removeServer(INSTANCE)  # остаток после падения
    server.listen(INSTANCE)

    def on_connection() -> None:
        sock = server.nextPendingConnection()

        def on_read() -> None:
            if not sock.canReadLine():
                return
            try:
                msg = json.loads(bytes(sock.readLine()).decode())
            except ValueError:
                msg = {}
            win.bring_up()
            win.send_files(msg.get("files") or [])

        sock.readyRead.connect(on_read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(on_connection)
    return server


def run(files: list[str], *, host: str, port: int, tls: bool, hidden: bool = False) -> int:
    logging.basicConfig(level=logging.WARNING)
    try:  # свой значок на панели задач, а не значок python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Tropka.App")
    except (ImportError, AttributeError, OSError):
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Тропка")
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)  # закрытие окна — уход в трей
    pm = QPixmap()
    pm.loadFromData(QByteArray(icon_png()))
    app.setWindowIcon(QIcon(pm))
    if _pass_to_running(files):
        return 0
    theme.apply(app)

    try:
        service = BridgeService(host=host, port=port, tls=tls)
        service.start()
    except OSError as e:
        QMessageBox.critical(None, "Тропка", f"Не удалось запустить сервер:\n{e}")
        return 1

    win = MainWindow(service)
    _listen(win)
    app.styleHints().colorSchemeChanged.connect(lambda *_: theme.apply(app))
    tray = Tray(win.show_requested.emit, win.qr_requested.emit, win.quit_requested.emit)
    win.tray = tray
    tray.start()
    win.send_files(files)
    if not hidden:
        win.show()
    # Только для exe: из исходников правило пришлось бы давать python.exe целиком
    if getattr(sys, "frozen", False) and host not in ("127.0.0.1", "localhost"):
        win.check_network()
    code = app.exec()
    tray.stop()
    service.stop()
    return code
