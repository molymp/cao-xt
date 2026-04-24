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

- Admin-App: `/tmp/caoxt-admin.log`
- Orga-App: `/tmp/caoxt-orga.log`
- Kasse-App: `/tmp/caoxt-kasse.log`
- Kiosk-App: `/tmp/caoxt-kiosk.log`
- HACCP-Poller: `/tmp/caoxt-haccp-poller.log`

---

## 5. Siehe auch

- `docs/handbuch-betreiber.md` — Installation & Deployment
- `RELEASE_DORFKERN_V2.md` — technische Release-Notizen & Entscheidungen
