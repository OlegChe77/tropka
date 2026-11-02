"""Звуки ПК через winsound (без QtMultimedia). Вкл/выкл хранится в settings.json."""
from __future__ import annotations

import json
from pathlib import Path

try:
    import winsound
except ImportError:  # не Windows
    winsound = None

SOUND_DIR = Path(__file__).parent / "sounds"
NAMES = ("online", "file", "text", "delivered")


class Sounds:
    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / "settings.json"
        self.enabled = bool(self._load().get("sound", True))

    def _load(self) -> dict:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        data = self._load()
        data["sound"] = on
        try:
            self._file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def play(self, name: str) -> None:
        """Не ждёт конца звука; новый звук прерывает предыдущий."""
        if not self.enabled or winsound is None:
            return
        try:
            winsound.PlaySound(str(SOUND_DIR / f"{name}.wav"),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError:
            pass
