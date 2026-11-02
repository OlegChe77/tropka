"""Простая шина событий: сервер сообщает о подключениях и передачах.

Подписчики вызываются в потоке сервера. Окно (Qt) должно само
перекладывать события в свой поток через сигналы.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

Handler = Callable[[str, dict[str, Any]], None]
log = logging.getLogger(__name__)


class Events:
    def __init__(self) -> None:
        self._subs: list[Handler] = []

    def subscribe(self, fn: Handler) -> None:
        self._subs.append(fn)

    def emit(self, kind: str, **data: Any) -> None:
        for fn in list(self._subs):
            try:
                fn(kind, data)
            except Exception:
                log.exception("Ошибка в обработчике события %s", kind)
