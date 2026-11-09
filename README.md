# Yaleno Wizard

Hält **persönliche Dateien, Konfiguration und Einstellungen** auf allen deinen Geräten gleich.
Der **Speicher** – ein SFTP-Server (Anmeldung per SSH-Key), eine **Nextcloud** bzw. ein beliebiger
WebDAV-Server (App-Passwort) oder ein lokaler Ordner – ist die
zentrale Ablage: Dort liegt immer der aktuelle Stand deiner Daten, unabhängig von einem Gerät.
Jedes Gerät gleicht sich mit ihm ab. Frühere Stände bleiben als **Versionen** erhalten, zwischen
denen du vor- und zurückspringen kannst. Läuft unter **Linux und Windows**.

## Ablauf

1. **Speicher verbinden** – SFTP-Server (Host, Port, Benutzer, privater SSH-Key, optional
   Passphrase, Ordner auf dem Server), Nextcloud/WebDAV (siehe unten) oder lokaler Ordner. Unbekannte Server-Host-Keys werden mit
   Fingerprint zur Bestätigung angezeigt und danach gemerkt; ein geänderter Host-Key bricht ab.
2. **Abgleichen** oder **Verlauf** wählen, Gerätename festlegen.
3. **Abgleichen:** Kategorien wählen (Anzahl hier / im Speicher; die Wahl wird gemerkt) →
   Dateien an-/abwählen (kursiv = liegt nur im Speicher und wird geholt) → **Vorschau** aller
   Aktionen, Konfliktregel, Probelauf → Abgleich.
4. **Verlauf:** Version wählen (◀ Älter / Neuer ▶), dann entweder
   - **einzelne Dateien** dieser Version auf dieses Gerät holen (überspringen / beide behalten /
     überschreiben; auch Daten anderer Geräte, z. B. Paketlisten oder `/etc` in einen Ablageordner),
   - oder den **ganzen Speicher auf diese Version setzen** – alle Geräte übernehmen den Stand beim
     nächsten Abgleich. Das wird als neue Version gespeichert; du kannst jederzeit wieder vorspringen.
5. **Fortschritt** mit Log, Abbrechen jederzeit möglich. Logs liegen unter
   `~/.local/state/yaleno-wizard/log` bzw. `%LOCALAPPDATA%\yaleno-wizard\Logs`.

## Wie abgeglichen wird

Für jede Datei vergleicht der Wizard drei Stände: **dieses Gerät**, **Speicher** und den Stand
beim **letzten Abgleich dieses Geräts** (gemerkt unter `~/.config/yaleno-wizard/sync/`).

| Situation | Ergebnis |
|---|---|
| nur hier geändert / neu | wird hochgeladen |
| nur im Speicher geändert / neu | wird auf dieses Gerät geholt |
| hier gelöscht | wird aus dem aktuellen Stand entfernt (bleibt im Verlauf) |
| auf anderem Gerät gelöscht, hier unverändert | wird hier gelöscht (bleibt im Verlauf) |
| gelöscht auf einer Seite, geändert auf der anderen | die geänderte Datei bleibt |
| auf beiden Seiten verschieden geändert | **Konflikt**: Gewinner nach Regel (neuere Änderung / dieses Gerät / Speicher), die andere Fassung bleibt als `name (Konflikt … ).ext` daneben und wird ebenfalls abgeglichen |

Abgewählte Kategorien und Dateien bleiben unberührt. Während eines Abgleichs ist der Speicher
gesperrt (`lock`); eine verwaiste Sperre wird nach 30 Minuten übernommen.

**Welche Daten auf welchen Geräten landen:**

| Bereich | Inhalt | gilt für |
|---|---|---|
| alle Geräte | persönliche Dateien (Dokumente, Bilder, …) | Linux **und** Windows |
| gleiches Betriebssystem | Shell, Git, Editor, Desktop, Browser, SSH-Keys, App-Konfiguration | alle Linux- bzw. alle Windows-Geräte |
| nur dieses Gerät | Systemdateien (`/etc`), Befehlsausgaben (Paketlisten, dconf, Registry) | wird nur hochgeladen, nie automatisch geschrieben – bei Bedarf über *Verlauf* holen |

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

Pfade werden über Platzhalter wie `{DOCUMENTS}` übersetzt, sodass dieselben Dateien unter Linux
in `~/Dokumente` und unter Windows in `C:\Users\…\Documents` liegen.

## Ablage auf dem Speicher

```
<Ordner>/yaleno/
    store.json                     Kennung des Speichers
    HEAD                           Nummer der aktuellen Version
    objects/<ab>/<sha256>          Dateiinhalte – jeder Inhalt nur einmal, egal in wie vielen Versionen
    revisions/00000042.json.gz     vollständiger Dateibaum von Version 42 (Pfad, Größe, Zeit, Rechte, SHA-256)
    revisions/00000042.info.json   Datum, Gerät, Änderungen
```

Eine neue Version entsteht nur, wenn sich am Stand im Speicher etwas ändert. HEAD wird erst
umgesetzt, wenn die Version vollständig geschrieben ist. Jeder Inhalt wird beim Herunterladen
per SHA-256 geprüft.

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
Die Datei kann von Hand bearbeitet und als Vorlage für wiederkehrende Abgleiche genutzt werden.

## Nextcloud / WebDAV einrichten

1. In Nextcloud: **Einstellungen → Sicherheit → „Neues App-Passwort erstellen“** (bei
   Zwei-Faktor-Anmeldung zwingend, sonst empfohlen – es lässt sich dort jederzeit widerrufen).
2. Im Wizard „Nextcloud / WebDAV“ wählen und eintragen:
   - **Server:** die normale Nextcloud-Adresse, z. B. `https://cloud.example.org` (auch mit
     Unterpfad wie `https://example.org/nextcloud`). Der WebDAV-Pfad
     `/remote.php/dav/files/<benutzer-id>/` wird automatisch ermittelt – auch wenn du dich per
     E-Mail anmeldest. Andere WebDAV-Server: die vollständige WebDAV-Adresse eintragen.
   - **Benutzer**, **App-Passwort** (wird dauerhaft gespeichert, siehe unten), **Ordner** in deinen Dateien
     (Standard `Yaleno`, wird bei Bedarf angelegt).

Die Daten liegen dann in Nextcloud unter `Yaleno/yaleno/…`. Bitte diesen Ordner nicht zusätzlich
mit dem Nextcloud-Desktop-Client auf die Geräte synchronisieren – das übernimmt der Wizard.
Nur HTTPS mit gültigem Zertifikat wird akzeptiert.

## SSH-Key einrichten

```bash
ssh-keygen -t ed25519 -f ~/.ssh/yaleno            # Key erzeugen (Passphrase empfohlen)
ssh-copy-id -i ~/.ssh/yaleno.pub benutzer@server   # öffentlichen Teil auf den Server
```

Unter Windows den Inhalt von `yaleno.pub` (Knopf „Öffentlichen Schlüssel kopieren“) auf dem
Server an `~/.ssh/authorized_keys` anhängen. Eine Passphrase wird wie das App-Passwort gespeichert
(abschaltbar).

## Einstellungsdatei (YAML)

Alles, was zur Verbindung und Anmeldung gehört, steht in **einer Datei**:
`~/.config/yaleno-wizard/yaleno.yml` (Windows: `%APPDATA%\yaleno-wizard\yaleno.yml`). Der Wizard
schreibt sie beim Verbinden; sie kann auch von Hand geschrieben und auf andere Geräte kopiert werden
(„Einstellungen laden …“ / „Einstellungen exportieren …“ auf der ersten Seite, oder
`yaleno-wizard --config datei.yml`, oder Umgebungsvariable `YALENO_CONFIG`).

```yaml
storage:
  type: webdav                 # webdav (= nextcloud) | sftp | local
  password_store: keyring      # keyring | file | none
  webdav:
    url: https://cloud.example.org
    username: niko
    folder: Yaleno
    password: xxxxx-xxxxx-xxxxx-xxxxx-xxxxx   # nur bei password_store: file
  sftp:
    host: backup.example.org
    port: 22
    username: niko
    key_file: ~/.ssh/id_ed25519
    path: /srv/backup
    passphrase: ""             # nur bei password_store: file
  local:
    path: /mnt/nas/yaleno
device: niko-pc                # Name dieses Geräts im Speicher
sync:
  categories: [personal, shell, dev]
  conflicts: newer             # newer | local | remote
  exclude:                     # abgewählte Ordner (enden auf /) und Dateien je Kategorie
    personal: ["{DOWNLOADS}/", "{DOCUMENTS}/privat.pdf"]
background:
  enabled: true
  interval_minutes: 15
  autostart: true
```

**Passwörter** (App-Passwort, Passphrase) werden dauerhaft gespeichert, sofern „dauerhaft
speichern“ angehakt ist:

- `password_store: keyring` (Standard) – im Schlüsselbund des Systems (KWallet / GNOME-Schlüsselbund
  über Secret Service, Windows-Anmeldeinformationsverwaltung). In der Datei steht dann kein Passwort.
- `password_store: file` – im Klartext in der YAML-Datei (Rechte `0600`). Wird automatisch verwendet,
  wenn kein Schlüsselbund verfügbar ist, und ist praktisch, um eine fertige Datei auf ein neues Gerät
  zu kopieren. Die Datei dann wie ein Passwort behandeln.
- `password_store: none` – nichts speichern (dann ist kein Hintergrund-Abgleich möglich).

Steht in einer Datei ein `password:`, wird es verwendet – auch ohne `password_store`.

## Hintergrund-Abgleich

Auf der zweiten Seite **„Hintergrund-Abgleich …“**: aktivieren, Abstand (Minuten), Konfliktregel,
„beim Anmelden automatisch starten“. Dann läuft ein Symbol im Infobereich („Jetzt abgleichen“,
„Pausieren“, „Wizard öffnen“, „Beenden“), das im eingestellten Abstand abgleicht und bei Konflikten
oder Fehlern eine Benachrichtigung zeigt. Es gelten die zuletzt im Wizard gewählten Kategorien und
abgewählten Dateien (`sync.categories` / `sync.exclude`).

Sicherheitsbremsen im Hintergrund:

- **Viele Löschungen auf einmal** (ab 25 Dateien und mehr als 20 % des Bestands) werden nicht
  ausgeführt – der Abgleich bricht mit Hinweis ab und muss im Wizard bestätigt werden.
- Fehlt ein **Grundordner** ganz (z. B. Laufwerk nicht eingehängt), gelten seine Dateien nicht als
  gelöscht.
- Gleicht gerade ein anderes Gerät ab, wird es nach 2 Minuten erneut versucht.

Weitere Startarten:

```bash
yaleno-wizard --background        # Symbol im Infobereich (das trägt auch der Autostart ein)
yaleno-wizard --sync              # einmal abgleichen ohne Oberfläche, z. B. per cron/systemd-Timer
                                  # Exit-Code: 0 ok, 1 einzelne Dateien fehlgeschlagen, 2 Fehler
```

Autostart: Linux `~/.config/autostart/yaleno-wizard.desktop`, Windows Registry
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Log: `hintergrund.log` im Log-Ordner.

## Entwicklung

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip ...
.venv/bin/python -m yaleno_wizard          # starten
.venv/bin/pytest -q                        # Tests (inkl. echtem SFTP- und WebDAV-Testserver, GUI offscreen)
.venv/bin/pyinstaller yaleno_wizard.spec   # → dist/yaleno-wizard(.exe)
```

Die Binärdatei muss auf dem jeweiligen Betriebssystem gebaut werden. Der Workflow
`.github/workflows/build.yml` baut Linux und Windows automatisch (bei Tags `v*` oder manuell).
