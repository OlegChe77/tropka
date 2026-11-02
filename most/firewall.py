"""Пустит ли Windows телефон к «Тропке»: правило брандмауэра и тип сети.

Без прав администратора правила брандмауэра можно только читать (netsh);
исправление — одним запросом UAC (PowerShell от администратора).
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
from dataclasses import dataclass, field

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

# netsh пишет поля по-английски или по-русски — зависит от кодовой страницы консоли
_KEYS = {
    "program": ("Program", "Программа"),
    "enabled": ("Enabled", "Включен", "Включено"),
    "action": ("Action", "Действие"),
    "profiles": ("Profiles", "Профили"),
    "protocol": ("Protocol", "Протокол"),
}
_YES = ("yes", "да")
_ALLOW = ("allow", "разрешить")
_PRIVATE = ("private", "частный", "any", "любой")
_TCP = ("tcp", "any", "любой")


@dataclass
class Status:
    rule: str = "unknown"  # allow | block | missing | unknown
    public: list[dict] = field(default_factory=list)  # [{"index", "name"}] — общедоступные сети

    @property
    def ok(self) -> bool:
        return self.rule in ("allow", "unknown") and not self.public


def _run(args: list[str], timeout: float = 20) -> str:
    out = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW).stdout
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors="replace")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.strip()))


def parse_rules(text: str, program: str) -> str:
    """Итог входящих правил netsh для программы: block важнее allow."""
    target = _norm(program)
    found = set()
    for block in text.replace("\r", "").split("\n\n"):
        rule = {}
        for line in block.splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key = key.strip()
            for name, aliases in _KEYS.items():
                if key in aliases:
                    rule[name] = value.strip()
        if _norm(rule.get("program", "")) != target:
            continue
        if rule.get("enabled", "").lower() not in _YES:
            continue
        if rule.get("protocol", "any").lower() not in _TCP:
            continue
        if rule.get("action", "").lower() not in _ALLOW:
            found.add("block")
        elif any(p.strip().lower() in _PRIVATE for p in rule.get("profiles", "").split(",")):
            found.add("allow")
    return "block" if "block" in found else "allow" if "allow" in found else "missing"


def rule_state(program: str) -> str:
    try:
        text = _run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=in",
                     "verbose"])
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return parse_rules(text, program) if text.strip() else "unknown"


def public_networks(ips: list[str]) -> list[dict]:
    """Сети с адресами ips, которые Windows считает общедоступными."""
    script = ("Get-NetConnectionProfile | ForEach-Object { [pscustomobject]@{"
              "index=$_.InterfaceIndex; name=$_.Name; cat=\"$($_.NetworkCategory)\"; "
              "ips=@(Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 "
              "-ErrorAction SilentlyContinue | ForEach-Object IPAddress) } } | ConvertTo-Json -Compress")
    try:
        data = json.loads(_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
                          or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"index": d["index"], "name": d["name"]} for d in data
            if d.get("cat") == "Public" and set(d.get("ips") or []) & set(ips)]


def check(program: str, ips: list[str]) -> Status:
    return Status(rule_state(program), public_networks(ips))


def fix_script(program: str, public: list[dict]) -> str:
    """PowerShell-скрипт исправления: старые правила программы (в т.ч. «блокировать»,
    если в окне брандмауэра нажали «Отмена») → одно разрешающее; сети → частные."""
    p = program.replace("'", "''")
    lines = [
        f"$p = '{p}'",
        'netsh advfirewall firewall delete rule name=all dir=in program="$p" | Out-Null',
        'netsh advfirewall firewall delete rule name="Мост" dir=in | Out-Null',  # правило старого имени
        'netsh advfirewall firewall add rule name="Тропка" dir=in action=allow '
        'program="$p" profile=private,domain enable=yes | Out-Null',
    ]
    lines += [f"Set-NetConnectionProfile -InterfaceIndex {int(n['index'])} -NetworkCategory Private"
              for n in public]
    return "\n".join(lines)


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p),
                ("lpParameters", ctypes.c_wchar_p), ("lpDirectory", ctypes.c_wchar_p),
                ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p),
                ("hProcess", ctypes.c_void_p)]


def fix(program: str, public: list[dict]) -> bool:
    """Запустить исправление от администратора (окно UAC) и дождаться. False — отказали в UAC."""
    encoded = base64.b64encode(fix_script(program, public).encode("utf-16-le")).decode()
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = f"-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand {encoded}"
    info.nShow = 0  # SW_HIDE
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return False
    if info.hProcess:
        kernel32.WaitForSingleObject(info.hProcess, 60_000)
        kernel32.CloseHandle(info.hProcess)
    return True
