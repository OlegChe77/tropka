"""Пути и настройки по умолчанию."""
from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

APP_NAME = "Тропка"
DONATE_URL = "https://dalink.to/olegche"  # «Помощь проекту»
DEFAULT_PORT = 47321

# GUID папки «Загрузки» в реестре Windows
_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"


def data_dir() -> Path:
    """Папка для базы, сертификата и настроек: %APPDATA%\\Tropka.

    Данные старого имени (%APPDATA%\\Most) переносятся, если новой папки ещё нет."""
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    path, old = base / "Tropka", base / "Most"
    if not path.exists() and old.is_dir():
        try:
            old.rename(path)
        except OSError:  # старая программа держит файлы — копируем
            shutil.copytree(old, path, dirs_exist_ok=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    """Куда складывать принятые файлы: «Загрузки\\Tropka»."""
    return _system_downloads() / "Tropka"


def _system_downloads() -> Path:
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value, _ = winreg.QueryValueEx(k, _DOWNLOADS_GUID)
        return Path(os.path.expandvars(value))
    except (ImportError, OSError):
        return Path.home() / "Downloads"


def pc_name() -> str:
    return socket.gethostname()
