# Dorfkern Betreiber-Handbuch

Installation, Rollout und Wartung einer Dorfkern-Instanz.
Zielgruppe: IT-Verantwortliche, die einen neuen Dorfladen
aufsetzen oder eine bestehende Instanz warten.

---

## 1. Architektur in zwei Sätzen

Dorfkern besteht aus **vier Flask-Apps** plus einem **HACCP-Poller-Daemon**,
die alle auf dieselbe **MariaDB/MySQL-Datenbank** (CAO-WaWi-Schema + Dorfkern-
eigene `DORFKERN_*` / `XT_*`-Tabellen) zugreifen. Ein Laden hat **einen Admin-
Host** (Orga + Admin, optional Poller) und **mehrere Terminal-Hosts**
(Kasse / Kiosk / Orga-Außenstelle).

| App | Port | Hardware-Typ |
|-----|------|--------------|
| Admin | 5004 | Server / Büro-PC |
| Orga | 5003 | Server / Büro-PC |
| Kasse | 5002 | Kassen-Terminal (Touch + Bondrucker + TSE) |
| Kiosk | 5001 | Kundenterminal (reiner Touch) |
| HACCP-Poller | – | Daemon auf Admin-Host (braucht TFA_API_KEY) |

---

## 2. Voraussetzungen

### 2.1 Admin-Host

- Linux (Debian/Ubuntu) oder macOS.
- Python 3.11+.
- Zugriff auf die CAO-MariaDB (Host, Port, Name, User, Passwort).
- Optional: TFA.me-API-Key für HACCP.
- Offene Ports: `5001–5004` im LAN erreichbar.

### 2.2 Terminal-Host

- Linux/macOS mit Touchscreen (Kiosk) oder Tastatur+Maus+Touch (Kasse/Orga).
- Python 3.11+.
- Netzzugriff auf Admin-Host + MariaDB.
- Kasse zusätzlich: Bondrucker (ESC/POS), Swissbit-USB-TSE.

### 2.3 Datenbank

Empfohlen: MariaDB 10.6+ oder MySQL 8+.
Dorfkern erkennt automatisch, ob die angegebene DB bereits ein
**CAO-WaWi-Schema** enthält (über Tabelle `MITARBEITER`) und legt nur
die **fehlenden `DORFKERN_*` / `XT_*`-Tabellen** an. Bestehende CAO-
Installationen werden nicht umgebaut.

---

## 3. Erstinstallation (Admin-Host)

### Schnellster Weg — Einzeiler-Bootstrap

Auf einer frischen Maschine genügt ein Befehl:

```bash
# Produktivbetrieb (Repo → /opt/dorfkern, System-Dienst):
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"

# Entwicklung / als normaler User (Repo → ~/dorfkern):
bash -c "$(curl -fsSL https://raw.githubusercontent.com/molymp/cao-xt/master/bootstrap.sh)"
```

`bootstrap.sh` prüft git + python3, klont an die passende Stelle und
startet `install.sh`. Wer das Repo schon hat: direkt `./install.sh`.

### Installer-Dialog (`install.sh` → `installer/install.py`)

`install.sh` legt ein `venv` an, installiert alle App-Requirements
und startet die interaktive Routine. Phasen:

0. **Installations-Typ** –
   *1) Ad-hoc* (Popen, stirbt mit Login-Session — Dev),
   *2) Dienst pro Benutzer* (`systemctl --user` + Lingering),
   *3) Dienst systemweit* (System-Units, Service-User `dorfkern`,
   `/opt/dorfkern` — Standard für Produktivbetrieb).
   Zusätzlich abgefragt: **Instanz-Name** (leer = Default) und
   **Port-Base** (Default 5000 → Apps 5001-5004). Mehrere Instanzen
   (`prod`/`dev`) laufen so parallel auf einem Host.
1. **Datenbank-Konfiguration** – Host/Port/Name/User/Passwort,
   Verbindungstest.
2. **DB-Init** – erkennt automatisch CAO vs. leer; legt fehlende
   `DORFKERN_*` / `XT_*`-Tabellen an (idempotent).
3. **App-Auswahl** – Admin immer aktiv. Orga/Kasse/Kiosk nach Wunsch.
   HACCP-Poller nur wenn `TFA_API_KEY` gesetzt.
4. **Installieren + Starten** – je nach Typ Popen bzw. systemd-Units
   schreiben, Service-User/Verzeichnisse anlegen, Target enablen.
5. **Kiosk-Terminal (optional, nur Typ 3)** – siehe Kapitel 11.
6. **Abschlussbericht** – Adressen, Log-Pfade, Steuerbefehle.

> **Hinweis Python**: Die Apps brauchen Python ≥ 3.10. Auf Debian 11 /
> Raspberry Pi OS ist System-Python noch 3.9. `install.sh` sucht
> automatisch nach `python3.11`/`3.10`-Binaries. Bei pyenv-Python (nicht
> im sudo-PATH): `sudo PYTHON=/home/<user>/.pyenv/versions/3.11.x/bin/python3 ./install.sh`.
> Falls `cryptography` am Rust-Build scheitert (alte Pi):
> `.venv/bin/pip3 install "cryptography==3.3.2"`, dann erneut.

Den `produktion`/`training`-Schalter gibt es **nicht mehr** — er war
toter Code. Trainingsbetrieb wird pro Terminal über die DB
(`TERMINAL.TRAININGS_MODUS`) gesteuert, nicht über die Installation.

Ergebnis: `caoxt/caoxt.ini` enthält Bootstrap-Konfig (DB-Verbindung,
`[Installation] instance_name`/`base_port`/`aktive_apps`). Alles andere
liegt in `DORFKERN_KONFIG`.

---

## 4. Rollout auf Terminal-Hosts

Für Kassen-, Kiosk- und Orga-Terminals (nicht interaktiv):

```bash
git clone <repo-url> cao-xt
cd cao-xt
./install.sh --non-interactive \
             --role terminal \
             --terminal-typ KASSE   # oder KIOSK / ORGA
```

Dabei:
- Liest DB-Zugangsdaten aus Umgebungsvariablen
  (`XT_DB_HOST`, `XT_DB_PORT`, `XT_DB_NAME`, `XT_DB_USER`, `XT_DB_PASSWORD`)
  oder einer bestehenden `caoxt/caoxt.ini`.
- **Überspringt den DB-Init** (ist Sache des Admin-Hosts).
- Startet **nur eine** App (`KASSE → kasse-app`, `KIOSK → kiosk-app`,
  `ORGA → orga-app`).
- Die gestartete App **registriert sich selbst** in `TERMINAL` beim ersten
  Start (Hostname + MAC + IP + Typ). Im Admin-UI (📟 Registry) kann man
  Bezeichnung und Aktiv-Flag nachpflegen.

### 4.1 Massen-Rollout

Script-Beispiel für viele gleichartige Terminals:

```bash
# auf jedem Kiosk-Host:
export XT_DB_HOST=192.168.1.10 XT_DB_PORT=3306 \
       XT_DB_NAME=cao XT_DB_USER=dorfkern XT_DB_PASSWORD=...
git clone <repo-url> cao-xt
cd cao-xt
./install.sh --non-interactive --role terminal --terminal-typ KIOSK
```

Alle Kiosks tauchen danach in der Admin-App unter 📟 Registry auf,
mit Hostname und MAC. Umbenennen („Kiosk Eingang", „Kiosk Bäckerei")
dort.

---

## 5. Service-Control (`dorfkern-ctl`)

Wrapper-Script im Repo-Root, steuert alle Apps auf dem lokalen Host:

```bash
./dorfkern-ctl status                 # Status aller Apps
./dorfkern-ctl start                  # alle konfigurierten Apps
./dorfkern-ctl start kasse            # nur Kasse
./dorfkern-ctl restart                # alle neu starten
./dorfkern-ctl stop kiosk             # Kiosk stoppen
```

`dorfkern-ctl` erkennt den Modus automatisch (`is_systemd_managed()`):

- **Ad-hoc**: PIDs in `/tmp/caoxt-pids.json`, Logs `/tmp/dorfkern-<app>.log`.
- **systemd (User/System)**: delegiert an `systemctl [--user] …`, Logs
  via `journalctl [--user] -u dorfkern[-<inst>]-<app>` bzw.
  `/var/log/dorfkern[-<inst>]/<app>.log`.

systemd ist im Produktivbetrieb der **Standard** (Installer Typ 3, nicht
mehr „optional"): `dorfkern.target` ist boot-persistent (`systemctl
enable`), Apps starten ohne Login und nach Crash neu
(`Restart=on-failure`). Details: `installer/systemd/README.md`.

---

## 6. Updates

Der Update-Mechanismus ist **commit-basiert**: ein Update gilt als
verfügbar, sobald `origin/<aktueller-branch>` Commits enthält, die der
lokale `HEAD` noch nicht hat. Eine separate Versions-Pflege (semver)
ist dafür nicht erforderlich – `VERSION.json` darf existieren und
liefert dann zusätzliche Anzeige-/Impact-Hints, ist aber für die
Erkennung selbst irrelevant.

### Empfohlener Weg: aus der Admin-App

**Admin → System → Updates** (Sidebar oder direkt `/system/updates`).
Klick auf *„🔍 Auf Updates prüfen"*:

* macht ein `git fetch origin <branch>`
* zeigt lokalen Commit-Hash, Remote-Commit-Hash und die Liste der
  neuen Commits (Subjects)
* falls neue Commits da sind, erscheint *„⬆️ Update jetzt installieren"*

Beim Install:

1. Apps werden gestoppt
2. `caoxt/caoxt.ini` per `git update-index --skip-worktree` lokal
   geschützt (idempotent)
3. `git pull --ff-only` 
4. `caoxt/caoxt.ini` aus `.example` bootstrappen, falls nicht vorhanden
5. Optional `pip install` (wenn `VERSION.json.impact.requirements_changed`)
6. Apps neu starten
7. Health-Check via TCP-Connect auf alle vier Ports

Fortschritt landet in `/tmp/caoxt-update.log`.

### Konsolen-Fallback

```bash
./install.sh --update        # geführter Lauf mit Bestätigung
./install.sh --check-update  # nur prüfen
```

Beide Wege rufen denselben Code-Pfad (`installer/updater.py`).

### Rollback

`installer/updater.py` merkt sich vor jedem Pull den Commit-Hash und
ruft bei Fehlschlag `git reset --hard <vorher>`. Manuell ist der
Befehl `git reflog` + `git reset --hard <hash>` der zuverlässigste
Weg.

### Was bleibt automatisch erhalten

* **Datenbank-Inhalt komplett** (DORFKERN_KONFIG, alle Stammdaten,
  Bewegungsdaten, TSE-Geräte, Mitarbeiter-RFID-Tags, Schichtplan,
  Kassen-Bons, Kassenbuch). Ein git-pull fasst die DB nicht an.
* `caoxt/caoxt.ini` (lokal, in `.gitignore`)
* `*-app/app/config_local.py` (lokal, in `.gitignore`)
* `/tmp/caoxt-*.log`

DB-Migrationen (z.B. neue Tabellen) laufen beim **Admin-App-Start**
automatisch. Ein Update zieht also auch ohne expliziten
Migrations-Trigger alles mit.

---

## 7. Konfiguration

**Einziger Speicherort für dauerhafte Einstellungen: Admin-App →
🔧 Konfiguration** (Tabelle `DORFKERN_KONFIG`).

`caoxt/caoxt.ini` wird **nur noch** verwendet für:
- DB-Verbindung (Host/Port/Name/User/Passwort)
- Master-Key für SECRET-Verschlüsselung
- Umgebung (produktion/training)
- Liste der aktiven Apps (wird vom Installer geschrieben)

Alles andere (SMTP, HACCP-API-Key, Google-Sheet-IDs, Integrations-
Tokens, …) → Admin-UI.

**Terminal-Konfiguration** (Drucker, Kassenlade, EC-Terminal,
DATEV-Konten, Trainings-Modus) liegt zentral in der Admin-App unter
`💻 Terminals → ✏️ Bearbeiten`. Drucker-Test wird ebenfalls von dort
ausgelöst. Die Kasse-App selbst zeigt unter `/admin/` nur noch
KassenSichV-spezifische Themen (TSE-Geräte, DSFinV-K-Export,
Tagesabschluss, Trainings-Modus als Notausstieg).

**Wichtig:** `caoxt.ini` enthält DB-Zugangsdaten und ist seit Phase 7b
**nicht mehr in Git getrackt** (`/caoxt/caoxt.ini` in `.gitignore`).
Repo-Vorlage: `caoxt/caoxt.ini.example` – wird beim ersten App-Start
automatisch nach `caoxt.ini` kopiert, falls keine lokale Datei
existiert. Datei-Rechte **0600** setzen, nicht in Backups im Klartext.

### 7.1 RFID-Tags für Mitarbeiter

Mitarbeitende können ihren bereits vorhandenen Alarm-RFID-Tag als
Login-Alternative zur Mitarbeiterkarte nutzen. Pflege über
**Orga → 🪪 Personal → Mitarbeiter → Feld „RFID-Tag"** (direkt unter
dem CAO-Login).

- DB-Tabelle: `XT_MITARBEITER_RFID` (1:1 zu `MITARBEITER.MA_ID`).
- Format: 4–64 Zeichen aus `A–Z`, `0–9`, `:`, `-`. Eingabe wird
  uppercase-normalisiert; Kollisionen werden abgewiesen.
- Wirkt automatisch in **allen Karten-Scan-Endpoints** (App-Login der
  4 Apps, Stempeluhr im Kiosk) – über den gemeinsamen
  `mitarbeiter_login_karte`-Pfad mit RFID-Fallback.
- Die CAO-`MITARBEITER`-Tabelle wird **nicht** verändert (CAO-Kompat).

---

## 8. Inbetriebnahme-Checkliste

Nach Erstinstallation auf dem Admin-Host:

- [ ] Login als `Administratoren` in Admin-App funktioniert.
- [ ] 🔧 Konfiguration → SMTP-Werte eingetragen, Test-Mail
      aus Orga-App geht durch.
- [ ] 📟 Registry → Admin-Host ist eingetragen.
- [ ] 🎚️ App-Aktivierungen → gewünschte Apps auf `AKTIV=1`.
- [ ] Für jede CAO-Rolle (`Mitarbeiter`, `Ladenleitung`, …) →
      `DORFKERN_ROLLE_PERMISSION`-Einträge gesetzt.
- [ ] Je Terminal: Hostname/MAC in Registry sichtbar, Bezeichnung
      gepflegt, LETZTER_KONTAKT aktuell.
- [ ] HACCP: TFA_API_KEY gesetzt, Poller läuft
      (`./dorfkern-ctl status`), erste Messwerte in Orga-App.
- [ ] Kasse: TSE angesteckt, Test-Bon druckt mit Signatur.
- [ ] Backup-Job für MariaDB eingerichtet (nicht Teil von Dorfkern).

---

## 9. Troubleshooting

### 9.1 App startet nicht

```bash
./dorfkern-ctl status
tail -f /tmp/caoxt-<app>.log
```

Typische Ursachen: Port belegt, DB nicht erreichbar, `caoxt.ini`
fehlt / kaputt, venv-Python fehlt (`./install.sh` nochmal).

### 9.2 Terminal erscheint nicht in der Registry

- App wirklich gestartet? (`./dorfkern-ctl status` auf dem Terminal)
- DB-Host aus Terminal-Sicht erreichbar?
  (`nc -zv <admin-host> 3306`)
- Log auf dem Terminal: `grep selbst_registrieren /tmp/caoxt-*.log`.

### 9.3 Rechte-Migration von alter Installation

Bestehende CAO-Rollen werden automatisch aus `BENUTZERRECHTE` gelesen.
Dorfkern legt beim ersten Start der Admin-App den **Permission-Objekt-
Katalog** an; die **Rollen-Mapping-Einträge** (`DORFKERN_ROLLE_PERMISSION`)
müssen per SQL / Admin-UI (ab v2.1) pro Laden gesetzt werden —
es gibt bewusst kein Default-Mapping, um Fail-closed-Semantik zu
erhalten.

### 9.4 DB-Wechsel: Benutzer hängen fest / alles ausgegraut

Nach einem DB-Wechsel (Admin → Datenbank) sind alle Sessions an die
**alte** DB gebunden. Seit dem `db_sig`-Mechanismus werden sie beim
nächsten Klick automatisch ungültig → saubere Login-Seite. Bei einer
Box mit einer Pre-`db_sig`-Session hilft einmaliges Logout bzw. ein
App-Restart; danach greift der Auto-Logout zuverlässig.

### 9.5 Weiterführend

- `docs/handbuch-admin.md` — UI-/Rechte-Details.
- `installer/systemd/README.md` — Service-Modi, Multi-Instanz, Kiosk.
- `RELEASE_DORFKERN_V2.md` — technische Release-Entscheidungen.
- Log-Pfade: System-Mode `/var/log/dorfkern[-<inst>]/`, sonst
  `/tmp/dorfkern-*.log`; Updater `journalctl`/`/tmp/dorfkern-update.log`.

---

## 10. Updates & Versionierung

Version steht in `VERSION.json` (Repo-Root) und in `caoxt.ini [Version]`.
Dorfkern v2 = **2.0.0**. Breaking Changes werden in `CHANGELOG.md`
unter der jeweiligen Version dokumentiert, mit Migrationshinweisen.

---

## 11. Kiosk-Terminal & Wartungs-Modus

### 11.1 Kiosk-Setup (Installer-Phase 5)

Nur bei Installations-Typ 3 (System-Dienst). Macht die Box zum
Touch-Terminal: beim Boot Auto-Login als GUI-User (Default: `SUDO_USER`
bzw. `XT_KIOSK_USER`, **nicht** der `dorfkern`-Service-User) in eine
Vollbild-Chromium-Session auf die Kiosk-App.

**Additiv**: bestehende LightDM-Autologin-Konfiguration eines anderen
Users wird nicht überschrieben, ein bereits aktiver anderer
Display-Manager (gdm/sddm) nicht umgestellt — in dem Fall kommt eine
klare Meldung mit dem manuellen Umstell-Befehl.

Mit installiert werden:
- `lightdm` + `lightdm-gtk-greeter` + `accountsservice` + `chromium`
  + `openbox` (idempotent via apt)
- `/usr/local/bin/dorfkern-kiosk-session` — Chromium mit eigenem Profil
  (`~/.config/dorfkern-chromium-kiosk`, getrennt vom normalen Browser),
  dynamischer Display-Auflösung, Vollbild
- Chromium-Enterprise-Policy `/etc/chromium/policies/managed/dorfkern-kiosk.json`
  — **kein** Passwort-Manager / Autofill / Translate-Popup
- `/usr/local/bin/dorfkern-maintenance-mode` (siehe 11.2)
- sudoers-Snippets für Shutdown/Reboot + Maintenance

### 11.2 Wartungs-Modus

Wechsel zwischen Kiosk und einem normalen Wartungs-Desktop — **ohne
Reboot**, drei Wege:

1. **Admin-App**: Dashboard → Widget „🛠️ Wartungs-Modus" (eigenes
   Permission-Objekt `admin.system.maintenance`).
2. **Desktop-Icon** „Zurück zum Kiosk" — liegt im Wartungs-Desktop,
   schaltet per Doppelklick zurück (passwortfrei via sudoers).
3. **SSH/Konsole**: `sudo dorfkern-maintenance-mode [--kiosk|--maintenance|--greeter|--status]`

- `--maintenance` (Default): Auto-Login des GUI-Users in LXDE-Desktop,
  **kein** Login-Prompt (Touch-freundlich).
- `--kiosk`: zurück zu Vollbild-Chromium.
- `--greeter`: klassischer LightDM-Login (User/Session/Passwort wählbar).

Mechanik: tauscht `/etc/lightdm/lightdm.conf.d/50-dorfkern-kiosk.conf`
um und macht `systemctl restart lightdm`. Der Admin-Browser bleibt
unberührt (wirkt nur am physischen Display).

### 11.3 Feierabend-Knopf

Admin-App → Dashboard-Widget „⚡ Ein/Aus" bzw. `/system/power`
(Permission `admin.system.power`): Herunterfahren / Neu starten direkt
aus dem Browser. Backend ruft `sudo -n /sbin/shutdown` über das
sudoers-Snippet.
