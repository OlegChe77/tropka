"""Адреса компьютера в локальной сети."""
from __future__ import annotations

import socket


def lan_ips() -> list[str]:
    """IPv4-адреса ПК; первым идёт адрес, через который идёт основной маршрут."""
    ips: list[str] = []
    try:
        # UDP-«подключение» ничего не отправляет, только выбирает интерфейс
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    result = []
    for ip in ips:
        if ip.startswith(("127.", "169.254.", "0.")) or ip in result:
            continue
        result.append(ip)
    return result
