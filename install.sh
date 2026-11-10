#!/bin/sh
# Yaleno Wizard mit einem Befehl installieren, aktualisieren oder entfernen (Linux, ohne Root).
#
#   curl -fsSL https://raw.githubusercontent.com/NillanHendrix/Yaleno-Wizard/main/install.sh | sh -s -- --install
#   curl -fsSL https://raw.githubusercontent.com/NillanHendrix/Yaleno-Wizard/main/install.sh | sh -s -- --update
#   curl -fsSL https://raw.githubusercontent.com/NillanHendrix/Yaleno-Wizard/main/install.sh | sh -s -- --uninstall
#
# Oder im Quellcode-Ordner:  sh install.sh --install | --update | --uninstall
#
# Woher das Programm kommt:
#   1. Fertiges Release von GitHub (yaleno-wizard-<version>-linux-x86_64.tar.gz), falls vorhanden.
#   2. Sonst wird aus dem Quellcode gebaut (braucht git und Python >= 3.11, dauert ein paar Minuten).
#      Quellcode und Build-Umgebung liegen in ~/.local/share/yaleno-wizard/build.
#
# Weitere Optionen:
#   --source   immer aus dem Quellcode bauen (auch wenn es ein Release gibt)
#   --force    bei --update auch dann neu installieren, wenn schon aktuell
#
# Umgebungsvariablen (vor allem für Tests und Forks):
#   YALENO_REPO    Git-Adresse des Quellcodes   (Standard: GitHub)
#   YALENO_REF     Branch zum Bauen             (Standard: main)
#   YALENO_API     Adresse der Release-Abfrage  (Standard: GitHub-API, "none" = keine Releases)
#   YALENO_PYTHON  Python-Programm zum Bauen    (Standard: neuestes gefundenes >= 3.11)
set -eu

REPO=${YALENO_REPO:-https://github.com/NillanHendrix/Yaleno-Wizard.git}
REF=${YALENO_REF:-main}
API=${YALENO_API:-https://api.github.com/repos/NillanHendrix/Yaleno-Wizard/releases/latest}
DATA=${XDG_DATA_HOME:-$HOME/.local/share}/yaleno-wizard
BUILD="$DATA/build"
INSTALLED="$HOME/.local/bin/yaleno-wizard"
STAMP="$DATA/installed-from"   # "release <version>" oder "source <commit>"

say() { printf '%s\n' "$*"; }
fail() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Aufruf: install.sh --install | --update | --uninstall  [--source] [--force]

  --install     Yaleno Wizard installieren (Programm nach ~/.local/bin, Startmenü-Eintrag)
  --update      auf die neueste Version aktualisieren (Einstellungen bleiben erhalten)
  --uninstall   Programm und Startmenü-Eintrag entfernen (Einstellungen bleiben erhalten)
  --source      aus dem Quellcode bauen statt ein fertiges Release zu laden
  --force       bei --update auch neu installieren, wenn schon aktuell

Ohne Download:  curl -fsSL https://raw.githubusercontent.com/NillanHendrix/Yaleno-Wizard/main/install.sh | sh -s -- --install
EOF
}

# ---------------------------------------------------------------------- Argumente
action=""
from_source=0
force=0
for arg in "$@"; do
    case $arg in
        --install|--update|--uninstall)
            [ -z "$action" ] || fail "Bitte nur eine von --install, --update, --uninstall angeben."
            action=${arg#--} ;;
        --source) from_source=1 ;;
        --force) force=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unbekannte Option: %s\n\n' "$arg" >&2; usage >&2; exit 2 ;;
    esac
done
if [ -z "$action" ]; then
    usage >&2
    exit 2
fi
case $(uname -s) in
    Linux) ;;
    *) fail "Dieses Skript ist für Linux. Unter Windows bitte den Installer (yaleno-wizard-setup-….exe) nehmen." ;;
esac

# ---------------------------------------------------------------------- Hilfen
need() { command -v "$1" >/dev/null 2>&1; }

download() {  # download URL ZIEL
    if need curl; then
        curl -fsSL --retry 2 -o "$2" "$1"
    elif need wget; then
        wget -q -O "$2" "$1"
    else
        fail "Weder curl noch wget gefunden – bitte eines davon installieren."
    fi
}

installed_version() {
    [ -x "$INSTALLED" ] && "$INSTALLED" --version 2>/dev/null | head -n 1 || true
}

stamp() { mkdir -p "$DATA"; printf '%s\n' "$1" > "$STAMP"; }
stamped() { [ -f "$STAMP" ] && cat "$STAMP" || true; }

version_newer() {  # version_newer A B  → wahr, wenn A neuer als B
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1)" = "$1" ]
}

TMP=""
cleanup() { [ -z "$TMP" ] || rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------- Release
# Setzt REL_VERSION und REL_URL, wenn es ein passendes fertiges Release gibt.
REL_VERSION=""
REL_URL=""
find_release() {
    [ "$from_source" = 0 ] && [ "$API" != "none" ] || return 1
    [ "$(uname -m)" = "x86_64" ] || return 1
    TMP=${TMP:-$(mktemp -d)}
    download "$API" "$TMP/release.json" 2>/dev/null || return 1
    REL_URL=$(grep -o '"browser_download_url"[^,}]*linux-x86_64\.tar\.gz"' "$TMP/release.json" \
              | head -n 1 | sed 's/.*"\([^"]*\)"$/\1/')
    [ -n "$REL_URL" ] || return 1
    REL_VERSION=$(basename "$REL_URL" | sed -n 's/^yaleno-wizard-\(.*\)-linux-x86_64\.tar\.gz$/\1/p')
    [ -n "$REL_VERSION" ] || return 1
}

install_release() {
    say "Lade Yaleno Wizard $REL_VERSION …"
    download "$REL_URL" "$TMP/app.tar.gz" || fail "Download fehlgeschlagen: $REL_URL"
    mkdir -p "$TMP/app"
    tar -xzf "$TMP/app.tar.gz" -C "$TMP/app"
    binary=$(find "$TMP/app" -type f -name yaleno-wizard | head -n 1)
    [ -n "$binary" ] || fail "Im Archiv fehlt die Programmdatei."
    chmod +x "$binary"
    "$binary" --install
    stamp "release $REL_VERSION"
}

# ---------------------------------------------------------------------- Quellcode
find_python() {
    if [ -n "${YALENO_PYTHON:-}" ]; then
        printf '%s\n' "$YALENO_PYTHON"
        return 0
    fi
    for py in python3.13 python3.12 python3.11 python3 python; do
        if need "$py" && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            printf '%s\n' "$py"
            return 0
        fi
    done
    return 1
}

remote_commit() {
    git ls-remote "$REPO" "refs/heads/$REF" 2>/dev/null | cut -f 1
}

fetch_source() {
    need git || fail "git fehlt – bitte installieren (z. B. 'sudo pacman -S git' oder 'sudo apt install git')."
    if [ -d "$BUILD/src/.git" ]; then
        say "Hole den neuesten Quellcode …"
        git -C "$BUILD/src" remote set-url origin "$REPO"
        git -C "$BUILD/src" fetch -q --depth 1 origin "$REF"
        git -C "$BUILD/src" reset -q --hard FETCH_HEAD
    else
        say "Lade den Quellcode …"
        rm -rf "$BUILD/src"
        mkdir -p "$BUILD"
        git clone -q --depth 1 --branch "$REF" "$REPO" "$BUILD/src"
    fi
}

install_source() {
    py=$(find_python) || fail "Python 3.11 oder neuer fehlt – bitte installieren (z. B. 'sudo apt install python3 python3-venv')."
    fetch_source
    if [ ! -x "$BUILD/venv/bin/python" ]; then
        say "Richte die Build-Umgebung ein ($py) …"
        "$py" -m venv "$BUILD/venv" || fail "Konnte keine Python-Umgebung anlegen (Debian/Ubuntu: 'sudo apt install python3-venv')."
    fi
    say "Installiere Abhängigkeiten (beim ersten Mal dauert das etwas) …"
    "$BUILD/venv/bin/python" -m pip install -q --upgrade pip
    "$BUILD/venv/bin/python" -m pip install -q "$BUILD/src" "pyinstaller>=6"
    say "Baue das Programm …"
    (cd "$BUILD/src" && PYINSTALLER_CONFIG_DIR="$BUILD/cache" "$BUILD/venv/bin/pyinstaller" --noconfirm --log-level WARN \
        --distpath "$BUILD/dist" --workpath "$BUILD/work" yaleno_wizard.spec)
    [ -f "$BUILD/dist/yaleno-wizard" ] || fail "Bauen fehlgeschlagen – $BUILD/dist/yaleno-wizard fehlt."
    "$BUILD/dist/yaleno-wizard" --install
    rm -rf "$BUILD/work"
    stamp "source $(git -C "$BUILD/src" rev-parse HEAD)"
}

# ---------------------------------------------------------------------- Aktionen
do_install() {
    if find_release; then
        install_release
    else
        [ "$from_source" = 1 ] || say "Kein fertiges Release gefunden – baue aus dem Quellcode."
        install_source
    fi
    say "Fertig: Yaleno Wizard $(installed_version) ist installiert."
}

do_update() {
    current=$(installed_version)
    if [ -z "$current" ]; then
        say "Yaleno Wizard ist noch nicht installiert – installiere jetzt."
        do_install
        return
    fi
    if find_release; then
        if [ "$force" = 0 ] && ! version_newer "$REL_VERSION" "$current"; then
            say "Yaleno Wizard $current ist aktuell (neuestes Release: $REL_VERSION)."
            return
        fi
        say "Aktualisiere $current → $REL_VERSION."
        install_release
    else
        if [ "$force" = 0 ]; then
            latest=$(remote_commit)
            if [ -n "$latest" ] && [ "$(stamped)" = "source $latest" ]; then
                say "Yaleno Wizard $current ist aktuell (Quellcode-Stand $(printf '%.7s' "$latest"))."
                return
            fi
        fi
        install_source
    fi
    say "Fertig: Yaleno Wizard $(installed_version) ist installiert."
}

do_uninstall() {
    if [ -x "$INSTALLED" ]; then
        "$INSTALLED" --uninstall
    elif [ -x "$BUILD/dist/yaleno-wizard" ]; then
        "$BUILD/dist/yaleno-wizard" --uninstall
    else
        say "Yaleno Wizard ist nicht installiert ($INSTALLED fehlt) – nichts zu entfernen."
    fi
    if [ -d "$BUILD" ] || [ -f "$STAMP" ]; then
        rm -rf "$BUILD" "$STAMP"
        rmdir "$DATA" 2>/dev/null || true
        say "Build-Dateien entfernt."
    fi
}

case $action in
    install) do_install ;;
    update) do_update ;;
    uninstall) do_uninstall ;;
esac
