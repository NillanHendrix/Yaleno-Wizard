#!/bin/sh
# Yaleno Wizard installieren: Programm nach ~/.local/bin, Startmenü-Eintrag mit Logo.
#   ./install.sh               installieren
#   ./install.sh --uninstall   Startmenü-Eintrag und Programm entfernen
#
# Funktioniert im entpackten Release-Archiv (Programmdatei liegt daneben) und direkt aus dem
# Quellcode (packaging/linux/install.sh, Programmdatei aus dem PyInstaller-Build in dist/).
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
installed="$HOME/.local/bin/yaleno-wizard"

# Programmdatei suchen: neben dem Skript (Archiv), dann dist/ im Quellcode.
find_binary() {
    for candidate in "$here/yaleno-wizard" "$here/../../dist/yaleno-wizard"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

if [ "${1:-}" = "--uninstall" ]; then
    if [ -x "$installed" ]; then
        exec "$installed" --uninstall
    fi
    # Programm fehlt, Reste (Startmenü, Symbole, Autostart) räumt auch eine andere Kopie weg.
    if binary=$(find_binary); then
        chmod +x "$binary"
        exec "$binary" --uninstall
    fi
    echo "Yaleno Wizard ist nicht installiert ($installed fehlt) – nichts zu entfernen."
    exit 0
fi

if [ $# -gt 0 ]; then
    echo "Unbekannte Option: $1" >&2
    echo "Aufruf: $0 [--uninstall]" >&2
    exit 2
fi

if ! binary=$(find_binary); then
    cat >&2 <<EOF
FEHLER: Programmdatei 'yaleno-wizard' nicht gefunden.
Gesucht in:
  $here/yaleno-wizard
  $(cd "$here/../.." 2>/dev/null && pwd || echo "$here/../..")/dist/yaleno-wizard

Entweder das Release-Archiv (yaleno-wizard-<version>-linux-x86_64.tar.gz) entpacken und
dort ./install.sh ausführen, oder im Quellcode zuerst bauen:
  .venv/bin/pyinstaller yaleno_wizard.spec
Ohne Build geht auch:  .venv/bin/python -m yaleno_wizard --install
EOF
    exit 1
fi

chmod +x "$binary"
exec "$binary" --install
