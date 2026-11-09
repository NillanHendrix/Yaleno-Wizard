# 🧙 Yaleno Wizard

<img src="src/yaleno_wizard/assets/yaleno.svg" width="15%"> <img src="banner.png" width="25%">

Hält **persönliche Dateien, Konfiguration und Einstellungen** auf allen deinen Geräten gleich. 💻🔄🖥️

Der **Speicher** ist die zentrale Ablage: Dort liegt immer der aktuelle Stand deiner Daten,
unabhängig von einem Gerät. Jedes Gerät gleicht sich mit ihm ab. Frühere Stände bleiben als
**Versionen** erhalten, zwischen denen du vor- und zurückspringen kannst. ⏪⏩

- ☁️ **Speicher nach Wahl:** Nextcloud bzw. jeder WebDAV-Server, SFTP-Server (SSH-Key) oder ein Ordner
- 🔄 **Zwei-Wege-Abgleich:** Änderungen und Löschungen kommen auf allen Geräten an
- 🕰️ **Versionsverlauf:** einzelne Dateien zurückholen oder den ganzen Stand zurücksetzen
- 🤝 **Konflikte ohne Datenverlust:** die andere Fassung bleibt immer als Kopie erhalten
- 🌙 **Hintergrund-Abgleich** mit Symbol im Infobereich und Autostart
- 🔐 **Passwort im Schlüsselbund** des Systems, alle Einstellungen in **einer YAML-Datei**
- 🐧🪟 läuft unter **Linux und Windows** – persönliche Dateien auch zwischen beiden

## 📑 Inhalt

- [🚀 Anleitung](#anleitung)
  - [1️⃣ Installieren](#installieren)
  - [2️⃣ Speicher vorbereiten](#speicher-vorbereiten)
  - [3️⃣ Erstes Gerät verbinden und abgleichen](#erstes-geraet)
  - [4️⃣ Weitere Geräte hinzufügen](#weitere-geraete)
  - [5️⃣ Hintergrund-Abgleich einschalten](#hintergrund)
  - [6️⃣ Im Verlauf zurückspringen](#verlauf)
  - [💡 Häufige Fragen](#faq)
- [📖 Referenz](#referenz)
- [🛠️ Entwicklung](#entwicklung)

---

<a id="anleitung"></a>

## 🚀 Anleitung

<a id="installieren"></a>

### 1️⃣ Installieren

Beide Wege richten einen **Eintrag mit Logo im Startmenü** ein. 🧙 Den Windows-Installer gibt es
auf GitHub unter **Releases** bzw. *Actions → build* (Artefakte); unter Linux baust und installierst
du direkt aus dem Quellcode mit `packaging/linux/install.sh`.

<details open>
<summary>🪟 <b>Windows</b></summary>

1. `yaleno-wizard-setup-<version>.exe` herunterladen und starten.
2. Installation **für dich allein** (ohne Admin-Rechte) oder für alle Benutzer wählen,
   optional ein Desktop-Symbol anlegen. ✅
3. Im Startmenü erscheinen **Yaleno Wizard**, **Yaleno Wizard – Hintergrund-Abgleich** und
   **Deinstallieren**.

Deinstallieren über *Einstellungen → Apps* oder den Startmenü-Eintrag. Einstellungen und
gespeicherte Passwörter bleiben dabei erhalten.

</details>

<details open>
<summary>🐧 <b>Linux</b></summary>

Voraussetzung: Python ≥ 3.11 und git.

```bash
git clone https://github.com/NillanHendrix/Yaleno-Wizard.git
cd Yaleno-Wizard
python -m venv .venv
.venv/bin/pip install -e ".[dev]"                      # bringt PyInstaller mit
.venv/bin/pyinstaller --noconfirm yaleno_wizard.spec   # baut dist/yaleno-wizard
sh packaging/linux/install.sh                          # Programm nach ~/.local/bin, Startmenü + Logo
```

Danach findest du **Yaleno Wizard** im Anwendungsmenü (KDE, GNOME, XFCE …). Rechtsklick auf den
Eintrag bietet zusätzlich **„Hintergrund-Abgleich starten“**. Keine Root-Rechte nötig. 🙌
Das installierte Programm ist eigenständig – der Quellcode-Ordner kann danach weg.

`packaging/linux/install.sh` legt an (alles nur für dich):

| Was | Wo |
|---|---|
| 📦 Programm | `~/.local/bin/yaleno-wizard` |
| 🧭 Startmenü-Eintrag | `~/.local/share/applications/yaleno-wizard.desktop` |
| 🧙 Logo (16–512 px + SVG) | `~/.local/share/icons/hicolor/*/apps/yaleno-wizard.*` |
| 🌙 Autostart (nur falls eingeschaltet) | `~/.config/autostart/yaleno-wizard.desktop` – wird auf das installierte Programm umgestellt |

**Aktualisieren:** Einstellungen bleiben erhalten.

```bash
git pull
.venv/bin/pyinstaller --noconfirm yaleno_wizard.spec
sh packaging/linux/install.sh
```

**Entfernen:** `sh packaging/linux/install.sh --uninstall` (oder `yaleno-wizard --uninstall`). Ist
nichts installiert, meldet das Skript „nichts zu entfernen“. Einstellungen und gespeicherte
Passwörter bleiben erhalten.

Das Skript nimmt die Programmdatei aus `dist/`. Fehlt sie (Bauen vergessen), sagt es, wo gesucht
wurde und was zu tun ist (siehe [Häufige Fragen](#faq)).

</details>

<details>
<summary>🐍 <b>Ohne Bauen direkt aus dem Quellcode starten</b> (Python ≥ 3.11, auch Windows)</summary>

```bash
git clone https://github.com/NillanHendrix/Yaleno-Wizard.git
cd Yaleno-Wizard
python -m venv .venv
.venv/bin/pip install -e .                 # Windows: .venv\Scripts\pip install -e .
.venv/bin/python -m yaleno_wizard          # Wizard starten
```

Für einen dauerhaften Startmenü-Eintrag unter Linux besser den Weg oben mit
`packaging/linux/install.sh` nehmen. `python -m yaleno_wizard --install` geht auch, der Eintrag
startet dann aber das Python-Modul aus der `.venv` und funktioniert nur, solange der Ordner existiert.

</details>

<a id="speicher-vorbereiten"></a>

### 2️⃣ Speicher vorbereiten

Wähle **eine** Variante:

<details open>
<summary>☁️ <b>Nextcloud</b> (empfohlen, wenn du schon eine hast)</summary>

1. In Nextcloud oben rechts auf dein Profilbild → **Persönliche Einstellungen → Sicherheit**.
2. Ganz unten bei **„Geräte & Sitzungen“** einen Namen eingeben (z. B. `Yaleno`) und
   **„Neues App-Passwort erstellen“** klicken.
3. Das angezeigte Passwort kopieren – du brauchst es gleich im Wizard. 🔑

> 💡 Ein App-Passwort ist bei Zwei-Faktor-Anmeldung zwingend und lässt sich dort jederzeit
> widerrufen, ohne dein eigentliches Passwort zu ändern.

</details>

<details>
<summary>🔒 <b>SFTP-Server</b> (eigener Server oder NAS mit SSH)</summary>

```bash
ssh-keygen -t ed25519 -f ~/.ssh/yaleno            # Schlüssel erzeugen (Passphrase empfohlen)
ssh-copy-id -i ~/.ssh/yaleno.pub benutzer@server   # öffentlichen Teil auf den Server kopieren
ssh benutzer@server mkdir -p /srv/backup           # Zielordner anlegen
```

Unter Windows: im Wizard auf **„Öffentlichen Schlüssel kopieren“** klicken und den Inhalt auf dem
Server an `~/.ssh/authorized_keys` anhängen.

</details>

<details>
<summary>📁 <b>Ordner</b> (Netzlaufwerk, USB-Festplatte)</summary>

Nichts vorzubereiten – der Ordner muss nur auf jedem Gerät erreichbar sein.

</details>

<a id="erstes-geraet"></a>

### 3️⃣ Erstes Gerät verbinden und abgleichen

1. 🔌 **Speicher verbinden** – Variante wählen und ausfüllen:
   - *Nextcloud:* Server `https://cloud.example.org`, Benutzer, App-Passwort, Ordner (`Yaleno`).
   - *SFTP:* Server, Benutzer, SSH-Key, ggf. Passphrase, Ordner auf dem Server.
   - Haken bei **„dauerhaft speichern“** lassen – dann musst du das Passwort nie wieder eingeben. 🔐
   - Bei SFTP fragt der Wizard beim ersten Mal nach dem **Fingerprint** des Servers. Vergleiche ihn
     mit `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` auf dem Server.
2. ✍️ **Was möchtest du tun?** → **Abgleichen** wählen und einen **Gerätenamen** vergeben
   (z. B. `laptop`).
3. 🗂️ **Kategorien** wählen – z. B. *Persönliche Dateien*, *Shell & Terminal*, *Git & Entwicklung*.
4. ☑️ **Dateien** – einzelne Ordner abwählen, die nicht abgeglichen werden sollen
   (z. B. *Downloads*). Die Auswahl wird gemerkt.
5. 👀 **Vorschau** prüfen: was hochgeladen, heruntergeladen oder gelöscht wird.
6. ▶️ **„Jetzt abgleichen“** – fertig! ✅

<a id="weitere-geraete"></a>

### 4️⃣ Weitere Geräte hinzufügen

**Variante A – von Hand:** Auf dem neuen Gerät den Wizard starten, denselben Speicher eintragen,
**einen anderen Gerätenamen** vergeben (z. B. `desktop`) und abgleichen. Das neue Gerät holt alles,
was für es bestimmt ist. 📥

**Variante B – mit Einstellungsdatei:** 📄

1. Auf dem ersten Gerät auf der ersten Seite **„Einstellungen exportieren …“** → auf Wunsch das
   Passwort mit hineinschreiben → z. B. `yaleno.yml` speichern.
2. Datei auf das neue Gerät bringen (USB-Stick, sicherer Weg – sie enthält ggf. dein Passwort! ⚠️).
3. Dort **„Einstellungen laden …“** → Gerätenamen anpassen → **Weiter**.

> 🧭 **Was landet wo?** Persönliche Dateien kommen auf **alle** Geräte – auch zwischen Linux und
> Windows. Einstellungen (Shell, Git, Desktop …) nur auf Geräte mit **gleichem Betriebssystem**.
> Systemdateien und Paketlisten bleiben **beim jeweiligen Gerät** und lassen sich bei Bedarf über
> den Verlauf holen.

<a id="hintergrund"></a>

### 5️⃣ Hintergrund-Abgleich einschalten

1. Im Wizard auf der Seite *„Was möchtest du tun?“* unten auf **„Hintergrund-Abgleich …“**.
2. ✅ **Aktivieren**, ⏱️ **Abstand** (z. B. 15 min), 🤝 **Konfliktregel** und
   🚀 **„Beim Anmelden automatisch starten“** einstellen → **OK**.
3. Im Infobereich erscheint ein Symbol 🔄. Rechtsklick: *Jetzt abgleichen*, *Pausieren*,
   *Wizard öffnen*, *Beenden*.

> ⚠️ Voraussetzung: einmal im Wizard abgeglichen und das Passwort dauerhaft gespeichert.

> 🛡️ **Sicherheitsbremse:** Sollen im Hintergrund auf einmal sehr viele Dateien gelöscht werden
> (ab 25 und mehr als 20 % des Bestands), passiert nichts – du bekommst einen Hinweis und
> bestätigst das im Wizard. Fehlt ein ganzer Ordner (z. B. Laufwerk nicht eingehängt), gilt das
> nicht als Löschung.

<a id="verlauf"></a>

### 6️⃣ Im Verlauf zurückspringen

Datei versehentlich gelöscht oder überschrieben? Kein Problem. 🛟

1. Wizard → **Verlauf** wählen.
2. Mit **◀ Älter / Neuer ▶** die gewünschte Version suchen (Datum, Gerät, Änderungen
   `+neu ~geändert −gelöscht`).
3. Dann entweder:
   - 📄 **„Einzelne Dateien aus dieser Version holen“** → Kategorien und Dateien wählen → bei
     vorhandenen Dateien *überspringen*, *beide behalten* oder *überschreiben*.
   - ⏪ **„Speicher auf diese Version setzen“** → alle Geräte übernehmen diesen Stand beim nächsten
     Abgleich. Nichts geht verloren: Das wird als neue Version gespeichert, du kannst jederzeit
     wieder ⏩ vorspringen.

<a id="faq"></a>

### 💡 Häufige Fragen

<details>
<summary>🤝 Was passiert bei einem Konflikt?</summary>

Wurde eine Datei auf zwei Geräten verschieden geändert, gewinnt eine Fassung nach deiner Regel
(*neuere Änderung*, *dieses Gerät* oder *Speicher*). Die andere liegt als
`name (Konflikt laptop 2026-11-09 1430).ext` daneben – auf allen Geräten. Schau sie dir an und
lösche die überflüssige.

</details>

<details>
<summary>🗑️ Ich habe eine Datei gelöscht – ist sie weg?</summary>

Nein. Sie verschwindet beim nächsten Abgleich von den anderen Geräten, bleibt aber in allen
älteren Versionen erhalten. Über **Verlauf** holst du sie zurück.

</details>

<details>
<summary>🔒 „Der Speicher wird gerade von … abgeglichen“</summary>

Ein anderes Gerät gleicht gerade ab. Kurz warten und erneut versuchen – der Hintergrund-Abgleich
macht das nach 2 Minuten von selbst. Eine hängengebliebene Sperre wird nach 30 Minuten übernommen.

</details>

<details>
<summary>📂 Kann ich die Dateien direkt in Nextcloud ansehen?</summary>

Nein. Inhalte werden platzsparend nach Prüfsumme abgelegt (`Yaleno/yaleno/objects/…`) und sind
nur über den Wizard lesbar. Den Ordner **nicht** zusätzlich mit dem Nextcloud-Desktop-Client
synchronisieren – das übernimmt der Wizard.

</details>

<details>
<summary>🔑 Wo liegt mein Passwort?</summary>

Im Schlüsselbund des Systems (KWallet, GNOME-Schlüsselbund, Windows-Anmeldeinformationen).
Gibt es keinen, in der Einstellungsdatei – nur für dich lesbar. Haken bei „dauerhaft speichern“
entfernen, um es zu löschen.

</details>

<details>
<summary>⚠️ Sollte ich Browser und SSH-Schlüssel abgleichen?</summary>

Mit Bedacht. **Browser-Profile** können beschädigt werden, wenn der Browser auf zwei Geräten
gleichzeitig läuft – dann lieber die Sync-Funktion des Browsers nutzen. **SSH-Schlüssel** landen
auf allen Geräten mit gleichem Betriebssystem; nur mit einem vertrauenswürdigen Speicher.

</details>

<details>
<summary>🐧 <code>install.sh</code>: „Programmdatei 'yaleno-wizard' nicht gefunden“ / „No such file or directory“</summary>

`packaging/linux/install.sh` installiert die gebaute Programmdatei `dist/yaleno-wizard`. Die
entsteht erst durch PyInstaller – also zuerst bauen, dann installieren:

```bash
.venv/bin/pyinstaller --noconfirm yaleno_wizard.spec
sh packaging/linux/install.sh
```

Ältere Versionen des Skripts suchten nur im eigenen Ordner und brachen deshalb immer mit
`chmod: cannot access './yaleno-wizard': No such file or directory` ab – dann `git pull`.
Ohne Bauen geht notfalls `.venv/bin/python -m yaleno_wizard --install` (Eintrag hängt an der `.venv`).

</details>

<details>
<summary>🧭 Der Eintrag erscheint nicht im Startmenü</summary>

Prüfen, ob `~/.local/share/applications/yaleno-wizard.desktop` existiert. Manche Desktops lesen
das Menü erst nach Ab- und Anmelden neu ein. Liegt `~/.local/bin` nicht im `PATH`, funktioniert das
Startmenü trotzdem – nur im Terminal muss `~/.local/bin/yaleno-wizard` ausgeschrieben werden.

</details>

<details>
<summary>📜 Wo finde ich Protokolle?</summary>

`~/.local/state/yaleno-wizard/log` bzw. `%LOCALAPPDATA%\yaleno-wizard\Logs` – ein Log je Vorgang
im Wizard, `hintergrund.log` für den Hintergrund-Abgleich.

</details>

---

<a id="referenz"></a>

## 📖 Referenz

### 🔄 Wie abgeglichen wird

Für jede Datei vergleicht der Wizard drei Stände: **dieses Gerät**, **Speicher** und den Stand
beim **letzten Abgleich dieses Geräts** (gemerkt unter `~/.config/yaleno-wizard/sync/`).

| Situation | Ergebnis |
|---|---|
| ⬆️ nur hier geändert / neu | wird hochgeladen |
| ⬇️ nur im Speicher geändert / neu | wird auf dieses Gerät geholt |
| 🗑️ hier gelöscht | wird aus dem aktuellen Stand entfernt (bleibt im Verlauf) |
| 🗑️ auf anderem Gerät gelöscht, hier unverändert | wird hier gelöscht (bleibt im Verlauf) |
| ✏️ gelöscht auf einer Seite, geändert auf der anderen | die geänderte Datei bleibt |
| ⚡ auf beiden Seiten verschieden geändert | **Konflikt**: Gewinner nach Regel, die andere Fassung bleibt als `name (Konflikt …).ext` daneben und wird ebenfalls abgeglichen |

Abgewählte Kategorien und Dateien bleiben unberührt. Während eines Abgleichs ist der Speicher
gesperrt (`lock`).

**Welche Daten auf welchen Geräten landen:**

| Bereich | Inhalt | gilt für |
|---|---|---|
| 🌍 alle Geräte | persönliche Dateien (Dokumente, Bilder, …) | Linux **und** Windows |
| 🐧/🪟 gleiches Betriebssystem | Shell, Git, Editor, Desktop, Browser, SSH-Keys, App-Konfiguration | alle Linux- bzw. alle Windows-Geräte |
| 📍 nur dieses Gerät | Systemdateien (`/etc`), Befehlsausgaben (Paketlisten, dconf, Registry) | wird nur hochgeladen, nie automatisch geschrieben – bei Bedarf über *Verlauf* holen |

### 🗂️ Kategorien

| Kategorie | Linux | Windows |
|---|---|---|
| 📁 Persönliche Dateien *(auch OS-übergreifend)* | Dokumente, Bilder, Musik, Videos, Schreibtisch, Downloads (XDG) | dieselben Known Folders |
| 💲 Shell & Terminal | Bash, Zsh, Fish, Starship, tmux, Terminal-Emulatoren | PowerShell-Profile, Windows Terminal, Git-Bash |
| 🔑 SSH- & GPG-Schlüssel ⚠️ | `~/.ssh`, `~/.gnupg`, Schlüsselbund | `.ssh`, GnuPG |
| 🧑‍💻 Git & Entwicklung | Git, VS Code, (Neo)Vim, npm/cargo/pip-Konfig | Git, VS Code, (Neo)Vim |
| 🎨 Desktop-Umgebung | KDE Plasma, GNOME (`dconf dump`), GTK, Autostart, Schriften | Registry-Exporte (Systemsteuerung, Tastatur, Explorer, Umgebung), Schriften, Startmenü |
| 🌐 Browser & E-Mail ⚠️ | Firefox, Zen, LibreWolf, Floorp, Chromium, Chrome, Brave, Vivaldi, Thunderbird | Firefox, Zen, Chrome, Edge, Brave, Thunderbird |
| 📦 Installierte Programme | Paketlisten: pacman, AUR, apt, dnf, Flatpak, Snap | `winget export` |
| ⚙️ Systemkonfiguration | ausgewählte Dateien aus `/etc` | – |
| 🧩 Weitere Anwendungs-Konfiguration | Rest von `~/.config` | Rest von `AppData\Roaming` |

Caches, `node_modules`, Papierkorb, Lock-Dateien usw. werden automatisch ausgelassen. 🧹
Definiert sind die Kategorien in `src/yaleno_wizard/catalog/linux.py` und `windows.py`.

Pfade werden über Platzhalter wie `{DOCUMENTS}` übersetzt, sodass dieselben Dateien unter Linux
in `~/Dokumente` und unter Windows in `C:\Users\…\Documents` liegen.

### 💾 Ablage auf dem Speicher

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
per SHA-256 geprüft. ✔️

### 📄 Einstellungsdatei (YAML)

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

🔐 **Passwörter** (App-Passwort, Passphrase) werden dauerhaft gespeichert, sofern „dauerhaft
speichern“ angehakt ist:

- `password_store: keyring` (Standard) – im Schlüsselbund des Systems (KWallet / GNOME-Schlüsselbund
  über Secret Service, Windows-Anmeldeinformationsverwaltung). In der Datei steht dann kein Passwort.
- `password_store: file` – im Klartext in der YAML-Datei (Rechte `0600`). Wird automatisch verwendet,
  wenn kein Schlüsselbund verfügbar ist, und ist praktisch, um eine fertige Datei auf ein neues Gerät
  zu kopieren. Die Datei dann wie ein Passwort behandeln. ⚠️
- `password_store: none` – nichts speichern (dann ist kein Hintergrund-Abgleich möglich).

Steht in einer Datei ein `password:`, wird es verwendet – auch ohne `password_store`.

### ☁️ Nextcloud / WebDAV im Detail

- **Server:** die normale Nextcloud-Adresse, z. B. `https://cloud.example.org` (auch mit Unterpfad
  wie `https://example.org/nextcloud`). Der WebDAV-Pfad `/remote.php/dav/files/<benutzer-id>/` wird
  automatisch ermittelt – auch wenn du dich per E-Mail anmeldest.
- Andere WebDAV-Server: die vollständige WebDAV-Adresse eintragen.
- **Ordner** in deinen Dateien (Standard `Yaleno`) wird bei Bedarf angelegt.
- Nur HTTPS mit gültigem Zertifikat wird akzeptiert. 🔒

### 🌙 Hintergrund-Abgleich und Kommandozeile

```bash
yaleno-wizard                     # Wizard öffnen
yaleno-wizard --background        # Symbol im Infobereich (das trägt auch der Autostart ein)
yaleno-wizard --sync              # einmal abgleichen ohne Oberfläche, z. B. per cron/systemd-Timer
                                  # Exit-Code: 0 ok, 1 einzelne Dateien fehlgeschlagen, 2 Fehler
yaleno-wizard --config datei.yml  # andere Einstellungsdatei verwenden
yaleno-wizard --install           # 🧙 ins Startmenü eintragen (mit Logo)
yaleno-wizard --uninstall         # Eintrag und Programm entfernen
```

Es gelten die zuletzt im Wizard gewählten Kategorien und abgewählten Dateien
(`sync.categories` / `sync.exclude`). Autostart: Linux `~/.config/autostart/yaleno-wizard.desktop`,
Windows Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

### 📝 Bestand-Textdatei

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

---

<a id="entwicklung"></a>

## 🛠️ Entwicklung

Aufbau, Funktionsweise des Abgleichs, Entscheidungen und offene Punkte:
📚 [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md)  ·  📝 Änderungen: [CHANGELOG.md](CHANGELOG.md)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip ...
.venv/bin/python -m yaleno_wizard          # starten
.venv/bin/pytest -q                        # 🧪 Tests (inkl. echtem SFTP- und WebDAV-Testserver, GUI offscreen)
.venv/bin/pyinstaller yaleno_wizard.spec   # 📦 → dist/yaleno-wizard(.exe), mit Logo
.venv/bin/python scripts/make_icons.py     # 🎨 PNG/ICO neu erzeugen, nach Änderung an assets/yaleno.svg
```

**Installer bauen:**

- 🪟 Windows: nach PyInstaller `iscc /DAppVersion=0.1.0 packaging\windows\yaleno-wizard.iss`
  ([Inno Setup 6](https://jrsoftware.org/isinfo.php)) → `dist\yaleno-wizard-setup-0.1.0.exe`
- 🐧 Linux: nach PyInstaller `scripts/pack_linux.sh` → `dist/yaleno-wizard-0.1.0-linux-x86_64.tar.gz`
  (Ordner `yaleno-wizard-0.1.0/` mit `yaleno-wizard` + `install.sh`; der Workflow nutzt dasselbe
  Skript). Zum Testen geht auch direkt `sh packaging/linux/install.sh` – es nimmt dann
  `dist/yaleno-wizard`. Gefahrlos ausprobieren mit einem leeren Home-Ordner:
  `HOME=$(mktemp -d) sh packaging/linux/install.sh`

Die Binärdatei muss auf dem jeweiligen Betriebssystem gebaut werden. Der Workflow
`.github/workflows/build.yml` macht alles automatisch: bei manuellem Start als Artefakte, bei einem
Tag `v*` (z. B. `git tag v0.1.0 && git push --tags`) zusätzlich als **Release** mit Installern. 🤖
