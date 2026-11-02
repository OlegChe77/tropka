"""Готовит для сборки значок (.ico) и свойства файла (версия) в папке build/.

python packaging/make_assets.py build
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from most import __version__  # noqa: E402
from most.config import APP_NAME  # noqa: E402
from most.gui.tray import icon_image  # noqa: E402

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

VERSION_INFO = """\
VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('CompanyName', '{name}'),
      StringStruct('FileDescription', '{name} — файлы между ПК и телефоном'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'tropka'),
      StringStruct('LegalCopyright', '© {name}'),
      StringStruct('OriginalFilename', 'Tropka.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
"""


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build")
    out.mkdir(parents=True, exist_ok=True)
    # Каждый размер рисуем отдельно: уменьшенная картинка 256 в 16×16 слишком мутная
    images = [icon_image(s) for s, _ in ICO_SIZES]
    images[-1].save(out / "most.ico", sizes=ICO_SIZES, append_images=images[:-1])
    parts = [int(p) for p in __version__.split(".")]
    nums = tuple((parts + [0, 0, 0, 0])[:4])
    (out / "version_info.txt").write_text(
        VERSION_INFO.format(nums=nums, ver=".".join(map(str, nums)), name=APP_NAME),
        encoding="utf-8")
    print(f"{APP_NAME} {__version__}: {out / 'most.ico'}, {out / 'version_info.txt'}")


if __name__ == "__main__":
    main()
