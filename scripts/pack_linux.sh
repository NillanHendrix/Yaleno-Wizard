#!/bin/sh
# Packt das Linux-Archiv genauso wie der Build-Workflow:
#   dist/yaleno-wizard-<version>-linux-x86_64.tar.gz  mit  yaleno-wizard + install.sh
#
#   .venv/bin/pyinstaller --noconfirm yaleno_wizard.spec
#   scripts/pack_linux.sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

version=${VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/yaleno_wizard/__init__.py)}
if [ -z "$version" ]; then
    echo "FEHLER: Version nicht gefunden (src/yaleno_wizard/__init__.py)." >&2
    exit 1
fi
if [ ! -f dist/yaleno-wizard ]; then
    echo "FEHLER: dist/yaleno-wizard fehlt – zuerst 'pyinstaller yaleno_wizard.spec' ausführen." >&2
    exit 1
fi

name="yaleno-wizard-$version"
pkg="build/pkg"
rm -rf "$pkg"
mkdir -p "$pkg/$name"
cp dist/yaleno-wizard packaging/linux/install.sh "$pkg/$name/"
chmod 755 "$pkg/$name/yaleno-wizard" "$pkg/$name/install.sh"
archive="dist/$name-linux-x86_64.tar.gz"
tar -C "$pkg" -czf "$archive" "$name"
echo "$archive"
