"""Kategorien für Windows."""

from __future__ import annotations

from .linux import BROWSER_EXCLUDES, PERSONAL_ITEMS
from .model import Catalog, Category, Item

CHROMIUM_EXCLUDES = BROWSER_EXCLUDES + ("ShaderCache", "GrShaderCache", "Crashpad", "BrowserMetrics*")


def _reg(item_id: str, label: str, key: str) -> Item:
    return Item(
        item_id, label, kind="command",
        backup_cmd=("reg", "export", key, "{OUT}", "/y"),
        restore_cmd=("reg", "import", "{IN}"),
        output_ext="reg",
    )


def build() -> Catalog:
    cats = [
        Category(
            id="personal",
            name="Persönliche Dateien",
            description="Dokumente, Bilder, Musik, Videos, Desktop und Downloads. "
            "Lassen sich auch auf einem Linux-Rechner wiederherstellen.",
            os="windows",
            cross_os=True,
            claim_priority=100,
            items=PERSONAL_ITEMS,
        ),
        Category(
            id="shell",
            name="Shell & Terminal",
            description="PowerShell-Profile, Windows Terminal und Git-Bash.",
            os="windows",
            items=(
                Item("powershell", "PowerShell-Profile", paths=(
                    "{DOCUMENTS}/PowerShell", "{DOCUMENTS}/WindowsPowerShell",
                ), excludes=("Modules",)),
                Item("wt", "Windows Terminal", paths=(
                    "{LOCALAPPDATA}/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json",
                    "{LOCALAPPDATA}/Microsoft/Windows Terminal/settings.json",
                )),
                Item("gitbash", "Git-Bash", paths=("{HOME}/.bashrc", "{HOME}/.bash_profile", "{HOME}/.minttyrc")),
            ),
        ),
        Category(
            id="keys",
            name="SSH- & GPG-Schlüssel",
            description="Private Schlüssel. Sensibel – nur auf einen vertrauenswürdigen Server sichern!",
            os="windows",
            sensitive=True,
            items=(
                Item("ssh", "SSH (%USERPROFILE%\\.ssh)", paths=("{HOME}/.ssh",)),
                Item("gnupg", "GnuPG", paths=("{APPDATA}/gnupg",), excludes=("S.*", "*.lock")),
            ),
        ),
        Category(
            id="dev",
            name="Git & Entwicklung",
            description="Git-Identität, VS Code, Neovim/Vim.",
            os="windows",
            items=(
                Item("git", "Git", paths=("{HOME}/.gitconfig", "{HOME}/.gitignore_global")),
                Item("vscode", "VS Code (Einstellungen, Snippets, Tastenkürzel)", paths=(
                    "{APPDATA}/Code/User", "{APPDATA}/VSCodium/User",
                ), excludes=("workspaceStorage", "globalStorage", "History")),
                Item("vim", "Vim / Neovim", paths=("{HOME}/_vimrc", "{HOME}/.vimrc", "{LOCALAPPDATA}/nvim")),
            ),
        ),
        Category(
            id="desktop",
            name="Windows-Einstellungen",
            description="Registry-Exporte (Desktop, Maus, Tastatur, Explorer-Optionen) und eigene Schriftarten.",
            os="windows",
            items=(
                _reg("reg-control-panel", "Systemsteuerung (Desktop, Maus, Tastatur, Farben)", r"HKCU\Control Panel"),
                _reg("reg-keyboard", "Tastaturlayouts", r"HKCU\Keyboard Layout"),
                _reg("reg-explorer", "Explorer-Optionen",
                     r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"),
                _reg("reg-env", "Benutzer-Umgebungsvariablen", r"HKCU\Environment"),
                Item("fonts", "Eigene Schriftarten", paths=("{LOCALAPPDATA}/Microsoft/Windows/Fonts",)),
                Item("startmenu", "Startmenü-Verknüpfungen", paths=(
                    "{APPDATA}/Microsoft/Windows/Start Menu/Programs",
                )),
            ),
        ),
        Category(
            id="browser",
            name="Browser & E-Mail",
            description="Profile von Firefox, Chrome, Edge, Brave und Thunderbird. "
            "Browser vor dem Sichern schließen (gesperrte Dateien werden sonst übersprungen)!",
            os="windows",
            sensitive=True,
            items=(
                Item("firefox", "Firefox", paths=("{APPDATA}/Mozilla/Firefox",), excludes=BROWSER_EXCLUDES),
                Item("zen", "Zen Browser", paths=("{APPDATA}/zen",), excludes=BROWSER_EXCLUDES),
                Item("firefox-forks", "LibreWolf / Floorp / Waterfox", paths=(
                    "{APPDATA}/librewolf", "{APPDATA}/Floorp", "{APPDATA}/Waterfox",
                ), excludes=BROWSER_EXCLUDES),
                Item("chrome", "Google Chrome", paths=("{LOCALAPPDATA}/Google/Chrome/User Data",),
                     excludes=CHROMIUM_EXCLUDES),
                Item("edge", "Microsoft Edge", paths=("{LOCALAPPDATA}/Microsoft/Edge/User Data",),
                     excludes=CHROMIUM_EXCLUDES),
                Item("brave", "Brave", paths=("{LOCALAPPDATA}/BraveSoftware/Brave-Browser/User Data",),
                     excludes=CHROMIUM_EXCLUDES),
                Item("thunderbird", "Thunderbird", paths=("{APPDATA}/Thunderbird",), excludes=BROWSER_EXCLUDES),
            ),
        ),
        Category(
            id="packages",
            name="Installierte Programme (winget)",
            description="Export aller über winget bekannten Programme. Beim Wiederherstellen kann "
            "die Liste per 'winget import' nachinstalliert werden.",
            os="windows",
            items=(
                Item("winget", "winget-Export", kind="command",
                     backup_cmd=("winget", "export", "-o", "{OUT}", "--accept-source-agreements"),
                     restore_cmd=("winget", "import", "-i", "{IN}", "--accept-package-agreements",
                                  "--accept-source-agreements", "--ignore-unavailable"),
                     output_ext="json"),
            ),
        ),
        Category(
            id="apps",
            name="Weitere Anwendungs-Konfiguration",
            description="Übrige Ordner in AppData\\Roaming, die keiner anderen Kategorie zugeordnet sind.",
            os="windows",
            claim_priority=200,
            default_selected=False,
            items=(
                Item("appdata-rest", "AppData\\Roaming (Rest)", paths=("{APPDATA}/*",), excludes=(
                    "Microsoft", "Mozilla", "zen", "librewolf", "Floorp", "Waterfox", "Code", "VSCodium", "Thunderbird", "discord", "Slack",
                    "Zoom", "Teams", "npm-cache", "*.lock",
                )),
            ),
        ),
    ]
    return Catalog(os="windows", categories=cats)
