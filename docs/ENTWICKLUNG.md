# Entwicklungsdokumentation

Dieses Dokument beschreibt, wie der Yaleno Wizard vom ersten Stand („initial commit“) zur
aktuellen Version umgebaut wurde: was geändert wurde, warum, wie es funktioniert und was noch
offen ist. Bedienung und Dateiformate für Benutzer stehen im [README](../README.md).

## Inhalt

1. [Ausgangslage](#1-ausgangslage)
2. [Ablauf der Arbeiten](#2-ablauf-der-arbeiten)
3. [Architektur](#3-architektur)
4. [Zentraler Speicher und Versionen](#4-zentraler-speicher-und-versionen)
5. [Abgleich (Sync)](#5-abgleich-sync)
6. [Speicher-Anbindungen](#6-speicher-anbindungen)
7. [Einstellungen und Anmeldedaten](#7-einstellungen-und-anmeldedaten)
8. [Hintergrund-Abgleich](#8-hintergrund-abgleich)
9. [Benutzeroberfläche](#9-benutzeroberfläche)
10. [Tests](#10-tests)
11. [Bewusste Entscheidungen](#11-bewusste-entscheidungen)
12. [Bekannte Grenzen und offene Punkte](#12-bekannte-grenzen-und-offene-punkte)
13. [Logo und Installer](#13-logo-und-installer)
14. [Verschlüsselung und Anmeldung](#14-verschlüsselung-und-anmeldung)

---

## 1. Ausgangslage

Der erste Stand war ein reiner **Backup-Assistent**:

- Jede Sicherung legte einen vollständigen, **datierten Snapshot** an:
  `yaleno/<rechner>/<JJJJ-MM-TT_HHMMSS>/files/…` plus `manifest.json`.
- Wiederherstellen hieß: Rechner + Datum wählen, Dateien zurückkopieren.
- Speicher: SFTP (SSH-Key) oder lokaler Ordner.
- Passwörter/Passphrasen wurden nie gespeichert.

Probleme mit Blick auf das Ziel „meine Daten liegen im Speicher und sind unabhängig vom Gerät
verfügbar“:

- Jeder Snapshot war eine **komplette Kopie** – kein Abgleich zwischen Geräten, viel Platz.
- Daten waren **pro Rechner** getrennt; ein zweites Gerät hatte keinen gemeinsamen Stand.
- Änderungen auf einem Gerät kamen nie auf ein anderes.

## 2. Ablauf der Arbeiten

| Schritt | Anlass | Ergebnis |
|---|---|---|
| 1 | `No module named yaleno_wizard` beim Start | Die virtuelle Umgebung war leer. Projekt mit `pip install -e '.[dev]'` installiert (src-Layout braucht eine Installation). Keine Codeänderung. |
| 2 | „Der Speicher soll die zentrale Einheit sein, Ordner nur zum Vor- und Zurückspringen, alles wird gesynct“ | Snapshot-Modell ersetzt durch **zentralen Speicher mit Versionsverlauf** und **Zwei-Wege-Abgleich**. Wizard umgebaut (Abgleichen / Verlauf). |
| 3 | „WebDAV-Support für Nextcloud“ | Neuer Speichertyp **WebDAV** mit Nextcloud-Erkennung. |
| 4 | „App-Passwort dauerhaft speichern, Synchronisation im Hintergrund, Authentifizierung in einer .yml-Datei“ | **Schlüsselbund**-Anbindung, **YAML-Einstellungsdatei**, **Hintergrund-Abgleich** (Infobereich, Autostart, `--sync`). |
| 5 | Commit, Merge, Push | Ein Commit `706328d` auf Branch `zentraler-speicher-sync`, per Fast-Forward nach `main`, nach GitHub gepusht. |
| 6 | Dokumentation | `docs/ENTWICKLUNG.md`, README mit Anleitung und Emojis (`57ceee4`). |
| 7 | „Installer mit Logo und Starter im Startmenü“ | Logo (SVG → PNG/ICO), Windows-Installer (Inno Setup), Linux-Startmenü-Eintrag (`--install`), Release-Workflow. Siehe [Abschnitt 13](#13-logo-und-installer). |
| 8 | „Der Installer unter Linux geht immer noch nicht: *file not found*“ | Ursache: `install.sh` fand die Programmdatei nur im Release-Archiv. **Behoben:** `install.sh` sucht auch in `dist/`, verständliche Fehlermeldung, `--uninstall` ohne Installation; neues `scripts/pack_linux.sh` (auch im Workflow), 9 Tests. Siehe [Abschnitt 13](#13-logo-und-installer). |

Umfang des Umbaus (Schritte 2–4, Commit `706328d`): 41 Dateien, +4479 / −815 Zeilen.
| 9 | „Plugin-Funktionalität per YAML, Plugin-Manager mit Verwaltung und Updates“ – gewünscht u. a. für Prism Launcher, Verschlüsselung, Passkeys und OIDC | Plugin-System, Plugin-Manager (Dialog, Kommandozeile, Update-Hinweis), Verteilung über den Speicher, Ende-zu-Ende-Verschlüsselung, Security-Keys/Passkeys, App-Sperre, Nextcloud-Login im Browser, OIDC. Branch `plugins`, 6 Commits. Siehe [Abschnitt 14](#14-verschlüsselung-und-anmeldung). |
| 10 | „Entferne Plugin-Funktionalität vollständig“ | Plugin-System, Plugin-Manager, `yaleno-wizard plugin …`, Update-Hinweis im Infobereich und Plugin-Ablage im Speicher entfernt. Verschlüsselung, App-Sperre, Security-Keys/Passkeys, Nextcloud-Login im Browser und OIDC sind jetzt fest eingebaut und immer verfügbar; Prism Launcher (Minecraft) entfällt ersatzlos. |

Aktueller Stand: 105 automatische Tests. Änderungen je Version: [CHANGELOG](../CHANGELOG.md).

## 3. Architektur

```
src/yaleno_wizard/
├── __main__.py            Einstieg: Wizard | --background | --sync | --config | encryption …
├── settings.py            YAML-Einstellungsdatei (Profile), Pfade
├── credentials.py         Passwörter, Speicherschlüssel, OIDC-Token: Schlüsselbund oder Datei
├── encryption_cli.py      NEU  yaleno-wizard encryption …
├── security/              NEU  fido2.py (Security-Keys/Passkeys), app_lock.py (App-Sperre)
├── autostart.py           Autostart (Linux .desktop / Windows Run-Schlüssel)
├── install.py             NEU  Startmenü-Eintrag mit Logo (--install / --uninstall)
├── assets/                NEU  Logo: yaleno.svg (Vorlage), PNG 16–512 px, yaleno.ico
├── catalog/               Kategorien und Pfad-Platzhalter
├── core/
│   ├── store.py           NEU  zentraler Speicher: Objekte, Versionen, HEAD, Sperre, Verschlüsselung
│   ├── crypto.py          NEU  AES-256-GCM-Ströme, Schlüsselplätze
│   ├── encryption.py      NEU  Verschlüsselung einschalten, Schlüsselplätze verwalten
│   ├── sync.py            NEU  Drei-Wege-Abgleich: Planen + Ausführen
│   ├── background.py      NEU  Abgleich ohne Oberfläche, Sicherheitsbremsen
│   ├── restore.py         angepasst: holt Dateien aus beliebiger Version
│   ├── scanner.py         unverändert: findet lokale Dateien je Kategorie
│   ├── inventory.py       unverändert: Bestand-Textdatei (Muster werden mitbenutzt)
│   ├── backup.py          ENTFERNT (ersetzt durch sync.py)
│   └── manifest.py        ENTFERNT (ersetzt durch store.py)
├── storage/
│   ├── base.py            + create_exclusive() (für die Sperre)
│   ├── local.py / sftp.py + create_exclusive()
│   ├── webdav.py          NEU  WebDAV/Nextcloud (Basic oder beliebige requests-Auth)
│   ├── auth.py            NEU  Nextcloud Login Flow v2, OIDC (PKCE, Loopback, Bearer + Refresh)
│   └── connect.py         NEU  Speicher aus Einstellungen öffnen (Wizard + Hintergrund)
└── gui/
    ├── pages/history.py   NEU  Verlauf (ersetzt snapshot.py)
    ├── tray.py            NEU  Hintergrund-Abgleich im Infobereich
    ├── background_dialog.py NEU Einstellungen Hintergrund-Abgleich
    ├── encryption_dialog.py / unlock_dialog.py  NEU  Verschlüsselung, Entsperren
    ├── app_lock_dialog.py NEU  App-Sperre (Entsperren beim Start, Einstellungen)
    ├── browser_login.py   NEU  Warte-Fenster für Anmeldungen im Browser
    └── übrige Seiten      angepasst

packaging/
├── windows/yaleno-wizard.iss   NEU  Inno-Setup-Skript (Windows-Installer)
└── linux/install.sh            NEU  Installationsskript im Linux-Archiv
scripts/make_icons.py           NEU  erzeugt PNG/ICO aus dem SVG-Logo
scripts/pack_linux.sh           NEU  packt das Linux-Archiv (lokal und im Workflow)
yaleno_wizard.spec              PyInstaller: Logo, Assets, Windows-Versionsinfo
.github/workflows/build.yml     Tests → Binärdatei → Installer/Archiv → Release (bei Tags)
```

Grundsatz: **Kernlogik (`core/`, `storage/`) kennt kein Qt.** Wizard, Infobereich und
Kommandozeile nutzen dieselben Funktionen; dadurch ist fast alles ohne Oberfläche testbar.

## 4. Zentraler Speicher und Versionen

Datei: `core/store.py`

### Ablage

```
<basis>/yaleno/
    store.json                   Kennung (UUID) und Formatversion
    HEAD                         Nummer der aktuellen Version
    lock                         Sperre während eines Abgleichs
    objects/<ab>/<sha256>        Dateiinhalte, inhaltsadressiert
    revisions/00000042.json.gz   kompletter Dateibaum von Version 42
    revisions/00000042.info.json Kurzinfo: Datum, Gerät, +/~/− Zähler
    tmp/                         Zwischenablage für Uploads
```

- **Inhaltsadressiert:** Der Dateiname eines Objekts ist sein SHA-256. Ein Inhalt liegt nur
  einmal, egal in wie vielen Versionen oder auf wie vielen Geräten er vorkommt.
- **Version = vollständiger Baum** (Pfad, Kategorie, Bereich, Größe, Zeit, Rechte, SHA-256).
  Damit kann man ohne Rückrechnen zu jeder Version springen.
- **Atomar:** Erst Objekte, dann Version, zuletzt `HEAD`. Versionen hinter `HEAD`
  (abgebrochene Schreibversuche) werden ignoriert.
- **Zurücksetzen** (`revert_to`) schreibt den alten Baum als *neue* Version. Der vorherige Stand
  bleibt erhalten – so geht „vor“ und „zurück“ beliebig oft.

### Bereiche (scopes)

Nicht jede Datei gehört auf jedes Gerät. Jeder Eintrag hat einen Bereich:

| Bereich | Kriterium | Beispiel |
|---|---|---|
| `all` | Kategorie ist `cross_os` | Dokumente, Bilder – auch Linux ↔ Windows |
| `os:linux` / `os:windows` | sonst | Shell, Git, Desktop, Browser, SSH-Keys |
| `host:<gerät>` | Befehlsausgabe oder `requires_admin` | Paketlisten, dconf/Registry, `/etc` |

`host:`-Daten sind **„nur hochladen“**: sie werden gesichert, aber nie automatisch auf ein Gerät
geschrieben (dafür bräuchte es Admin-Rechte bzw. es würde ein fremdes System verändern). Über den
Verlauf lassen sie sich gezielt holen (Ablageordner).

### Sperre

`lock` wird **exklusiv angelegt** (`O_EXCL` lokal, `wx` bei SFTP, `If-None-Match: *` bei WebDAV).
Inhalt: Gerät, Zeit, Zufallstoken. Lange Abgleiche erneuern die Zeit alle 5 Minuten; eine Sperre
älter als 30 Minuten gilt als verwaist und wird übernommen. Freigegeben wird nur mit passendem Token.

## 5. Abgleich (Sync)

Datei: `core/sync.py`

### Drei-Wege-Vergleich

Pro Datei werden drei Stände verglichen:

- **L** – lokal (Scan dieses Geräts)
- **R** – Speicher (aktuelle Version, nur Bereiche dieses Geräts)
- **B** – Basis: Stand beim letzten erfolgreichen Abgleich *dieses* Geräts, lokal gespeichert in
  `~/.config/yaleno-wizard/sync/<speicher-id>-<gerät>.json`

| L | R | B | Aktion |
|---|---|---|---|
| = R | = L | – | nichts (Basis aktualisieren) |
| geändert | = B | ✓ | hochladen |
| = B | geändert | ✓ | herunterladen |
| geändert | geändert | ✓/– | **Konflikt** |
| vorhanden | fehlt | – | hochladen (neu) |
| = B | fehlt | ✓ | lokal löschen (anderswo gelöscht) |
| ≠ B | fehlt | ✓ | hochladen (Änderung gewinnt gegen Löschung) |
| fehlt | vorhanden | – | herunterladen (neu) |
| fehlt | = B | ✓ | im Speicher löschen |
| fehlt | ≠ B | ✓ | herunterladen (Änderung gewinnt gegen Löschung) |

Die lokale Prüfsumme wird nur neu berechnet, wenn Größe oder Änderungszeit von der Basis abweichen.

### Konflikte

Regel wählbar: neuere Änderung / dieses Gerät / Speicher. Die unterlegene Fassung geht nie verloren:
sie wird als `name (Konflikt <wer> <datum>).ext` daneben gelegt **und ebenfalls abgeglichen**, damit
sie auf allen Geräten auftaucht.

### Robustheit

- **Planen und Ausführen getrennt:** Der Wizard zeigt den Plan als Vorschau. Hat sich der Speicher
  bis zum Start geändert (anderes Gerät), wird unter Sperre neu geplant.
- **Während des Abgleichs geänderte Dateien** werden nicht überschrieben/gelöscht (Größe/Zeit-Prüfung)
  und beim nächsten Mal behandelt.
- **Abbruch:** Erledigte Aktionen werden als Version übernommen; der Rest folgt beim nächsten Mal.
  Halb geschriebene Dateien gibt es nicht (Schreiben in `.yaleno-part`, dann umbenennen).
- **Fehlender Grundordner** (z. B. Laufwerk nicht eingehängt) zählt nicht als „alles gelöscht“.
- **Abgewählte Kategorien/Dateien** bleiben in beide Richtungen unberührt.
- Neue Geräte werden in der Version unter `devices` registriert (Name → Betriebssystem).

## 6. Speicher-Anbindungen

Alle Speicher erfüllen dieselbe kleine Schnittstelle (`storage/base.py`): `listdir`, `exists`,
`is_dir`, `mkdir`, `open_read`, `open_write`, `rename`, `remove`, `create_exclusive`.

### WebDAV / Nextcloud (`storage/webdav.py`)

Umgesetzt mit `requests`, ohne weitere WebDAV-Bibliothek.

- **Nextcloud-Erkennung:** Antwortet `<url>/status.php`, wird per `PROPFIND current-user-principal`
  die **Benutzer-ID** ermittelt und `/remote.php/dav/files/<id>/` verwendet. Das ist nötig, weil die
  ID vom Anmeldenamen abweichen kann (Anmeldung per E-Mail). Sonst wird die Adresse als WebDAV-Adresse
  genommen.
- **Uploads mit fester `Content-Length`** statt „chunked“: Manche Nextcloud-Installationen
  (nginx + PHP-FPM) speichern bei chunked-Uploads leere Dateien.
- **Zwischendateien enden auf `.yaleno-tmp`**, nicht `.part` – Nextcloud behandelt `*.part` besonders.
- Hochladen in Zwischendatei, dann `MOVE` mit `Overwrite: T` (atomar).
- Abbruch während des Uploads wird erkannt; die Zwischendatei wird gelöscht.
- Verständliche Fehler für 401 (Anmeldung), 403, 507 (Quota), TLS-Probleme.
- Der Zielordner (Standard `Yaleno`) wird bei Bedarf angelegt.

### SFTP

Unverändert bis auf `create_exclusive` (paramiko-Modus `wx` – reines `x` setzt dort kein
Schreib-Flag, das fiel in den Tests auf).

## 7. Einstellungen und Anmeldedaten

### YAML-Datei (`settings.py`)

`profile.json` wurde durch **eine** YAML-Datei ersetzt: `~/.config/yaleno-wizard/yaleno.yml`.
Sie enthält Speicher (alle drei Typen nebeneinander), Gerätename, Kategorien, abgewählte Muster,
Konfliktregel und Hintergrund-Einstellungen. Vollständiges Beispiel im README.

- Wird mit Rechten `0600` geschrieben (kann Passwörter enthalten).
- Strenge Prüfung beim Laden mit deutschen Fehlermeldungen (`ConfigError`).
- `type: nextcloud` wird als Alias für `webdav` akzeptiert.
- Andere Datei: `--config DATEI` oder `YALENO_CONFIG`.
- Alte `profile.json` wird beim ersten Laden übernommen.
- Wizard: „Einstellungen laden …“ / „… exportieren“ (Export fragt, ob das Passwort mit hinein soll).

### Passwörter (`credentials.py`)

| `password_store` | Ort |
|---|---|
| `keyring` (Standard) | Schlüsselbund des Systems: Secret Service (KWallet/GNOME), Windows-Anmeldeinformationen |
| `file` | Klartext in der YAML-Datei – automatischer Rückfall ohne Schlüsselbund |
| `none` | nicht gespeichert |

Ein `password:` von Hand in der Datei hat immer Vorrang. Schlüssel im Schlüsselbund:
Dienst `yaleno-wizard`, Konto z. B. `webdav:<benutzer>@<url>`.

### Abgewählte Dateien

Die Dateiauswahl wird als **kürzeste Muster** gespeichert (ganz abgewählter Ordner → `{DOCUMENTS}/a/`,
ganz abgewählte Kategorie → `*`), im Format der vorhandenen Bestand-Regeln. So bleibt die Datei auch
bei tausenden abgewählten Dateien klein, und neue Dateien in abgewählten Ordnern bleiben abgewählt.

## 8. Hintergrund-Abgleich

Dateien: `core/background.py`, `gui/tray.py`, `autostart.py`, `__main__.py`

- `sync_once()` öffnet den Speicher aus den Einstellungen, scannt die gespeicherten Kategorien,
  wendet die Abwahl an und gleicht mit der eingestellten Konfliktregel ab.
- **Sicherheitsbremse:** ≥ 25 Löschungen **und** > 20 % des Bestands → Abbruch mit Hinweis; das muss
  im Wizard bestätigt werden. Schützt z. B. vor einem versehentlich geleerten Ordner.
- **Unbekannte SSH-Host-Keys** werden im Hintergrund abgelehnt (Bestätigung nur im Wizard).
- **Infobereich** (`--background`): Zeitgeber, „Jetzt abgleichen“, „Pausieren“, „Wizard öffnen“,
  „Beenden“; Benachrichtigung bei Konflikten/Fehlern; bei gesperrtem Speicher neuer Versuch nach
  2 Minuten. Nur **eine Instanz** pro Benutzer (`QLockFile`). Liest die Einstellungen vor jedem Lauf
  neu und beendet sich, wenn der Hintergrund-Abgleich ausgeschaltet wurde.
- **Autostart:** Linux `~/.config/autostart/yaleno-wizard.desktop`, Windows Registry
  `HKCU\…\Run`. Unter Windows wird `pythonw.exe` bevorzugt (kein Konsolenfenster).
- **`--sync`:** ein Lauf für cron/systemd-Timer; Exit-Code 0 ok, 1 einzelne Fehler, 2 Abbruch.
- Log: `hintergrund.log` im Log-Ordner (rotiert ab 2 MB).

## 9. Benutzeroberfläche

| Seite | Inhalt |
|---|---|
| Speicher verbinden | SFTP / Nextcloud-WebDAV / Ordner; „dauerhaft speichern“; Einstellungen laden/exportieren; scrollbar, Status immer sichtbar |
| Was möchtest du tun? | Abgleichen oder Verlauf; Gerätename; Knopf „Hintergrund-Abgleich …“ |
| Verlauf *(neu)* | Versionsliste mit ◀ Älter / Neuer ▶; Daten von welchem Gerät; einzelne Dateien holen **oder** Speicher auf diese Version setzen |
| Kategorien | beim Abgleich Anzahl „hier“ und „im Speicher“; Auswahl wird gemerkt |
| Dateien | Dateien nur im Speicher kursiv; Abwahl wird gemerkt |
| Zusammenfassung | Abgleich: Vorschau aller Aktionen, Konfliktregel, Probelauf, Warnung bei Löschungen |
| Fortschritt | Log, Abbrechen, Ergebnis |

## 10. Tests

105 Tests, laufen in ca. 6 Sekunden (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`):

| Datei | Tests | Inhalt |
|---|---|---|
| `test_sync.py` | 19 | Zwei simulierte Geräte an einem Speicher: Erstabgleich, neues Gerät, Änderungen/Löschungen, Konflikte (alle 3 Regeln), Abwahl, Linux ↔ Windows, Verlauf + Zurücksetzen + wieder Vorspringen, Ablageordner, Pfad-Ausbruch, beschädigte Objekte, Sperre, Änderung zwischen Planen und Ausführen, Probelauf, Abbruch |
| `test_settings_background.py` | 20 | YAML hin und zurück, Rechte 0600, handgeschriebene Datei, Fehlermeldungen, Übernahme `profile.json`, Schlüsselbund + Rückfall, Hintergrund-Abgleich mit Abwahl, Bremse bei Massenlöschung, fehlender Grundordner, `--sync` mit `--config`, Autostart; Logo-Dateien (PNG/ICO gültig), `--install`/`--uninstall` unter Linux inkl. Autostart-Umstellung, `.desktop` mit `desktop-file-validate` |
| `test_webdav.py` | 7 | Gegen echten WebDAV-Server (WsgiDAV): Grundfunktionen inkl. Umlaute/Leerzeichen, großer Upload, Abbruch, exklusives Anlegen + Sperre, Abgleich zweier Geräte; Nextcloud-Erkennung (simuliert) |
| `test_crypto.py` | 14 | Blöcke (Größen, Manipulation, Kürzen, falscher Ort/Schlüssel), Schlüsselplätze, Umstellung eines bestehenden Speichers + zweites Gerät, leerer Speicher, Abbruch mitten in der Umstellung, Plätze verwalten, Hintergrund mit gemerktem Schlüssel, `encryption`-Kommandozeile |
| `test_security.py` | 4 | Security-Key als Schlüsselplatz und App-Sperre mit einem Fake-Authenticator, Key ohne PRF, PRF-Auswertung |
| `test_auth.py` | 6 | Gegen lokalen Stub-Server: Login Flow v2 inkl. Abbruch, OIDC mit PKCE + Loopback, Bearer mit Erneuerung (abgelaufen, widerrufen), falscher `state`, https-Pflicht |
| `test_gui.py` | 11 | Verschlüsseln + Entsperren, App-Sperre, OIDC-/Login-Felder der Verbindungsseite; Wizard offscreen: Abgleichen, erneut abgleichen, Datei aus Version holen, Speicher zurücksetzen; Verbindung über WebDAV inkl. falschem Passwort und Vorausfüllen aus dem Schlüsselbund; Abwahl-Muster; Infobereich; Hintergrund-Dialog; App-Symbol in allen Größen |
| `test_sftp.py` | 4 | Gegen echten SFTP-Testserver: Host-Key-Prüfung, Anmeldung, Abgleich zweier Geräte, Sperre |
| `test_core.py` | 7 | Platzhalter, Scanner, Bestand-Datei |
| `test_install_sh.py` | 13 | `install.sh` (ein Befehl): Optionen, Installieren/Aktualisieren/Entfernen aus einem Release (Versionsvergleich numerisch), `--update` ohne Installation, Quellcode-Stand schon aktuell; `packaging/linux/install.sh` im Archiv- und Quellcode-Layout, fehlende Programmdatei, Deinstallation mit/ohne Installation, `pack_linux.sh` packen → entpacken → installieren |

Alle Tests laufen isoliert: Einstellungen, Logs und **Schlüsselbund** werden pro Test durch
temporäre Ordner bzw. einen Speicher-Schlüsselbund ersetzt – der echte des Systems wird nie berührt.

## 11. Bewusste Entscheidungen

| Entscheidung | Grund | Preis |
|---|---|---|
| Inhaltsadressierte Objekte statt lesbarer Ordner | Deduplizierung, beliebig viele Versionen ohne Kopien, atomare Versionen | Dateien auf dem Server nicht direkt lesbar, nur über die App |
| Vollständiger Baum pro Version | Springen ohne Rückrechnen, einfache Reparatur | etwas mehr Platz für Versionsdateien (gzip) |
| Linearer Verlauf + Sperre statt Verzweigungen | einfach, verständlich für „vor/zurück“ | Geräte gleichen nacheinander ab |
| Basis lokal pro Gerät | nur so sind Löschungen von „nie gehabt“ unterscheidbar | neues Gerät = erster Abgleich ohne Basis (Konflikte statt Überschreiben) |
| Gerätedaten nur hochladen | `/etc` und Paketlisten nicht ungefragt auf fremde Systeme | Wiederherstellung über den Verlauf |
| Konfliktkopien statt Überschreiben | nie Datenverlust | gelegentlich zusätzliche Dateien |
| `requests` statt WebDAV-Bibliothek | wenige, verbreitete Abhängigkeiten; volle Kontrolle über Nextcloud-Eigenheiten | eigener PROPFIND-Code |
| Schlüsselbund als Standard | Passwort nicht im Klartext | unter Linux muss der Schlüsselbund entsperrt sein |
| Bremse bei Massenlöschung nur im Hintergrund | im Wizard sieht man die Vorschau | große Aufräumaktionen einmal im Wizard bestätigen |
| Logo als SVG, PNG/ICO per Skript erzeugt und eingecheckt | eine Vorlage, keine Bildbearbeitungs-Abhängigkeit im Build | nach Logo-Änderung Skript ausführen |
| Inno Setup für Windows | Standardwerkzeug, Startmenü/Deinstallation/Updates ohne eigenen Code, Installation ohne Admin-Rechte | Build nur unter Windows |
| Linux: `--install` im Programm statt Paket (deb/rpm/Flatpak) | ein Archiv für alle Distributionen, kein Root nötig | keine Updates über den Paketmanager |

## 12. Bekannte Grenzen und offene Punkte

**Nicht oder nur teilweise geprüft**

- Gegen eine **echte Nextcloud** (getestet mit WsgiDAV + simulierter Erkennung) – auch Login Flow v2
  und OIDC/`user_oidc` nur gegen einen Stub-Server.
- **Echte Security-Keys/Passkeys:** FIDO2 ist nur mit einem Fake-Authenticator getestet; geprüft ist,
  dass python-fido2 die Optionen inkl. PRF-Erweiterung korrekt annimmt. Mit einem YubiKey o. ä. noch
  auszuprobieren (Einrichten, Entsperren, PIN-Abfrage), ebenso Windows Hello.
- **Echter Schlüsselbund** (KWallet) und echtes **Symbol im Infobereich** (Tests offscreen).
- **Windows** insgesamt (Autostart über Registry, Anmeldeinformationsverwaltung, Pfade).
- **Windows-Installer:** Inno-Setup-Build, Installation, Deinstallation und `--install` per PowerShell
  (geschrieben, aber nur unter Linux entwickelt).
- **Release-Workflow** auf GitHub (läuft erst nach Push eines Tags).
- Geprüft ist dagegen der PyInstaller-Build unter Linux samt `--install` aus der Binärdatei.
- Geprüft ist auch `install.sh` mit der echten Binärdatei: direkt aus dem Quellcode und aus dem mit
  `scripts/pack_linux.sh` gepackten Archiv, jeweils in einem leeren `HOME`, inkl. `--uninstall`.

**Funktional offen**

- **Aufräumen:** Alte Versionen und nicht mehr benutzte Objekte werden nie gelöscht; der Speicher wächst.
  Sinnvoll wäre z. B. „letzte N Versionen / letzte X Tage behalten“ plus Objekt-Bereinigung.
- **Alte Snapshots** (`yaleno/<rechner>/<datum>/`) aus der ersten Version werden nicht übernommen.
- **Große Dateien bei Nextcloud** (mehrere GB) gehen in einem Stück hoch; Nextclouds
  Teil-Upload (chunking v2) ist nicht eingebaut.
- **Selbst signierte Zertifikate** werden abgelehnt; eine Option für eigene CA fehlt.
- **Standardauswahl:** Browser-Profile und SSH-Keys sind vorausgewählt und werden damit zwischen allen
  Geräten desselben Betriebssystems abgeglichen. Browser-Profile können beschädigt werden, wenn der
  Browser auf zwei Geräten gleichzeitig läuft – Abwahl als Standard wäre zu überlegen.
- **Verschlüsselung** lässt sich einschalten, aber (noch) nicht wieder ausschalten. Alte, nicht mehr
  benötigte Objekte bleiben wie bisher liegen.
- Die Verlaufsliste liest pro Version eine kleine Datei – bei sehr vielen Versionen über WebDAV/SFTP
  spürbar langsamer.
- **Keine Code-Signatur:** Windows (SmartScreen) warnt beim ersten Start des Installers vor einem
  unbekannten Herausgeber („Weitere Informationen → Trotzdem ausführen“).
- **Linux nur x86_64** und ohne automatische Updates; ein AppImage oder Flatpak wäre eine Alternative.
- Noch kein Versions-Tag gesetzt – das erste Release entsteht mit `git tag v0.1.0 && git push --tags`.

## 13. Logo und Installer

**Logo:** `src/yaleno_wizard/assets/yaleno.svg` (Zauberhut in zwei Abgleich-Pfeilen, violetter
Hintergrund). `scripts/make_icons.py` rendert daraus mit Qt die PNGs (16–512 px) und baut die
Windows-`yaleno.ico` selbst (PNG-Einträge, 16–256 px) – ohne zusätzliche Abhängigkeit. Die
Ergebnisse liegen im Repository. Verwendet für Fenster/Taskleiste (`app.setWindowIcon`), Infobereich,
`.exe`-Symbol, Installer und Startmenü.

**Windows** (`packaging/windows/yaleno-wizard.iss`, Inno Setup 6):

- Installation ohne Admin-Rechte für den Benutzer, auf Wunsch für alle (`PrivilegesRequiredOverridesAllowed`).
- Startmenü: Wizard, Hintergrund-Abgleich, Deinstallieren; optional Desktop-Symbol.
- Feste `AppId` – Updates ersetzen die alte Version.
- Deinstallation beendet einen laufenden Hintergrund-Abgleich und entfernt den Autostart-Eintrag;
  Einstellungen und Passwörter bleiben.
- Die `.exe` erhält Versionsinformationen (Eigenschaften → Details).

**Linux** (`yaleno_wizard/install.py`, `yaleno-wizard --install`): nach freedesktop-Standard für den
Benutzer – Programm nach `~/.local/bin`, `.desktop`-Datei nach `~/.local/share/applications`, Symbole ins
`hicolor`-Thema; danach werden die Menü-Caches erneuert (KDE/GNOME). Ein bestehender Autostart wird auf
das installierte Programm umgestellt. `StartupWMClass` und `setDesktopFileName` sorgen dafür, dass das
Fenster in der Taskleiste das Logo zeigt. Für die einzelne Windows-`.exe` legt `--install` eine
Startmenü-Verknüpfung per PowerShell an.

**CI** (`.github/workflows/build.yml`): Tests → PyInstaller → Windows: Inno Setup per Chocolatey,
`ISCC`; Linux: `tar.gz` mit `install.sh`. Bei Tags `v*` werden die Installer an ein GitHub-Release
gehängt.

**Geprüft:** Linux-Binärdatei lokal gebaut, `--install` daraus in ein Test-Home ausgeführt,
`.desktop`-Datei mit `desktop-file-validate` geprüft, ICO mit ImageMagick gelesen.
**Nicht geprüft:** Inno-Setup-Build und Installer unter Windows, PowerShell-Verknüpfung,
Release-Workflow (läuft erst auf GitHub).

### Fehler „file not found“ beim Linux-Installer (behoben)

Nachgestellt mit `sh packaging/linux/install.sh` im Projektordner:

```text
chmod: cannot access './yaleno-wizard': No such file or directory
```

- **Ursache:** `install.sh` wechselte in den eigenen Ordner und erwartete dort die Programmdatei.
  Das stimmt nur im Release-Archiv (`yaleno-wizard` + `install.sh` nebeneinander), das nur der
  Workflow packte. Im Quellcode liegt das Skript in `packaging/linux/`, die Programmdatei in `dist/`.
  `./install.sh --uninstall` scheiterte genauso, wenn `~/.local/bin/yaleno-wizard` fehlte.
  `yaleno-wizard --install` selbst war nie betroffen.
- **Behebung in `packaging/linux/install.sh`:**
  - sucht die Programmdatei neben sich (Archiv), dann in `../../dist/` (Quellcode);
  - fehlt sie, klare Meldung mit den gesuchten Pfaden und den Auswegen (`pyinstaller …`,
    Release-Archiv, `python -m yaleno_wizard --install`), Exit-Code 1;
  - `--uninstall` nimmt das installierte Programm, sonst die gefundene Programmdatei (räumt auch
    Reste wie Startmenü-Eintrag und Autostart weg), sonst „nichts zu entfernen“ mit Exit-Code 0;
  - unbekannte Optionen → Exit-Code 2; `set -eu`, funktioniert auch bei Aufruf von außerhalb des Ordners.
- **Neu `scripts/pack_linux.sh`:** packt `dist/yaleno-wizard-<version>-linux-x86_64.tar.gz` lokal
  genau so wie der Workflow; der Workflow ruft jetzt dieses Skript auf (eine Quelle statt zwei).
- **Tests `tests/test_install_sh.py` (9):** Archiv-Layout, Quellcode-Layout, fehlende Programmdatei,
  unbekannte Option, Deinstallation (installiert / nicht installiert / aus dem Archiv), Packen +
  Entpacken + Installieren, Packen ohne Build. Eine Platzhalter-Programmdatei protokolliert den Aufruf.
- **Hinweis:** Ein vorhandener Autostart-Eintrag aus der Zeit vor dem Installer
  (`Exec=…/.venv/bin/python -m yaleno_wizard --background`, `Icon=folder-sync`) wird beim nächsten
  `--install` auf `~/.local/bin/yaleno-wizard` umgestellt.

### Installation mit einem Befehl (`install.sh`)

`install.sh` im Hauptordner ist der bequeme Weg für Linux; es lässt sich direkt per
`curl … | sh -s -- --install` ausführen und ruft am Ende immer `yaleno-wizard --install` bzw.
`--uninstall` des Programms auf (dieselbe Logik wie oben, kein zweiter Installationsweg).

- **Quelle:** zuerst `releases/latest` der GitHub-API (Asset `*-linux-x86_64.tar.gz`, nur auf x86_64);
  gibt es keins, wird der Quellcode (`--depth 1`) nach `~/.local/share/yaleno-wizard/build/src`
  geholt, eine eigene venv angelegt und mit PyInstaller gebaut (PyInstaller-Cache ebenfalls dort).
- **Stand:** `~/.local/share/yaleno-wizard/installed-from` enthält `release <version>` oder
  `source <commit>`. `--update` vergleicht mit dem neuesten Release (`sort -V`) bzw. per
  `git ls-remote` mit dem Branch und tut nichts, wenn schon aktuell (`--force` erzwingt).
- **Entfernen:** Programm-`--uninstall`, danach Build-Ordner und Stand-Datei löschen; Einstellungen
  und Schlüsselbund bleiben.
- **Für Tests/Forks:** `YALENO_REPO`, `YALENO_REF`, `YALENO_API` (`none` = ohne Releases),
  `YALENO_PYTHON`. Die Tests nutzen ein Release-Archiv mit Platzhalter-Programm über `file://`.

## 14. Verschlüsselung und Anmeldung

### Verschlüsselung (`core/crypto.py`, `core/store.py`, `core/encryption.py`)

- Alles in `Store` gekapselt: `put_object`/`get_object`/`load_revision`/`list_revisions`
  ver- bzw. entschlüsseln transparent, `sync.py`, `restore.py` und die Oberfläche blieben unverändert.
- **Format:** 1-MiB-Blöcke AES-256-GCM, Nonce = 8-Byte-Zufall + Blockzähler, AAD = Kontext
  (`obj:<name>`, `rev:<n>`, `info:<n>`) + Zähler + Endblock-Kennung. Vertauschen,
  Verschieben, Kürzen und Verlängern fallen auf. Objektnamen = HMAC-SHA256 der Klartext-Prüfsumme,
  damit der Server bekannte Dateien nicht an ihrer Prüfsumme erkennt.
- **Hochladen:** erst Prüfsumme berechnen (zweiter Lesedurchgang), dann nur fehlende Inhalte
  verschlüsselt (über `SpooledTemporaryFile`) hochladen – Deduplizierung bleibt erhalten.
- **Schlüsselplätze:** Hauptschlüssel umhüllt mit AES-GCM; Schlüssel aus scrypt (Passwort,
  N = 2^17), HKDF (Wiederherstellungsschlüssel, 256 Bit, Base32) bzw. HKDF über das FIDO2-PRF-Ergebnis.
  `check` (HKDF-Ableitung) erkennt den richtigen Hauptschlüssel. Mindestens ein Passwort oder
  Wiederherstellungsschlüssel muss bleiben.
- **Umstellung:** neue Ordner `eobjects/`, `erevisions/`; `store.json` wird erst am
  Ende auf Version 2 gesetzt, danach werden die alten Ordner gelöscht (`Storage.remove_tree`). Die
  Speicher-ID bleibt gleich, daher gelten die Abgleich-Zustände der Geräte weiter. Ältere
  Programmversionen verweigern Version 2 mit „neuere Version“.
- **Gemerkter Schlüssel** (`credentials.save_store_key`) für den Hintergrund-Abgleich; fehlt er,
  bricht dieser mit einer verständlichen Meldung ab.

### Security-Keys, Passkeys und App-Sperre (`security/`)

- `Fido2Backend` kapselt die Hardware: `HardwareBackend` nutzt python-fido2 (Linux: HID-Geräte,
  Windows: WebAuthn-API) und prüft Registrierung und Anmeldung mit `Fido2Server`. RP-ID ist fest
  `yaleno.wizard`, damit ein Key auf allen Geräten funktioniert.
- Speicher: Registrierung mit PRF, danach eine Anmeldung mit zufälligem Salz; das PRF-Ergebnis
  umhüllt den Hauptschlüssel. Keys ohne PRF werden für den Speicher abgelehnt (für die App-Sperre
  reichen sie).
- App-Sperre: scrypt-Hash des Passworts bzw. gespeicherte Credentials in `yaleno.yml`; geprüft vor dem
  Öffnen des Wizards, auch aus dem Infobereich. Bewusst nur Bedienschutz.

### Anmeldung im Browser (`storage/auth.py`)

- **Login Flow v2:** `POST /index.php/login/v2`, Browser öffnen, Endpoint abfragen, bis Nextcloud
  Server, Login-Name und App-Passwort liefert. Danach wie eine normale App-Passwort-Verbindung.
- **OIDC:** Discovery, Authorization Code + PKCE (S256), `state` und `nonce`, Loopback-Server auf
  `127.0.0.1` mit zufälligem Port. `OIDCBearerAuth` (requests-`AuthBase`) erneuert das Access-Token
  vor Ablauf und einmalig bei 401 und merkt rotierte Refresh-Tokens. `WebDAVStorage`/
  `discover_dav_root` nehmen dafür optional eine eigene Auth an.

