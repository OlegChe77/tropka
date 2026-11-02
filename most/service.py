"""Сервер «Тропки» в отдельном потоке со своим asyncio-циклом (для окна)."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from . import config
from .certs import ensure_cert, server_context
from .events import Events
from .netutil import lan_ips
from .server import Bridge
from .store import Store


class BridgeService:
    """Создаёт хранилище, шину и сервер; start() ждёт, пока сервер поднимется."""

    def __init__(self, *, host: str = "0.0.0.0", port: int = config.DEFAULT_PORT,
                 tls: bool = True, data_dir: Path | None = None,
                 downloads: Path | None = None) -> None:
        self.data_dir = data_dir or config.data_dir()
        ips = lan_ips() or ["127.0.0.1"]
        # адреса для QR; сертификат всегда на адреса в сети, чтобы не пересоздавать его
        self.ips = ["127.0.0.1"] if host in ("127.0.0.1", "localhost") else ips
        ctx = server_context(*ensure_cert(self.data_dir, ips)) if tls else None
        self.store = Store(self.data_dir / "most.db")
        self.events = Events()
        self.bridge = Bridge(self.store, downloads or config.downloads_dir(), self.events,
                             host=host, port=port, ssl_context=ctx, pc_name=config.pc_name())
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def start(self, timeout: float = 10) -> None:
        self._thread = threading.Thread(target=self._run, name="most-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("Сервер не запустился")
        if self._error:
            raise self._error

    def stop(self, timeout: float = 5) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout)
        self.store.close()

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as e:  # ошибка запуска — отдаём в start()
            self._error = e
            self._ready.set()

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        await self.bridge.start()
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            await self.bridge.stop()
