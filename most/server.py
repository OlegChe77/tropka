"""HTTPS-сервер: вход по PIN, файлы и текст между ПК и телефонами.

Лента — общая: всё, что прислал один телефон, видят и могут скачать другие.
С ПК можно отправить всем или одному устройству.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import ssl
import time
import uuid
from pathlib import Path
from urllib.parse import quote, unquote

from aiohttp import web

from .events import Events
from .store import Store

WEB_DIR = Path(__file__).parent / "web"
COOKIE = "most_s"
SESSION_SECONDS = 30 * 24 * 3600
PIN_TRIES = 5
PIN_LOCK_SECONDS = 60
DISK_RESERVE = 50 * 1024 * 1024
CHUNK = 256 * 1024
PROGRESS_EVERY = 0.25  # сек между событиями хода передачи
PORT_ATTEMPTS = 10
MAX_TEXT = 100_000
PING_SECONDS = 20

# что телефон может показать прямо в браузере (запасная кнопка «Посмотреть»); html/svg нельзя — скрипты
VIEW_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".opus": "audio/ogg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".txt": "text/plain; charset=utf-8",
}

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def new_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def safe_name(name: str) -> str:
    """Имя файла без пути и запрещённых в Windows символов."""
    name = name.replace("\\", "/").split("/")[-1]
    name = _BAD_CHARS.sub("_", name).strip().rstrip(". ")
    if not name:
        name = "файл"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    if len(name) > 180:
        stem, ext = os.path.splitext(name)
        name = stem[: 180 - len(ext)] + ext
    return name


def guess_device(user_agent: str) -> str:
    ua = user_agent or ""
    for key in ("iPhone", "iPad"):
        if key in ua:
            return key
    m = re.search(r"Android [\d.]+; ([^;)]+)", ua)
    if m and m.group(1).strip() not in ("K", "wv"):
        return m.group(1).strip()
    if "Android" in ua:
        return "Android"
    if "Windows" in ua:
        return "Windows"
    if "Macintosh" in ua:
        return "Mac"
    return "Устройство"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _attachment(name: str) -> str:
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


class Bridge:
    """Сервер «Тропки». Запускается в asyncio-цикле: start() / stop()."""

    def __init__(self, store: Store, downloads: Path, events: Events | None = None, *,
                 host: str = "0.0.0.0", port: int = 0,
                 ssl_context: ssl.SSLContext | None = None, pc_name: str = "") -> None:
        self.store = store
        self.downloads = downloads
        self.events = events or Events()
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.pc_name = pc_name
        self.pin = new_pin()
        self._tries: dict[str, tuple[int, float]] = {}  # ip -> (ошибок, блок до)
        self._runner: web.AppRunner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: list[tuple[int, asyncio.Queue]] = []  # открытые ленты: (устройство, очередь)
        downloads.mkdir(parents=True, exist_ok=True)
        store.forget_old_devices(SESSION_SECONDS)

    # --- запуск ---

    @property
    def scheme(self) -> str:
        return "https" if self.ssl_context else "http"

    def url(self, ip: str) -> str:
        return f"{self.scheme}://{ip}:{self.port}/"

    def pair_url(self, ip: str) -> str:
        """Адрес для QR: с ним телефон входит без ввода PIN."""
        return f"{self.url(ip)}?k={self.pin}"

    def regenerate_pin(self) -> str:
        self.pin = new_pin()
        return self.pin

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[self._middleware])
        app.on_startup.append(self._on_startup)
        app.router.add_get("/", self.index)
        app.router.add_post("/api/login", self.login)
        app.router.add_get("/api/me", self.me)
        app.router.add_put("/api/upload", self.upload)
        app.router.add_post("/api/text", self.text)
        app.router.add_get("/api/feed", self.feed)
        app.router.add_post("/api/clear", self.clear)
        app.router.add_get("/api/events", self.stream)
        app.router.add_get(r"/api/file/{id:\d+}", self.download)
        app.router.add_static("/static/", WEB_DIR)
        return app

    async def _on_startup(self, app: web.Application) -> None:
        self._loop = asyncio.get_running_loop()

    async def start(self) -> None:
        # открытые ленты (SSE) не дают серверу остановиться — ждём их недолго
        self._runner = web.AppRunner(self.make_app(), access_log=None, shutdown_timeout=2)
        await self._runner.setup()
        ports = [0] if self.port == 0 else range(self.port, self.port + PORT_ATTEMPTS)
        for port in ports:
            site = web.TCPSite(self._runner, self.host, port, ssl_context=self.ssl_context)
            try:
                await site.start()
            except OSError:
                continue
            self.port = self._runner.addresses[0][1]
            return
        await self._runner.cleanup()
        raise OSError(f"Порты {self.port}–{self.port + PORT_ATTEMPTS - 1} заняты")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # --- доступ ---

    @web.middleware
    async def _middleware(self, request: web.Request, handler):
        request["device"] = self._device_from(request)
        path = request.path
        if path.startswith("/api/") and path != "/api/login" and request["device"] is None:
            return web.json_response({"error": "Нужен PIN"}, status=401)
        resp = await handler(request)
        if resp.prepared:  # поток событий и файлы уже отправили заголовки
            return resp
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' blob: data:")
        if path.startswith("/api/") or path == "/":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def _device_from(self, request: web.Request) -> dict | None:
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        device = self.store.device_by_token(_hash(token))
        if not device or time.time() - device["last_seen"] > SESSION_SECONDS:
            return None
        if time.time() - device["last_seen"] > 60:
            self.store.touch_device(device["id"])
        return device

    def _check_pin(self, ip: str, pin: str) -> str:
        """'ok' | 'bad' | 'locked'. После PIN_TRIES ошибок адрес ждёт минуту."""
        now = time.time()
        fails, until = self._tries.get(ip, (0, 0.0))
        if until > now:
            return "locked"
        if secrets.compare_digest(pin.encode(), self.pin.encode()):
            self._tries.pop(ip, None)
            return "ok"
        fails += 1
        if fails >= PIN_TRIES:
            self._tries[ip] = (0, now + PIN_LOCK_SECONDS)
        else:
            self._tries[ip] = (fails, 0.0)
        return "bad"

    def _sign_in(self, request: web.Request, resp: web.StreamResponse) -> None:
        token = secrets.token_urlsafe(32)
        name = guess_device(request.headers.get("User-Agent", ""))
        device_id = self.store.add_device(_hash(token), name)
        resp.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, path="/", httponly=True,
                        secure=self.ssl_context is not None, samesite="Lax")
        self.events.emit("device_joined", id=device_id, name=name, ip=request.remote)

    # --- страницы и API ---

    async def index(self, request: web.Request) -> web.StreamResponse:
        pin = request.query.get("k")
        if pin is not None:
            # вход по QR: ставим cookie и убираем PIN из адресной строки
            resp = web.Response(status=302, headers={"Location": "/"})
            if request["device"] is None and self._check_pin(request.remote or "", pin) == "ok":
                self._sign_in(request, resp)
            return resp
        return web.FileResponse(WEB_DIR / "index.html")

    async def login(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except ValueError:
            data = {}
        pin = str(data.get("pin", "")).strip()
        status = self._check_pin(request.remote or "", pin)
        if status == "locked":
            return web.json_response({"error": "Слишком много попыток. Подождите минуту."}, status=429)
        if status == "bad":
            return web.json_response({"error": "Неверный PIN"}, status=403)
        resp = web.json_response({"ok": True})
        self._sign_in(request, resp)
        return resp

    async def me(self, request: web.Request) -> web.Response:
        return web.json_response({"device": request["device"]["name"], "pc": self.pc_name})

    async def upload(self, request: web.Request) -> web.Response:
        """PUT с телом-файлом. Имя — в заголовке X-File-Name (URL-кодированное)."""
        device = request["device"]
        name = safe_name(unquote(request.headers.get("X-File-Name", "")))
        total = request.content_length
        if total is None:
            return web.json_response({"error": "Нет размера файла"}, status=411)
        if shutil.disk_usage(self.downloads).free < total + DISK_RESERVE:
            return web.json_response({"error": "На компьютере мало места"}, status=507)

        tid = uuid.uuid4().hex
        part = self.downloads / f".most-{tid}.part"
        self.events.emit("upload_started", id=tid, name=name, size=total, device=device["name"])
        done, last = 0, 0.0
        try:
            with open(part, "wb") as f:
                async for chunk in request.content.iter_chunked(CHUNK):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last >= PROGRESS_EVERY:
                        last = now
                        self.events.emit("upload_progress", id=tid, done=done, total=total)
            if done != total:
                raise ConnectionError("передача оборвалась")
            target = self._place(part, name)
        except BaseException as e:
            part.unlink(missing_ok=True)
            self.events.emit("upload_failed", id=tid, name=name, reason=str(e) or type(e).__name__)
            raise

        hid = self.store.add_history("in", "file", device["id"], name=target.name,
                                     path=str(target), size=total)
        self.events.emit("file_received", id=tid, item=hid, name=target.name, path=str(target),
                         size=total, device=device["name"])
        self._push(hid)
        return web.json_response({"ok": True, "id": hid, "name": target.name})

    async def text(self, request: web.Request) -> web.Response:
        device = request["device"]
        try:
            text = str((await request.json()).get("text", ""))
        except ValueError:
            text = ""
        if not text.strip():
            return web.json_response({"error": "Пустой текст"}, status=400)
        if len(text) > MAX_TEXT:
            return web.json_response({"error": "Слишком длинный текст"}, status=413)
        hid = self.store.add_history("in", "text", device["id"], text=text)
        self.events.emit("text_received", item=hid, text=text, device=device["name"])
        self._push(hid)
        return web.json_response({"ok": True, "id": hid})

    async def feed(self, request: web.Request) -> web.Response:
        dev = request["device"]["id"]
        items = [self._item_json(r, dev) for r in self.store.feed(dev)]
        for item in items:
            self._mark_text_seen(item, dev)
        return web.json_response({"items": items})

    async def clear(self, request: web.Request) -> web.Response:
        self.clear_feed(request["device"]["name"])
        return web.json_response({"ok": True})

    async def download(self, request: web.Request) -> web.StreamResponse:
        """Файл телефону. Ход скачивания идёт странице по SSE (сообщения "dl"):
        браузер качает сам и странице ничего не говорит."""
        device = request["device"]
        dev = device["id"]
        hid = int(request.match_info["id"])
        row = self.store.feed_item(hid, dev)
        if not row or row["kind"] != "file":
            return web.json_response({"error": "Не найдено"}, status=404)
        path = Path(row["path"])
        if not path.is_file():
            if "view" not in request.query:
                self._tell(dev, {"type": "dl", "id": hid, "state": "error",
                                 "error": "Файла больше нет на компьютере"})
            return web.json_response({"error": "Файла больше нет на компьютере"}, status=410)
        if "view" in request.query:
            return self._view(path, row["name"])
        total = path.stat().st_size
        resp = web.StreamResponse(headers={"Content-Disposition": _attachment(row["name"]),
                                           "Content-Type": "application/octet-stream",
                                           "Cache-Control": "no-store"})
        resp.content_length = total
        await resp.prepare(request)
        self._tell(dev, {"type": "dl", "id": hid, "state": "start", "done": 0, "total": total})
        loop = asyncio.get_running_loop()
        done, last = 0, time.monotonic()
        try:
            with open(path, "rb") as f:
                while chunk := await loop.run_in_executor(None, f.read, CHUNK):
                    await resp.write(chunk)  # обрыв связи — исключение, «скачано» не ставим
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last >= PROGRESS_EVERY:
                        last = now
                        self._tell(dev, {"type": "dl", "id": hid, "state": "progress",
                                         "done": done, "total": total})
            await resp.write_eof()
        except BaseException:
            self._tell(dev, {"type": "dl", "id": hid, "state": "error",
                             "error": "Скачивание оборвалось"})
            raise
        self._tell(dev, {"type": "dl", "id": hid, "state": "done", "done": total, "total": total})
        self._delivered(row, device)
        return resp

    def _view(self, path: Path, name: str) -> web.StreamResponse:
        """Показать файл в браузере («Открыть»). Только безопасные типы, в песочнице."""
        ctype = VIEW_TYPES.get(Path(name).suffix.lower())
        if not ctype:
            return web.json_response({"error": "Этот файл браузер не покажет"}, status=415)
        return web.FileResponse(path, headers={
            "Content-Type": ctype,
            "Content-Disposition": "inline",
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; "
                                       "media-src 'self'; style-src 'unsafe-inline'",
        })

    async def stream(self, request: web.Request) -> web.StreamResponse:
        """Server-Sent Events: новые элементы ленты, пока страница открыта."""
        device = request["device"]
        dev = device["id"]
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-store"})
        await resp.prepare(request)
        queue: asyncio.Queue = asyncio.Queue()
        client = (dev, queue)
        online = any(d == dev for d, _ in self._clients)
        self._clients.append(client)
        if not online:
            self.events.emit("device_online", id=dev, name=device["name"])
        try:
            await resp.write(b"retry: 3000\n\n")
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), PING_SECONDS)
                except asyncio.TimeoutError:
                    await resp.write(b": ping\n\n")
                    continue
                data = json.dumps(msg, ensure_ascii=False)
                await resp.write(f"data: {data}\n\n".encode())
                if msg["type"] == "item":
                    self._mark_text_seen(msg["item"], dev)
        except ConnectionResetError:
            pass
        finally:
            self._clients.remove(client)
            if not any(d == dev for d, _ in self._clients):
                self.events.emit("device_offline", id=dev, name=device["name"])
        return resp

    # --- отправка с ПК (можно звать из любого потока) ---

    def offer_file(self, path: str | Path, device_id: int | None = None) -> int:
        """Поставить файл в очередь «на телефон». device_id=None — всем."""
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Нет такого файла: {p}")
        hid = self.store.add_history("out", "file", device_id, name=p.name,
                                     path=str(p), size=p.stat().st_size)
        self.events.emit("file_offered", item=hid, name=p.name, path=str(p),
                         size=p.stat().st_size)
        self._push(hid)
        return hid

    def offer_text(self, text: str, device_id: int | None = None) -> int:
        hid = self.store.add_history("out", "text", device_id, text=text)
        self.events.emit("text_offered", item=hid, text=text)
        self._push(hid)
        return hid

    def clear_feed(self, by: str | None = None) -> None:
        """Очистить общую ленту у всех (by — имя телефона, None — ПК). Файлы остаются."""
        self.store.clear_history()
        self.events.emit("feed_cleared", device=by)
        for _, queue in list(self._clients):
            self._send(queue, {"type": "clear"})

    def online_devices(self) -> set[int]:
        return {d for d, _ in self._clients}

    # --- лента ---

    def _item_json(self, row: dict, viewer: int) -> dict:
        if row["direction"] == "out":
            who, sender = "pc", self.pc_name
        elif row["device_id"] == viewer:
            who, sender = "me", row["device"]
        else:
            who, sender = "other", row["device"]
        available = row["kind"] == "text" or Path(row["path"] or "").is_file()
        return {"id": row["id"], "ts": row["ts"], "kind": row["kind"], "who": who,
                "sender": sender or "", "name": row["name"], "size": row["size"],
                "text": row["text"], "delivered": bool(row["delivered"]),
                "available": available,
                "view": Path(row["name"] or "").suffix.lower() in VIEW_TYPES}

    def _push(self, hid: int) -> None:
        """Разослать новый элемент открытым лентам (кроме отправителя)."""
        for dev, queue in list(self._clients):
            row = self.store.feed_item(hid, dev)
            if not row or (row["direction"] == "in" and row["device_id"] == dev):
                continue
            self._send(queue, {"type": "item", "item": self._item_json(row, dev)})

    def _tell(self, dev: int, msg: dict) -> None:
        """Сообщение всем открытым страницам одного устройства."""
        for d, queue in list(self._clients):
            if d == dev:
                self._send(queue, msg)

    def _send(self, queue: asyncio.Queue, msg: dict) -> None:
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            queue.put_nowait(msg)
        else:
            self._loop.call_soon_threadsafe(queue.put_nowait, msg)

    def _mark_text_seen(self, item: dict, dev: int) -> None:
        """Текст считается доставленным, как только попал на страницу."""
        if item["kind"] == "text" and not item["delivered"] and item["who"] != "me":
            self.store.mark_delivered(item["id"], dev)

    def _delivered(self, row: dict, device: dict) -> None:
        self.store.mark_delivered(row["id"], device["id"])
        self.events.emit("delivered", item=row["id"], name=row["name"], device=device["name"])

    def _place(self, part: Path, name: str) -> Path:
        """Переименовать .part в свободное имя: «фото.jpg», «фото (1).jpg», …"""
        stem, ext = os.path.splitext(name)
        n = 0
        while True:
            target = self.downloads / (name if n == 0 else f"{stem} ({n}){ext}")
            try:
                os.rename(part, target)  # в Windows не перезаписывает существующий
                return target
            except FileExistsError:
                n += 1
