# 📝 Änderungen

Alle nennenswerten Änderungen am Yaleno Wizard. Format nach
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach [SemVer](https://semver.org/lang/de/).
Hintergründe und Entscheidungen: [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md).

## [Unveröffentlicht]

### Hinzugefügt

- 🧩 **Plugins als YAML-Dateien** (`type: catalog` für weitere Programme, `type: feature` für
  Funktionen) mit **Plugin-Manager**: Dialog „Plugins …“, `yaleno-wizard plugin …`, Updates über die
  Quell-URL je Plugin, täglicher Update-Hinweis im Infobereich, Verteilung über den Speicher an andere Geräte.
- 🎮 Mitgeliefertes Plugin **Prism Launcher (Minecraft)**: Einstellungen, Konten und Instanzen.
- 🛡️ **Ende-zu-Ende-Verschlüsselung** des ganzen Speichers (AES-256-GCM, auch Dateinamen und Verlauf),
  Passwort + Wiederherstellungsschlüssel, absturzsichere Umstellung, `yaleno-wizard encryption …`.
- 🔑 **Security-Keys/Passkeys (FIDO2)** zum Entsperren des Speichers und für die App-Sperre.
- 🔒 **App-Sperre**: Wizard öffnet sich erst nach Passwort oder Security-Key.
- 🌐 **Nextcloud-Anmeldung im Browser** (Login Flow v2, auch per Passkey/2FA) und 🪪 **OIDC**
  (PKCE, Refresh-Token im Schlüsselbund, Bearer-Zugriff auf WebDAV).
- ⚡ **Installation mit einem Befehl** unter Linux: `install.sh --install | --update | --uninstall`
  (auch per `curl … | sh -s -- --install`). Nimmt das fertige Release oder baut aus dem Quellcode,
  `--update` installiert nur, wenn es etwas Neues gibt.
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

Erste Version als Abgleich-Werkzeug (Commit `706328d`). Ersetzt den bisherigen Backup-Assistenten.

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
