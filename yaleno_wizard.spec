# PyInstaller-Spezifikation – baut eine einzelne ausführbare Datei mit Logo.
#   Linux:   pyinstaller yaleno_wizard.spec   → dist/yaleno-wizard
#   Windows: pyinstaller yaleno_wizard.spec   → dist\\yaleno-wizard.exe
#            danach Installer: iscc packaging\\windows\\yaleno-wizard.iss
# Muss jeweils auf dem Ziel-Betriebssystem gebaut werden.
import re
import sys
from pathlib import Path

block_cipher = None
ASSETS = Path("src/yaleno_wizard/assets")
BUILTIN_PLUGINS = Path("src/yaleno_wizard/plugins/builtin")
VERSION = re.search(r'__version__ = "([^"]+)"', Path("src/yaleno_wizard/__init__.py").read_text()).group(1)

a = Analysis(
    ["src/yaleno_wizard/__main__.py"],
    pathex=["src"],
    datas=[(str(f), "yaleno_wizard/assets") for f in ASSETS.iterdir() if f.suffix in (".png", ".svg", ".ico")]
    + [(str(f), "yaleno_wizard/plugins/builtin") for f in BUILTIN_PLUGINS.glob("*.yml")],
    hiddenimports=["yaleno_wizard.catalog.linux", "yaleno_wizard.catalog.windows",
                   "keyring.backends.SecretService", "keyring.backends.kwallet", "keyring.backends.Windows"],
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtNetwork",
    ],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

version_info = None
if sys.platform.startswith("win"):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040704B0", [
                StringStruct("CompanyName", "Nillan Hendrix"),
                StringStruct("FileDescription", "Yaleno Wizard"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "yaleno-wizard"),
                StringStruct("OriginalFilename", "yaleno-wizard.exe"),
                StringStruct("ProductName", "Yaleno Wizard"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0407, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="yaleno-wizard",
    icon=str(ASSETS / "yaleno.ico"),
    version=version_info,
    console=False,
    upx=False,
    strip=sys.platform.startswith("linux"),
)
