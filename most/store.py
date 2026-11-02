"""SQLite: подключённые устройства и история передач."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
    id         INTEGER PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    created    REAL NOT NULL,
    last_seen  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history(
    id        INTEGER PRIMARY KEY,
    ts        REAL NOT NULL,
    direction TEXT NOT NULL,   -- in: с телефона на ПК, out: с ПК на телефон
    kind      TEXT NOT NULL,   -- file | text
    device_id INTEGER,         -- in: отправитель; out: получатель (NULL — все)
    name      TEXT,
    path      TEXT,
    size      INTEGER,
    text      TEXT
);
CREATE TABLE IF NOT EXISTS deliveries(
    history_id INTEGER NOT NULL,
    device_id  INTEGER NOT NULL,
    ts         REAL NOT NULL,
    PRIMARY KEY(history_id, device_id)
);
CREATE TABLE IF NOT EXISTS meta(
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""

# Следующий id истории. После очистки id не начинаются с 1 заново
# (history_floor): иначе открытые страницы и старые «скачано» спутали бы новые сообщения со старыми.
_NEXT_ID = """MAX(COALESCE((SELECT MAX(id) FROM history), 0),
    COALESCE((SELECT value FROM meta WHERE key = 'history_floor'), 0))"""

# Что видит устройство :dev в ленте: всё присланное с телефонов
# и всё с ПК, адресованное ему или всем.
_FEED = """
SELECT h.*, d.name AS device, (dl.ts IS NOT NULL) AS delivered
FROM history h
LEFT JOIN devices d ON d.id = h.device_id
LEFT JOIN deliveries dl ON dl.history_id = h.id AND dl.device_id = :dev
WHERE (h.direction = 'in' OR h.device_id IS NULL OR h.device_id = :dev)
"""


class Store:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _run(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._db:
            return self._db.execute(sql, args)

    # --- устройства ---

    def add_device(self, token_hash: str, name: str) -> int:
        now = time.time()
        cur = self._run(
            "INSERT INTO devices(token_hash, name, created, last_seen) VALUES(?,?,?,?)",
            (token_hash, name, now, now),
        )
        return cur.lastrowid

    def device_by_token(self, token_hash: str) -> dict[str, Any] | None:
        row = self._run("SELECT * FROM devices WHERE token_hash=?", (token_hash,)).fetchone()
        return dict(row) if row else None

    def touch_device(self, device_id: int) -> None:
        self._run("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), device_id))

    def forget_old_devices(self, max_age: float) -> None:
        self._run("DELETE FROM devices WHERE last_seen<?", (time.time() - max_age,))

    # --- история ---

    def add_history(self, direction: str, kind: str, device_id: int | None, *,
                    name: str | None = None, path: str | None = None,
                    size: int | None = None, text: str | None = None) -> int:
        cur = self._run(
            "INSERT INTO history(id, ts, direction, kind, device_id, name, path, size, text)"
            f" VALUES({_NEXT_ID} + 1,?,?,?,?,?,?,?,?)",
            (time.time(), direction, kind, device_id, name, path, size, text),
        )
        return cur.lastrowid

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._run(
            "SELECT h.*, d.name AS device,"
            " (SELECT COUNT(*) FROM deliveries dl WHERE dl.history_id=h.id) AS delivered"
            " FROM history h LEFT JOIN devices d ON d.id=h.device_id"
            " ORDER BY h.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_history(self) -> None:
        """Очистить ленту у всех. Файлы на дисках не трогаем."""
        with self._lock, self._db:
            self._db.execute(f"INSERT OR REPLACE INTO meta VALUES('history_floor', {_NEXT_ID})")
            self._db.execute("DELETE FROM deliveries")
            self._db.execute("DELETE FROM history")

    # --- лента телефона ---

    def feed(self, device_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """Последние элементы, видимые устройству, от старых к новым."""
        rows = self._run(_FEED + " ORDER BY h.id DESC LIMIT :lim",
                         {"dev": device_id, "lim": limit}).fetchall()
        return [dict(r) for r in reversed(rows)]

    def feed_item(self, history_id: int, device_id: int) -> dict[str, Any] | None:
        """Элемент ленты, если устройство имеет право его видеть."""
        row = self._run(_FEED + " AND h.id = :id", {"dev": device_id, "id": history_id}).fetchone()
        return dict(row) if row else None

    def mark_delivered(self, history_id: int, device_id: int) -> None:
        self._run("INSERT OR IGNORE INTO deliveries(history_id, device_id, ts) VALUES(?,?,?)",
                  (history_id, device_id, time.time()))

    def pending_for(self, device_id: int) -> list[dict[str, Any]]:
        """Очередь «на телефон»: что ПК отправил устройству, а оно ещё не забрало."""
        rows = self._run(_FEED + " AND h.direction = 'out' AND dl.ts IS NULL ORDER BY h.id",
                         {"dev": device_id}).fetchall()
        return [dict(r) for r in rows]
