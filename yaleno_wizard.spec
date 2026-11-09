# PyInstaller-Spezifikation – baut eine einzelne ausführbare Datei.
#   Linux:   pyinstaller yaleno_wizard.spec   → dist/yaleno-wizard
#   Windows: pyinstaller yaleno_wizard.spec   → dist\yaleno-wizard.exe
# Muss jeweils auf dem Ziel-Betriebssystem gebaut werden.
import sys

block_cipher = None

a = Analysis(
    ["src/yaleno_wizard/__main__.py"],
    pathex=["src"],
    hiddenimports=["yaleno_wizard.catalog.linux", "yaleno_wizard.catalog.windows"],
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtNetwork",
    ],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="yaleno-wizard",
    console=False,
    upx=False,
    strip=sys.platform.startswith("linux"),
)
