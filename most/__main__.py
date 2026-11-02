"""Запуск: python -m most [файлы…] [--console] [--port N] [--host IP] [--no-tls]

По умолчанию открывается окно «Лента» со значком в трее.
--console — консольный режим: адрес, PIN и QR печатаются в терминал.
Файлы из аргументов уходят в очередь «на телефон». В консоли
строка с путём к файлу (можно перетащить файл в консоль) отправляет файл,
любая другая строка — текст.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path

import qrcode

from . import config
from .certs import ensure_cert, server_context
from .events import Events
from .netutil import lan_ips
from .server import Bridge
from .store import Store


def _print_event(kind: str, data: dict) -> None:
    if kind == "device_joined":
        print(f"+ Подключилось: {data['name']} ({data['ip']})")
    elif kind == "upload_started":
        print(f"↓ Принимаю: {data['name']} ({data['size'] / 1e6:.1f} МБ) от {data['device']}")
    elif kind == "file_received":
        print(f"✓ Сохранено: {data['path']}")
    elif kind == "upload_failed":
        print(f"✗ Не принят: {data['name']} — {data['reason']}")
    elif kind == "text_received":
        print(f"💬 {data['device']}: {data['text']}")
    elif kind == "file_offered":
        print(f"↑ В очереди на телефон: {data['name']}")
    elif kind == "delivered":
        print(f"✓ {data['device']} скачал: {data['name']}")
    elif kind in ("device_online", "device_offline"):
        state = "на связи" if kind == "device_online" else "отключился"
        print(f"• {data['name']} {state}")


def _read_console(bridge: Bridge) -> None:
    """Поток чтения консоли: путь к файлу → файл, остальное → текст."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        # PowerShell при перетаскивании вставляет  & 'C:\путь'
        raw = line[2:] if line.startswith("& ") else line
        path = Path(raw.strip().strip("\"'"))
        try:
            if path.is_file():
                bridge.offer_file(path)
            elif path.is_dir():
                print("Папки пока не поддерживаются")
            else:
                bridge.offer_text(line)
                print("↑ Текст отправлен")
        except OSError as e:
            print(f"Ошибка: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="tropka", description="Тропка — файлы между ПК и телефоном")
    ap.add_argument("files", nargs="*", help="файлы для отправки на телефон")
    ap.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    ap.add_argument("--host", default="0.0.0.0",
                    help="адрес сервера (127.0.0.1 — для проверок без брандмауэра)")
    ap.add_argument("--no-tls", action="store_true", help="без HTTPS (только для отладки)")
    ap.add_argument("--console", action="store_true", help="без окна, в терминале")
    ap.add_argument("--hidden", action="store_true", help="запуститься свёрнутым в трей")
    args = ap.parse_args()

    if not args.console:
        from .gui import run as run_gui
        sys.exit(run_gui(args.files, host=args.host, port=args.port, tls=not args.no_tls,
                         hidden=args.hidden))
    run_console(args)


def run_console(args: argparse.Namespace) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    data = config.data_dir()
    ips = lan_ips() or ["127.0.0.1"]
    ctx = None if args.no_tls else server_context(*ensure_cert(data, ips))
    store = Store(data / "most.db")
    events = Events()
    events.subscribe(_print_event)
    bridge = Bridge(store, config.downloads_dir(), events, host=args.host, port=args.port,
                    ssl_context=ctx, pc_name=config.pc_name())

    async def run() -> None:
        await bridge.start()
        link = bridge.pair_url(ips[0])
        qr = qrcode.QRCode(border=1)
        qr.add_data(link)
        qr.print_ascii(invert=True)
        qr.make_image().save(data / "qr.png")
        print(f"\nАдрес:  {bridge.url(ips[0])}")
        print(f"PIN:    {bridge.pin}")
        print(f"Файлы:  {bridge.downloads}")
        print("Наведите камеру телефона на QR. Остановить — Ctrl+C.")
        print("Чтобы отправить на телефон: перетащите файл сюда или напишите текст и Enter.\n")
        for f in args.files:
            try:
                bridge.offer_file(f)
            except OSError as e:
                print(f"Ошибка: {e}")
        threading.Thread(target=_read_console, args=(bridge,), daemon=True).start()
        await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == "__main__":
    main()
