# Yaleno Wizard

Assistent zum **Sichern und Wiederherstellen** von allem Wichtigen auf einem Rechner –
persönliche Dateien, Konfiguration und Einstellungen – auf einen **SFTP-Server** (Anmeldung per
SSH-Key) oder einen lokalen Ordner. Läuft unter **Linux und Windows**.

## Ablauf

1. **Basis-Speicher verbinden** – SFTP-Server (Host, Port, Benutzer, privater SSH-Key, optional
   Passphrase, Ordner auf dem Server) oder lokaler Ordner. Unbekannte Server-Host-Keys werden mit
   Fingerprint zur Bestätigung angezeigt und danach gemerkt; ein geänderter Host-Key bricht ab.
2. **Sichern oder Wiederherstellen** wählen.
3. *(nur Wiederherstellen)* **Sicherung auswählen** (Rechner + Datum).
4. **Kategorien** wählen (mit Anzahl/Größe).
5. **Dateien** im Baum einzeln an-/abwählen, Filter, **Bestand exportieren/importieren**.
6. **Zusammenfassung** – beim Wiederherstellen: Verhalten bei vorhandenen Dateien
   (überspringen / beide behalten / überschreiben), Befehle ausführen, Probelauf.
7. **Fortschritt** mit Log, Abbrechen jederzeit möglich. Logs liegen unter
   `~/.local/state/yaleno-wizard/log` bzw. `%LOCALAPPDATA%\yaleno-wizard\Logs`.

## Kategorien

| Kategorie | Linux | Windows |
|---|---|---|
| Persönliche Dateien *(auch OS-übergreifend)* | Dokumente, Bilder, Musik, Videos, Schreibtisch, Downloads (XDG) | dieselben Known Folders |
| Shell & Terminal | Bash, Zsh, Fish, Starship, tmux, Terminal-Emulatoren | PowerShell-Profile, Windows Terminal, Git-Bash |
| SSH- & GPG-Schlüssel ⚠ | `~/.ssh`, `~/.gnupg`, Schlüsselbund | `.ssh`, GnuPG |
| Git & Entwicklung | Git, VS Code, (Neo)Vim, npm/cargo/pip-Konfig | Git, VS Code, (Neo)Vim |
| Desktop-Umgebung | KDE Plasma, GNOME (`dconf dump`), GTK, Autostart, Schriften | Registry-Exporte (Systemsteuerung, Tastatur, Explorer, Umgebung), Schriften, Startmenü |
| Browser & E-Mail ⚠ | Firefox, Zen, LibreWolf, Floorp, Chromium, Chrome, Brave, Vivaldi, Thunderbird | Firefox, Zen, Chrome, Edge, Brave, Thunderbird |
| Installierte Programme | Paketlisten: pacman, AUR, apt, dnf, Flatpak, Snap | `winget export` |
| Systemkonfiguration | ausgewählte Dateien aus `/etc` | – |
| Weitere Anwendungs-Konfiguration | Rest von `~/.config` | Rest von `AppData\Roaming` |

Caches, `node_modules`, Papierkorb, Lock-Dateien usw. werden automatisch ausgelassen.
Definiert sind die Kategorien in `src/yaleno_wizard/catalog/linux.py` und `windows.py`.

**Wiederherstellung über OS-Grenzen:** Eine Linux-Sicherung kann auf Windows (und umgekehrt) nur
die *persönlichen Dateien* wiederherstellen – Pfade werden über Platzhalter wie `{DOCUMENTS}`
übersetzt. Systemdateien (`/etc`) und Befehlsausgaben (Paketlisten) landen in einem Ablageordner
(`~/Yaleno-Wiederherstellung/<Datum>`), statt still mit Admin-Rechten geschrieben zu werden.

## Ablage auf dem Speicher

```
<Ordner>/yaleno/<rechner>/<YYYY-MM-DD_HHMMSS>/
    manifest.json                                  ← wird zuletzt geschrieben
    files/<kategorie>/<PLATZHALTER>/<pfad>         z. B. files/personal/DOCUMENTS/Rechnung.pdf
```

Jede Sicherung ist ein vollständiger Snapshot, die Dateien bleiben direkt lesbar. Ohne
`manifest.json` (z. B. nach Abbruch) gilt ein Snapshot als ungültig. Jede Datei wird mit SHA-256
geprüft; beim Wiederherstellen werden unveränderte Dateien erkannt und übersprungen.

## Bestand-Textdatei

```
# Yaleno Wizard Bestand v1
# erstellt: 2026-11-09T12:50:00  host: niko-pc  os: linux
[personal]
{DOCUMENTS}/Rechnungen/            ← ganzer Ordner
{PICTURES}/Urlaub/IMG_0001.jpg     ← einzelne Datei
{DOWNLOADS}/*.pdf                  ← Muster
!{DOCUMENTS}/Rechnungen/alt/       ← ausschließen
[shell]
{HOME}/.zshrc
```

Export: auf der Datei-Seite „Bestand exportieren …“ (nur Auswahl oder gesamter Bestand).
Import: „Bestand importieren …“ setzt die Auswahl; nicht gefundene Einträge werden aufgelistet.
Die Datei kann von Hand bearbeitet und als Vorlage für wiederkehrende Sicherungen genutzt werden.

## SSH-Key einrichten

```bash
ssh-keygen -t ed25519 -f ~/.ssh/yaleno            # Key erzeugen (Passphrase empfohlen)
ssh-copy-id -i ~/.ssh/yaleno.pub benutzer@server   # öffentlichen Teil auf den Server
```

Unter Windows den Inhalt von `yaleno.pub` (Knopf „Öffentlichen Schlüssel kopieren“) auf dem
Server an `~/.ssh/authorized_keys` anhängen. Passphrasen werden nie gespeichert.

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip ...
.venv/bin/python -m yaleno_wizard          # starten
.venv/bin/pytest -q                        # Tests (inkl. echtem SFTP-Testserver und GUI offscreen)
.venv/bin/pyinstaller yaleno_wizard.spec   # → dist/yaleno-wizard(.exe)
```

Die Binärdatei muss auf dem jeweiligen Betriebssystem gebaut werden. Der Workflow
`.github/workflows/build.yml` baut Linux und Windows automatisch (bei Tags `v*` oder manuell).
