"""Значок в трее (pystray) и картинка значка программы."""
from __future__ import annotations

import io
import threading
import webbrowser
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from ..config import DONATE_URL

ACCENT = (47, 111, 237, 255)


def icon_image(size: int = 256) -> Image.Image:
    """Синий скруглённый квадрат с белой аркой моста."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=ACCENT)
    w = max(2, s // 14)
    white = (255, 255, 255, 255)
    d.arc((s * 0.18, s * 0.30, s * 0.82, s * 0.94), 180, 360, fill=white, width=w)  # арка
    d.line((s * 0.12, s * 0.62, s * 0.88, s * 0.62), fill=white, width=w)          # настил
    for x in (0.33, 0.5, 0.67):                                                   # опоры
        top = 0.62 - (0.30 if x == 0.5 else 0.25)
        d.line((s * x, s * (top + 0.02), s * x, s * 0.62), fill=white, width=max(1, w // 2))
    return img


def icon_png(size: int = 256) -> bytes:
    buf = io.BytesIO()
    icon_image(size).save(buf, "PNG")
    return buf.getvalue()


class Tray:
    """Меню: «Открыть» (и по щелчку), «Показать QR», «Выход».

    Обработчики вызываются в потоке pystray — окну их надо передавать сигналами.
    """

    def __init__(self, on_open: Callable[[], None], on_qr: Callable[[], None],
                 on_quit: Callable[[], None], title: str = "Тропка") -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Открыть", lambda: on_open(), default=True),
            pystray.MenuItem("Показать QR", lambda: on_qr()),
            pystray.MenuItem("Помощь проекту", lambda: webbrowser.open(DONATE_URL)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", lambda: on_quit()),
        )
        self.icon = pystray.Icon("tropka", icon_image(64), title, menu)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.icon.run, name="tropka-tray", daemon=True)
        self._thread.start()

    def notify(self, text: str, title: str = "Тропка") -> None:
        try:
            self.icon.notify(text, title)
        except Exception:  # уведомления — не главное, ошибки не мешают работе
            pass

    def stop(self) -> None:
        self.icon.stop()
        if self._thread:
            self._thread.join(2)
