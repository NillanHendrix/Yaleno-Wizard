"""Kategorien für Linux."""

from __future__ import annotations

from .model import Catalog, Category, Item

PERSONAL_ITEMS = (
    Item("documents", "Dokumente", paths=("{DOCUMENTS}",)),
    Item("pictures", "Bilder", paths=("{PICTURES}",)),
    Item("music", "Musik", paths=("{MUSIC}",)),
    Item("videos", "Videos", paths=("{VIDEOS}",)),
    Item("desktop", "Schreibtisch", paths=("{DESKTOP}",)),
    Item("downloads", "Downloads", paths=("{DOWNLOADS}",)),
)

BROWSER_EXCLUDES = (
    "Cache*", "*Cache", "cache2", "Code Cache", "GPUCache", "Service Worker", "startupCache",
    "Crash Reports", "crashes", "datareporting", "saved-telemetry-pings", "safebrowsing",
    "storage/default/*/cache", "OptimizationGuidePredictionModels", "Safe Browsing",
    "component_crx_cache", "extensions_crx_cache", "*.lock", "lock", "SingletonLock",
    # Firefox-Familie: neu ladbare Plugins und temporärer Website-Speicher
    "gmp-widevinecdm", "gmp-gmpopenh264", "storage/temporary", "storage/to-be-removed",
)


def build() -> Catalog:
    cats = [
        Category(
            id="personal",
            name="Persönliche Dateien",
            description="Dokumente, Bilder, Musik, Videos, Schreibtisch und Downloads. "
            "Lassen sich auch auf einem Windows-Rechner wiederherstellen.",
            os="linux",
            cross_os=True,
            claim_priority=100,
            items=PERSONAL_ITEMS,
        ),
        Category(
            id="shell",
            name="Shell & Terminal",
            description="Bash/Zsh/Fish-Konfiguration, Prompt, tmux und Terminal-Emulatoren.",
            os="linux",
            items=(
                Item("bash", "Bash", paths=(
                    "{HOME}/.bashrc", "{HOME}/.bash_profile", "{HOME}/.bash_aliases",
                    "{HOME}/.bash_logout", "{HOME}/.profile", "{HOME}/.inputrc",
                )),
                Item("zsh", "Zsh", paths=(
                    "{HOME}/.zshrc", "{HOME}/.zshenv", "{HOME}/.zprofile", "{HOME}/.zlogin",
                    "{HOME}/.p10k.zsh", "{CONFIG}/zsh",
                )),
                Item("fish", "Fish", paths=("{CONFIG}/fish",), excludes=("fish_variables.*",)),
                Item("prompt", "Prompt (Starship)", paths=("{CONFIG}/starship.toml",)),
                Item("tmux", "tmux", paths=("{HOME}/.tmux.conf", "{CONFIG}/tmux")),
                Item("terminals", "Terminal-Emulatoren", paths=(
                    "{CONFIG}/alacritty", "{CONFIG}/kitty", "{CONFIG}/wezterm", "{CONFIG}/foot",
                    "{CONFIG}/ghostty", "{CONFIG}/konsolerc", "{DATA}/konsole",
                    "{CONFIG}/yakuakerc",
                )),
            ),
        ),
        Category(
            id="keys",
            name="SSH- & GPG-Schlüssel",
            description="Private Schlüssel und Vertrauensdaten. Sensibel – nur auf einen "
            "vertrauenswürdigen Server sichern!",
            os="linux",
            sensitive=True,
            items=(
                Item("ssh", "SSH (~/.ssh)", paths=("{HOME}/.ssh",)),
                Item("gnupg", "GnuPG (~/.gnupg)", paths=("{HOME}/.gnupg",),
                     excludes=("S.*", "*.lock", "random_seed")),
                Item("keyrings", "Schlüsselbund (GNOME Keyring / KWallet)", paths=(
                    "{DATA}/keyrings", "{DATA}/kwalletd",
                )),
            ),
        ),
        Category(
            id="dev",
            name="Git & Entwicklung",
            description="Git-Identität, Editoren (VS Code, Neovim, Vim) und Entwicklerwerkzeuge.",
            os="linux",
            items=(
                Item("git", "Git", paths=("{HOME}/.gitconfig", "{CONFIG}/git", "{HOME}/.gitignore_global")),
                Item("vscode", "VS Code (Einstellungen, Snippets, Tastenkürzel)", paths=(
                    "{CONFIG}/Code/User", "{CONFIG}/VSCodium/User", "{CONFIG}/Code - OSS/User",
                ), excludes=("workspaceStorage", "globalStorage", "History")),
                Item("vim", "Vim / Neovim", paths=("{HOME}/.vimrc", "{HOME}/.vim", "{CONFIG}/nvim"),
                     excludes=("undo", "swap", "plugged")),
                Item("tools", "Weitere Werkzeuge", paths=(
                    "{HOME}/.npmrc", "{HOME}/.cargo/config.toml", "{CONFIG}/pip",
                    "{HOME}/.editorconfig", "{CONFIG}/gh/config.yml",
                )),
            ),
        ),
        Category(
            id="desktop",
            name="Desktop-Umgebung",
            description="KDE Plasma, GNOME (dconf), GTK-Themes, Autostart, Standardanwendungen "
            "und Schriftarten.",
            os="linux",
            items=(
                Item("kde", "KDE Plasma", paths=(
                    "{CONFIG}/k*rc", "{CONFIG}/plasma*", "{CONFIG}/kdeglobals",
                    "{CONFIG}/kglobalshortcutsrc", "{CONFIG}/kwinrulesrc", "{CONFIG}/powermanagementprofilesrc",
                    "{DATA}/plasma", "{DATA}/color-schemes", "{DATA}/aurorae", "{DATA}/kxmlgui5",
                ), excludes=("plasmashellrc.lock",)),
                Item("dconf", "GNOME / GTK-Einstellungen (dconf)", kind="command",
                     backup_cmd=("dconf", "dump", "/"), restore_cmd=("dconf", "load", "/"),
                     output_ext="ini"),
                Item("gtk", "GTK-Themes", paths=("{CONFIG}/gtk-3.0", "{CONFIG}/gtk-4.0", "{HOME}/.gtkrc-2.0")),
                Item("autostart", "Autostart & Standardanwendungen", paths=(
                    "{CONFIG}/autostart", "{CONFIG}/mimeapps.list", "{CONFIG}/user-dirs.dirs",
                    "{DATA}/applications",
                )),
                Item("fonts", "Eigene Schriftarten", paths=("{DATA}/fonts", "{HOME}/.fonts", "{CONFIG}/fontconfig")),
            ),
        ),
        Category(
            id="browser",
            name="Browser & E-Mail",
            description="Profile von Firefox (inkl. Zen, LibreWolf, Floorp), Chromium/Chrome/Brave/Vivaldi und Thunderbird "
            "(Lesezeichen, Passwörter, Erweiterungen). Browser vor dem Sichern schließen!",
            os="linux",
            sensitive=True,
            items=(
                Item("firefox", "Firefox", paths=("{HOME}/.mozilla/firefox",), excludes=BROWSER_EXCLUDES),
                Item("zen", "Zen Browser", paths=("{CONFIG}/zen", "{HOME}/.zen"), excludes=BROWSER_EXCLUDES),
                Item("firefox-forks", "LibreWolf / Floorp / Waterfox", paths=(
                    "{HOME}/.librewolf", "{HOME}/.floorp", "{HOME}/.waterfox",
                ), excludes=BROWSER_EXCLUDES),
                Item("chromium", "Chromium", paths=("{CONFIG}/chromium",), excludes=BROWSER_EXCLUDES),
                Item("chrome", "Google Chrome", paths=("{CONFIG}/google-chrome",), excludes=BROWSER_EXCLUDES),
                Item("brave", "Brave", paths=("{CONFIG}/BraveSoftware",), excludes=BROWSER_EXCLUDES),
                Item("vivaldi", "Vivaldi", paths=("{CONFIG}/vivaldi",), excludes=BROWSER_EXCLUDES),
                Item("thunderbird", "Thunderbird", paths=("{HOME}/.thunderbird",), excludes=BROWSER_EXCLUDES),
            ),
        ),
        Category(
            id="packages",
            name="Installierte Programme (Liste)",
            description="Listen der selbst installierten Pakete (pacman, AUR, apt, dnf, Flatpak, Snap). "
            "Werden beim Wiederherstellen als Textdateien abgelegt, um sie nachzuinstallieren.",
            os="linux",
            items=(
                Item("pacman", "pacman (explizit installiert)", kind="command", backup_cmd=("pacman", "-Qqen")),
                Item("aur", "AUR / fremde Pakete", kind="command", backup_cmd=("pacman", "-Qqem")),
                Item("apt", "apt (manuell installiert)", kind="command", backup_cmd=("apt-mark", "showmanual")),
                Item("dnf", "dnf (vom Benutzer installiert)", kind="command",
                     backup_cmd=("dnf", "repoquery", "--userinstalled", "--qf", "%{name}\n")),
                Item("flatpak", "Flatpak-Apps", kind="command",
                     backup_cmd=("flatpak", "list", "--app", "--columns=application,origin")),
                Item("snap", "Snap-Pakete", kind="command", backup_cmd=("snap", "list")),
            ),
        ),
        Category(
            id="system",
            name="Systemkonfiguration (/etc)",
            description="Ausgewählte Systemdateien wie fstab, hosts, Locale, Paketmanager-Konfiguration. "
            "Wird beim Wiederherstellen nur in einen Ablageordner geschrieben (Root-Rechte nötig).",
            os="linux",
            requires_admin=True,
            default_selected=False,
            items=(
                Item("etc-core", "Basis (fstab, hosts, hostname, Locale)", paths=(
                    "{ROOT}/etc/fstab", "{ROOT}/etc/hosts", "{ROOT}/etc/hostname", "{ROOT}/etc/locale.conf",
                    "{ROOT}/etc/locale.gen", "{ROOT}/etc/vconsole.conf", "{ROOT}/etc/environment",
                    "{ROOT}/etc/default/grub", "{ROOT}/etc/mkinitcpio.conf", "{ROOT}/etc/crypttab",
                )),
                Item("etc-pkg", "Paketmanager", paths=(
                    "{ROOT}/etc/pacman.conf", "{ROOT}/etc/pacman.d/mirrorlist", "{ROOT}/etc/makepkg.conf",
                    "{ROOT}/etc/apt/sources.list", "{ROOT}/etc/apt/sources.list.d", "{ROOT}/etc/dnf/dnf.conf",
                )),
                Item("etc-x11", "Xorg / Tastatur", paths=("{ROOT}/etc/X11/xorg.conf.d",)),
                Item("etc-net", "Netzwerk (WLAN-Profile, nur mit Leserechten)", paths=(
                    "{ROOT}/etc/NetworkManager/system-connections",
                )),
            ),
        ),
        Category(
            id="apps",
            name="Weitere Anwendungs-Konfiguration",
            description="Alle übrigen Ordner in ~/.config, die keiner anderen Kategorie zugeordnet sind.",
            os="linux",
            claim_priority=200,
            default_selected=False,
            items=(
                Item("config-rest", "~/.config (Rest)", paths=("{CONFIG}/*",), excludes=(
                    "Code", "Code - OSS", "VSCodium", "chromium", "google-chrome", "BraveSoftware",
                    "vivaldi", "discord", "Slack", "Signal", "pulse", "*.lock", "session",
                )),
            ),
        ),
    ]
    return Catalog(os="linux", categories=cats)
