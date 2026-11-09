# 📝 Änderungen

Alle nennenswerten Änderungen am Yaleno Wizard. Format nach
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach [SemVer](https://semver.org/lang/de/).
Hintergründe und Entscheidungen: [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md).

## [Unveröffentlicht]

### Hinzugefügt

- 🧙 **Logo** (Zauberhut in Abgleich-Pfeilen) für Fenster, Taskleiste, Infobereich und Programmdatei.
- 🪟 **Windows-Installer** (`yaleno-wizard-setup-<version>.exe`): Startmenü-Einträge mit Logo
  (Wizard, Hintergrund-Abgleich, Deinstallieren), optional Desktop-Symbol, ohne Admin-Rechte.
- 🐧 **Linux-Startmenü-Eintrag** mit Logo: `yaleno-wizard --install` / `--uninstall`, Archiv mit `install.sh`.
- 🤖 Build-Workflow hängt Installer bei Tags `v*` an ein GitHub-Release.
- 📚 Anleitung im README, Entwicklungsdokumentation, dieses Änderungsprotokoll.

### Behoben

- 🐧 Linux-Installer: `install.sh` meldete *„No such file or directory“*, wenn es nicht aus dem
  Release-Archiv gestartet wurde. Es findet die Programmdatei jetzt auch in `dist/`, erklärt fehlende
  Dateien verständlich, und `--uninstall` klappt auch ohne vorherige Installation.
- 📦 `scripts/pack_linux.sh` packt das Linux-Archiv lokal wie der Build-Workflow.

## [0.1.0] – 2026-11-09

Erste Version als Abgleich-Werkzeug (Commit `ab56463`). Ersetzt den bisherigen Backup-Assistenten.

### Hinzugefügt

- ☁️ **Zentraler Speicher** mit inhaltsadressierter Ablage und **Versionsverlauf**: zu jeder Version
  vor- und zurückspringen, einzelne Dateien zurückholen oder den ganzen Stand zurücksetzen.
- 🔄 **Zwei-Wege-Abgleich** zwischen beliebig vielen Geräten (Drei-Wege-Vergleich), Löschungen
  inklusive; **Konflikte** ohne Datenverlust (Konfliktkopien).
- 🌍 Bereiche: persönliche Dateien auf allen Geräten (auch Linux ↔ Windows), Einstellungen je
  Betriebssystem, Systemdateien und Paketlisten je Gerät.
- ☁️ **Nextcloud/WebDAV** als Speicher (App-Passwort, automatische Ermittlung des WebDAV-Pfads).
- 🔐 Passwörter dauerhaft im **Schlüsselbund** des Systems (oder in der Einstellungsdatei).
- 📄 Alle Einstellungen in **einer YAML-Datei** (`yaleno.yml`), Import/Export im Wizard, `--config`.
- 🌙 **Hintergrund-Abgleich** mit Symbol im Infobereich, Intervall, Autostart und `--sync`;
  Sicherheitsbremse bei vielen Löschungen.

### Geändert

- Wizard: „Sichern / Wiederherstellen“ wird zu „Abgleichen / Verlauf“, mit Vorschau vor dem Abgleich.
- Die Dateiauswahl wird gemerkt (auch für den Hintergrund-Abgleich).

### Entfernt

- Datierte Snapshot-Ordner (`yaleno/<rechner>/<datum>/`); alte Snapshots werden nicht übernommen.
- `profile.json` (wird beim ersten Start automatisch in `yaleno.yml` übernommen).
