# PyInstaller: «Тропка» в один .exe без консоли. Запуск — через build.ps1
# (он же готовит build/most.ico и build/version_info.txt).
import os

ROOT = os.path.dirname(SPECPATH)
WORK = os.path.join(ROOT, "build")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "most", "web"), "most/web"),
           (os.path.join(ROOT, "most", "sounds"), "most/sounds")],
    hiddenimports=["pystray._win32"],
    excludes=["tkinter", "numpy", "PIL.ImageQt", "PIL._avif", "unittest", "pydoc"],
)

# Лишнее из PySide6: программный OpenGL, Qt Quick/QML/PDF (тянутся плагинами),
# экранная клавиатура, переводы Qt кроме русского.
DROP = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard",
        "qpdf", "qtvirtualkeyboard")


def keep(entry):
    name = entry[0].replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    if any(base.startswith(d) for d in DROP):
        return False
    if "/translations/" in name and not base.endswith("_ru.qm"):
        return False
    return True


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Tropka",
    console=False,
    upx=False,
    icon=os.path.join(WORK, "most.ico"),
    version=os.path.join(WORK, "version_info.txt"),
)
