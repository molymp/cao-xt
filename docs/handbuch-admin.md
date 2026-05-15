# Dorfkern Admin-Handbuch

Für die tägliche Arbeit in der **Admin-App** (⚙️).
Zielgruppe: Admins eines Dorfladens (Technik-Verantwortliche,
Geschäftsführung).

---

## 1. Überblick

Die Admin-App ist das zentrale Konfigurations- und Steuerungs-Tool
von Dorfkern. Alle nicht-TSE-relevanten Einstellungen laufen hier
zusammen.

Öffnen über:
- App-Switcher (⚙️ Admin) aus einer beliebigen Dorfkern-App,
- direkt per Browser: `http://<admin-host>:5004`.

Login: Mitarbeiter-Login (Kartenscan oder PIN) mit ausreichender
CAO-Rolle. Wer sich als Admin einloggen darf, steht in der CAO-Tabelle
`BENUTZERRECHTE` (Gruppe `Administratoren` → Vollzugriff).

---

## 2. Dorfkern-Menü

Im linken Seitenmenü unter „Dorfkern":

### 2.1 🔧 Konfiguration — `/dorfkern/konfig`

Zentrale Key-Value-Tabelle **`DORFKERN_KONFIG`**. Ersetzt schrittweise
`caoxt.ini` (außer DB-Verbindung + Master-Key).

- **Filter** nach Kategorie (DB / EMAIL / HACCP / …).
- **Neuer Eintrag** → Schluessel, Wert, Typ
  (`STRING`|`INT`|`BOOL`|`JSON`|`SECRET`), Kategorie, Beschreibung.
- **SECRET-Werte** sind in der Liste maskiert. Bearbeiten leert das
  Wert-Feld; leer lassen = bestehender Wert bleibt unverändert.

Typen-Spielregeln:
- `INT` → Konvertierung auf `int`; ungültig → Wert wird ignoriert
  (Log-Eintrag).
- `BOOL` → `true/false/1/0/yes/no/ja/nein`.
- `JSON` → beliebige JSON-Struktur, wird beim Lesen deserialisiert.

Beim **ersten Start** der Admin-App werden die Werte aus `caoxt.ini`
**einmalig** per `INSERT IGNORE` übernommen. Spätere Admin-UI-
Änderungen überschreiben die ini-Werte nicht mehr — die DB ist
Wahrheit.

### 2.2 📟 Registry — `/dorfkern/terminals`

Terminals = physische Geräte (Kassen, Kiosk, Admin-Host, Orga-Host).

- **„Aktuellen Host übernehmen"** liest Hostname/MAC des aktuell
  aufgerufenen Admin-Hosts und füllt das Anlage-Formular vor.
- **MAC-Adresse** wird MAC-first zur Erkennung genutzt; Fallback =
  Hostname.
- **Typ**: `KASSE` | `KIOSK` | `ADMIN` | `ORGA`.
- **LETZTER_KONTAKT** wird von Terminal-Apps beim Start automatisch
  aktualisiert (Phase 9: Selbstregistrierung).

Wenn eine Terminal-App startet und keinen passenden Eintrag findet,
legt sie sich **selbst an**. In der Registry kann man Bezeichnung,
Aktiv-Flag, MAC und IP nachträglich pflegen.

### 2.3 🎚️ App-Aktivierungen — `/dorfkern/aktivierungen`

Feature-Gating für den App-Switcher.

- Jede App (KIOSK/KASSE/ORGA/ADMIN) kann `AKTIV=0` gesetzt werden →
  im Switcher ausgegraut (nicht anklickbar).
- **ADMIN ist geschützt** — kann nicht deaktiviert werden (Schutz
  vor Selbst-Aussperrung).
- Optional: `LIZENZ_BIS` als `YYYY-MM-DD`. Nach Ablauf wird die App
  automatisch ausgeblendet.
- TTL-Cache ist 30 Sekunden — Änderungen wirken unmittelbar.

---

## 2a. 💻 Terminal-Konfiguration — `/terminals`

**Seit Phase 7c** zentral hier gepflegt (vorher in der Kasse-App).

- **Übersichtstabelle:** Nummer · Bezeichnung · Drucker-IP · Modus
  (`Live`/`Training`) · Bearbeiten-Knopf.
- **Detail-Seite `/terminals/<nr>`** mit allen Nicht-TSE-Feldern:
  - Allgemein (Bezeichnung)
  - Bon-Kopf (Firma-Name + Zusatz, Override für `FIRMA.NAME1`)
  - Bondrucker (IP / Port, Kassenlade Pin 2/5, Sofort-Drucken,
    Schublade automatisch öffnen, QR-Code auf Bon)
    + **Drucker-Test**-Knopf: sendet ESC/POS-Testseite direkt aus
    der Admin-App an `DRUCKER_IP:DRUCKER_PORT`.
  - Trainings-/Demo-Modus (TSE-Signierung deaktiviert; Bons als
    `TRAININGSBON` gedruckt — nicht steuerlich relevant).
  - EC-Terminal (manuell oder ZVT-Vollintegration; Terminal-IP/Port,
    ZVT-Passwort, Tagesabschluss-Modus).
  - DATEV-Konten (Bank, Nebenkasse, Manko-/Mehrbetragskonto).
- API: `GET /api/terminals/<nr>` (Lesen),
  `PUT /api/terminals/<nr>` (Whitelist-Partial-Update),
  `POST /api/terminals/<nr>/drucker/test` (ESC/POS-Test).
- TSE-Felder bleiben außen vor — die werden in `/tse` verwaltet.

In der Kasse-App selbst zeigt `/admin/` jetzt nur noch
KassenSichV-relevante Aktionen (TSE-Geräte, DSFinV-K-Export,
Tagesabschlüsse) und einen Hinweis-Banner mit Link auf die zentrale
Terminal-Detail-Seite. `/admin/terminal` (GET) leitet automatisch
auf die Admin-URL um, `POST` bleibt als Fallback funktional.

---

## 2b. 🪪 Mitarbeiter-RFID — Pflege in Orga

Mitarbeitende können einen RFID-Tag (z.B. von der Alarmanlage) als
Login-Alternative zur Mitarbeiterkarte hinterlegen. Pflege:
**Orga → Personal → Mitarbeiter → Feld „RFID-Tag"** (direkt unter
dem CAO-Login).

- DB-Tabelle: `XT_MITARBEITER_RFID` (`MA_ID PK`, `RFID_TAG VARCHAR(64)
  UNIQUE`, `GEAENDERT_AM`, `GEAENDERT_VON_MA_ID`).
- Format: 4–64 Zeichen aus `A-Z`, `0-9`, `:`, `-`. Auto-Uppercase.
- Eindeutigkeit: ein Tag pro Person; doppelte Eingabe wird abgewiesen.
- Wirkt automatisch in **allen Karten-Scan-Endpoints**: App-Login
  (alle 4 Apps) + Stempeluhr (Kiosk) — über
  `common.auth.mitarbeiter_login_karte`, der nach KARTEN-Lookup auf
  `common.rfid.finde_ma_per_rfid` zurückfällt.
- CAO-Tabellen werden nicht verändert; CAO-Updates bleiben unkritisch.

---

## 3. Rechtemodell (Dorfkern v2)

### 3.1 Rollen

Rollen kommen aus der CAO-Tabelle `BENUTZERRECHTE`. Standard-Rollen:

| Rolle | Bedeutung |
|-------|-----------|
| `Administratoren` | Vollzugriff (implizit, kein Eintrag in Permission-Tabelle nötig) |
| `Geschäftsführung` | meist Voll-Lesezugriff auf Orga + Kasse |
| `Ladenleitung` | Schichtplanung, Bestellverwaltung |
| `Mitarbeiter` | nur, was er braucht (Kiosk, Kasse-Basis, Stempeluhr) |

Wer welcher Rolle angehört, wird in CAO gepflegt (Tabelle
`BENUTZERRECHTE`, Spalte `GRUPPEN_ID`).

### 3.2 Permission-Objekte

In `DORFKERN_PERMISSION_OBJEKT` (Admin-App legt beim Start
Standard-Katalog an):

| Objekt-Key | App | Unterscheidung |
|------------|-----|----------------|
| `kiosk.zugriff` | KIOSK | – |
| `kiosk.backwaren` | KIOSK | – |
| `kiosk.bestellverwaltung` | KIOSK | – |
| `kiosk.mittagstisch` | KIOSK | – |
| `kiosk.stempeluhr` | KIOSK | – |
| `kasse.zugriff` | KASSE | – |
| `kasse.storno` | KASSE | – |
| `kasse.einstellungen` | KASSE | – |
| `orga.zugriff` | ORGA | – |
| `orga.schichtplan` | ORGA | **LESE_PFLEGE** |

`LESE_PFLEGE` bedeutet: eine Rolle kann für ein Objekt entweder
`LESEN`, `PFLEGEN` oder `BEIDES` bekommen. Strikt: `PFLEGEN` deckt
**nicht** `LESEN` mit ab — dafür gibt es `BEIDES`.

### 3.3 Zuordnung Rolle → Recht

In `DORFKERN_ROLLE_PERMISSION`. Beispiele:

| Rolle | Objekt | Recht |
|-------|--------|-------|
| Ladenleitung | `orga.schichtplan` | `BEIDES` |
| Mitarbeiter | `orga.schichtplan` | `LESEN` |
| Mitarbeiter | `kiosk.backwaren` | `BEIDES` |

**Fail-closed:** Wer keinen Eintrag hat, sieht die Funktion **nicht**.
Admin sieht immer alles, ohne dass ein Eintrag nötig ist.

### 3.4 Prüfung im Code

```python
from common import permission
if permission.hat_recht(ma_id, 'kiosk.backwaren'):
    ...
if permission.hat_recht(ma_id, 'orga.schichtplan', recht='PFLEGEN'):
    ...
```

Bei DB-Fehler / unbekannter Rolle / nicht-existentem Objekt → `False`.

---

## 3a. System & Betrieb (Dashboard-Widgets)

Die folgenden Funktionen sind nur sichtbar, wenn die jeweilige
Berechtigung vorhanden ist (Administratoren implizit). Sie liegen auf
dem **Dashboard** (Startseite) und unter **System** im Seitenmenü.

### 3a.1 ⚡ Ein/Aus — `/system/power`

Permission `admin.system.power`. Zwei Buttons:
- **Herunterfahren** — fährt die Box sofort herunter (Feierabend-Knopf).
- **Neu starten** — voller OS-Reboot (z. B. nach Kernel-Update).

Vor dem Auslösen kommt ein Bestätigungs-Dialog mit Checkliste
(keine offenen Kasse-Vorgänge, Tagesabschluss gemacht). Technisch:
`sudo -n /sbin/shutdown` über ein vom Installer angelegtes
sudoers-Snippet.

Davon zu unterscheiden: **System → Updates → „Alle Apps neu starten"**
— startet nur die Dorfkern-Apps neu (kein OS-Reboot), nötig wenn der
Working-Tree aktueller ist als die laufenden Prozesse.

### 3a.2 🛠️ Wartungs-Modus — Dashboard-Widget

Permission `admin.system.maintenance` (eigenes Objekt — wer „Ein/Aus"
darf, darf nicht automatisch auch Wartung). Nur relevant auf
Kiosk-Terminals (System-Dienst + Kiosk-Setup).

- **Wartungs-Modus aktivieren** — die Box bootet/loggt automatisch in
  einen normalen LXDE-Desktop statt in den Vollbild-Kiosk (kein
  Login-Prompt am Display). Auf dem Desktop liegt ein Icon
  „Zurück zum Kiosk".
- **Zurück zum Kiosk** — schaltet wieder auf Vollbild-Chromium.

Das Widget zeigt den aktuellen Modus (KIOSK / WARTUNG / GREETER).
Wirkt nur am **physischen Display** der Box; der Admin-Browser bleibt
verbunden. Alternativ am Gerät: Desktop-Icon, oder per SSH
`sudo dorfkern-maintenance-mode …`.

### 3a.3 🗄️ Datenbank-Wechsel — `/db-config`

Permission `admin.system.db_config`. Zwei-Stufen-Flow:

1. **Eingaben prüfen** (`probe`) — testet die neuen Zugangsdaten und
   erkennt den DB-Typ (CAO / leer / unbekannt). Schreibt **nichts**.
2. **Speichern** — schreibt `caoxt.ini`, führt bei Bedarf die
   DB-Initialisierung aus (bei leerer DB nur mit explizit gesetzter
   Checkbox), und startet auf Wunsch **alle Apps** neu (Default an —
   sonst sehen orga/kasse/kiosk weiter die alte DB).

> ⚠ **Nach einem DB-Wechsel werden alle Benutzer automatisch
> abgemeldet** (Sessions sind an die DB gebunden, `db_sig`). Du landest
> auf der Login-Seite und meldest dich mit einem Konto der **neuen** DB
> an. Das ist gewollt — verhindert den Zustand „eingeloggt, aber alles
> ausgegraut".

### 3a.4 🎛️ App-Steuerung — `/system/apps`

Status + Start/Stop/Restart der einzelnen Apps. Im systemd-Modus über
`systemctl` (Status read-only ohne sudo; Steuerbefehle über
sudoers-Snippet). Zeigt PIDs/Ports und ob die jeweilige App läuft.

---

## 4. Troubleshooting

### 4.1 Terminal wird nicht erkannt

- In `📟 Registry` prüfen: steht Hostname & MAC des Geräts drin?
- Wenn VMs/Container: identische MAC → Hostname-Fallback greift.
- `LETZTER_KONTAKT`-Zeit → so alt, wie App zuletzt lief.

### 4.2 App im Switcher ist ausgegraut

1. `🎚️ App-Aktivierungen` öffnen.
2. `AKTIV` für die App prüfen.
3. `LIZENZ_BIS` prüfen — wenn in der Vergangenheit, wird ausgeblendet.

### 4.3 Neuer Mitarbeiter sieht die Orga-App nicht

1. In CAO-WaWi prüfen: Mitarbeiter ist Mitglied einer Gruppe (z.B.
   `Mitarbeiter`)?
2. In Admin-DB: gibt es für diese Gruppe einen Eintrag in
   `DORFKERN_ROLLE_PERMISSION` für `orga.zugriff`?
3. Fehlt der Eintrag → per DB/SQL ergänzen (Rollen-UI folgt in v2.1).

### 4.4 SMTP geht nicht

- `🔧 Konfiguration` → Filter `EMAIL` → Werte prüfen
  (`email.smtp_host`, `email.smtp_port`, `email.smtp_user`).
- `DEVMODE=1` (aus CAO-REGISTRY) überschreibt: Mails gehen nur an
  den Absender selbst mit `[DEV]`-Prefix.

### 4.5 Wo liegen die Logs?

Abhängig vom Betriebsmodus (siehe Betreiber-Handbuch Kap. 5):

- **System-Dienst**: `journalctl -u dorfkern[-<inst>]-<app>` bzw.
  `/var/log/dorfkern[-<inst>]/<app>.log`
- **Dienst pro Benutzer**: `journalctl --user -u dorfkern-<app>`
- **Ad-hoc**: `/tmp/dorfkern-<app>.log` (admin/orga/kasse/kiosk/
  haccp-poller/einkauf-poller)
- Updater: `/tmp/dorfkern-update.log` bzw. `/var/log/dorfkern/update.log`

### 4.6 Funktionen/Karten reagieren nicht, alles ausgegraut

Fast immer Folge eines DB-Wechsels: die Session zeigt noch auf einen
Mitarbeiter der alten DB. → Auf `/logout`, neu anmelden mit einem
Konto der aktuellen DB. Seit dem `db_sig`-Mechanismus passiert dieser
Logout automatisch beim nächsten Klick.

---

## 5. Siehe auch

- `docs/handbuch-betreiber.md` — Installation, Service-Modi, Kiosk,
  Wartungs-Modus, Multi-Instanz
- `installer/systemd/README.md` — systemd-Details, Einzeiler-Bootstrap
- `RELEASE_DORFKERN_V2.md` — technische Release-Notizen & Entscheidungen
