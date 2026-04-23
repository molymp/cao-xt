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

```bash
git clone <repo-url> cao-xt
cd cao-xt
./install.sh
```

`install.sh` legt ein `venv` an, installiert alle App-Requirements
und startet dann die interaktive Installations-Routine
(`installer/install.py`). Phasen:

1. **Datenbank-Konfiguration** – Host/Port/Name/User/Passwort.
   Verbindung wird getestet; bei Erfolg → weiter.
2. **DB-Init** – erkennt automatisch CAO vs. leer; legt fehlende
   `DORFKERN_*` / `XT_*`-Tabellen an (idempotent).
3. **Umgebung** – `produktion` | `training`. Training = keine echten
   TSE-Signierungen, Kennzeichnung im Bon.
4. **App-Auswahl** – Admin immer aktiv. Orga/Kasse/Kiosk nach Wunsch.
   HACCP-Poller nur wenn `TFA_API_KEY` gesetzt.
5. **Start + Bericht** – alle Apps werden gestartet, Health-Check,
   Abschlussbericht mit URLs und Log-Pfaden.

Ergebnis: `caoxt/caoxt.ini` enthält Bootstrap-Konfig (nur DB-Verbindung
+ Master-Key + Umgebung + aktive Apps). Alles andere liegt in
`DORFKERN_KONFIG`.

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

PIDs in `/tmp/caoxt-pids.json`, Logs in `/tmp/caoxt-<app>.log`.

Für systemd-Autostart: siehe `installer/systemd/` (optional).

---

## 6. Updates

```bash
./install.sh --update        # git fetch + reset --hard + restart
./install.sh --check-update  # nur prüfen, nichts ändern
```

Die Verwaltungs-App hat dafür auch eine geführte UI unter
**System → Updates** mit Impact-Anzeige (DB-Migration, Breaking Changes,
Commit-Liste).

Rollback: `installer/updater.py` speichert vor jedem Update den
aktuellen Commit-Hash; `install.sh --rollback` stellt ihn wieder her.

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

**Wichtig:** `caoxt.ini` enthält DB-Zugangsdaten. Datei-Rechte **0600**,
nicht in Versionskontrolle einchecken, nicht in Backups im Klartext.

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

### 9.4 Weiterführend

- `docs/handbuch-admin.md` — UI-/Rechte-Details.
- `RELEASE_DORFKERN_V2.md` — technische Release-Entscheidungen.
- Log-Pfade: alle `/tmp/caoxt-*.log`.

---

## 10. Updates & Versionierung

Version steht in `VERSION.json` (Repo-Root) und in `caoxt.ini [Version]`.
Dorfkern v2 = **2.0.0**. Breaking Changes werden in `CHANGELOG.md`
unter der jeweiligen Version dokumentiert, mit Migrationshinweisen.
