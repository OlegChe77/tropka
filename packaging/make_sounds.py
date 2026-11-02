"""Синтезирует звуки ПК в most/sounds/*.wav (мягкие колокольчики, 16 бит моно).

python packaging/make_sounds.py
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "most" / "sounds"

# имя -> ноты (частота Гц, начало с, длительность с)
TUNES = {
    "online": [(660, 0.0, 0.35), (990, 0.11, 0.45)],                    # подключился телефон
    "file": [(784, 0.0, 0.3), (988, 0.09, 0.3), (1319, 0.18, 0.5)],     # пришёл файл
    "text": [(1175, 0.0, 0.35)],                                        # пришёл текст
    "delivered": [(1047, 0.0, 0.3), (784, 0.1, 0.45)],                  # телефон скачал файл
}
VOLUME = 0.35


def render(notes: list[tuple[float, float, float]]) -> bytes:
    length = max(start + dur for _, start, dur in notes) + 0.05
    samples = [0.0] * int(length * RATE)
    for freq, start, dur in notes:
        first = int(start * RATE)
        for i in range(int(dur * RATE)):
            t = i / RATE
            env = min(1.0, t / 0.008) * math.exp(-t * 7 / dur)  # быстрая атака, плавный спад
            tone = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
            samples[first + i] += env * tone / 1.25
    peak = max(abs(s) for s in samples) or 1.0
    return b"".join(struct.pack("<h", int(s / peak * VOLUME * 32767)) for s in samples)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, notes in TUNES.items():
        with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(render(notes))
        print(OUT / f"{name}.wav")


if __name__ == "__main__":
    main()
