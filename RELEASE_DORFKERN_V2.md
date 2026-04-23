# Release „Dorfkern v2" – Multi-Shop-Fähigkeit

**Status:** Planungsentwurf (Stand 2026-04-23) — noch nicht freigegeben.
**Scope-Typ:** Architektur- und Konfigurations-Release, **keine neuen Fachfunktionen**.
**Ziel:** Die bestehende Appsammlung so vorbereiten, dass sie in anderen Dorfläden und ähnlichen Geschäften eingesetzt werden kann.

---

## 1. Ziele im Überblick

1. **Produktidentität:** App-Umbenennungen (Verwaltung → **Admin**, WaWi → **Orga**).
2. **Konfiguration zentralisieren:** Alles (außer KassenSichV-/TSE-Belangen) wird in der **Admin-App** konfiguriert und in der DB gespeichert.
3. **Granulares Rechtemanagement:** Rollen aus CAO übernehmen, feinkörnige Permission-Objects einführen, nicht-berechtigte Funktionen ausblenden.
4. **Einheitliches Layout:** Gemeinsame UI-Bausteine nach `/common/templates/` auslagern.
5. **Datenquellen-Abstraktion:** Kiosk/Backwaren unterstützt neben CAO auch Google Sheets, Excel, CSV (Fundament für beliebige Adapter).

---

## 2. Scope

### 2.1 Enthalten

| Thema | Details |
|---|---|
| App-Rename | `verwaltung-app/` → `admin-app/`, `wawi-app/` → `orga-app/`. Dazu URL-Slugs, Service-Namen, Navbar-Labels, Blueprint-Mounts, Env-Var-Prefixe, systemd-kompatible Starter-Skripte. |
| Konfigurations-Migration | ENV-Variablen / `caoxt.ini`-Werte → DB-Tabelle `KONFIGURATION`. Admin-App bringt UI-Masken. |
| Service-Control | Admin-App steuert Start/Stopp der App-Prozesse (Kasse, Kiosk, Orga, HACCP-Poller, Update-Jobs). Auch netzwerkweit (mehrere Hosts). |
| Terminal-Registry | `TERMINAL`-Tabelle: ID, Host, MAC/IP, Rolle (Kasse/Kiosk), aktive App-Instanz. Cookies ersetzt. |
| Feature-Gating | `APP_AKTIVIERUNG` steuert Sichtbarkeit je Mandant. Nicht-aktive Apps im Switcher ausgegraut und nicht anklickbar. |
| Integrations-Config | HACCP-API-Keys, Google-Sheets-Credentials/IDs (Mittagstisch) → DB. |
| Rechte-Modell | Rollen aus CAO lesen (`MITARBEITER.GRUPPE`/`BENUTZERRECHTE`). Eigene Permission-Objekte je App. Admin = Vollzugriff, alle anderen feingranular. |
| Layout-Vereinheitlichung | Navbar-Block, Login-Block, Sidebar-Block, Toast-Block, Footer → `/common/templates/_*.html`-Partials. Alle Apps mit `ChoiceLoader`. |
| Datenquellen-Abstraktion | Abstrakter `BackwarenDatenquelle`-Adapter: CAO (existiert), Google Sheets, Excel (.xlsx), CSV (neu). |

### 2.2 Nicht enthalten

- Neue Fachfunktionen (keine neuen Kasse-/Kiosk-/Orga-Features).
- TSE/KassenSichV-Konfiguration (bleibt in Kasse-App, ist revisionspflichtig).
- Migration auf anderes DBMS (bleibt MySQL).
- i18n/Mehrsprachigkeit (vorerst Deutsch).
- Mobile-/Native-App.

---

## 3. Breaking Changes (bewusst)

| Thema | Alt | Neu | Migrationshinweis |
|---|---|---|---|
| Verzeichnis | `wawi-app/`, `verwaltung-app/` | `orga-app/`, `admin-app/` | Git mv mit History-Erhalt |
| URL | `/wawi`, `/verwaltung` | `/orga`, `/admin` | 301-Redirects für 1 Release-Zyklus |
| systemd-Units | `wawi-app.service` | `orga-app.service` | Installer legt neu an, stoppt/deaktiviert alte |
| Env-Vars | `WAWI_PORT`, `VERWALTUNG_URL`, … | `ORGA_PORT`, `ADMIN_URL`, … | Installer schreibt um; alte Namen als Fallback 1 Release |
| Terminal-ID (Kiosk) | Cookie `kiosk_terminal` | DB-Eintrag `TERMINAL` via MAC/IP-Match beim Start | Migrations-Dialog beim ersten Start: „dieses Gerät ist Terminal X" |
| ini-Sektionen | `[Datenbank]`, `[Umgebung]` in `caoxt.ini` | Lesen weiter unterstützt, aber Admin-UI ist Wahrheit | ini bleibt als Bootstrap (genug für DB-Verbindung, Rest aus DB) |

---

## 4. Phasen & Reihenfolge

Jede Phase ist ein eigener Merge auf `master`, unabhängig deploybar.

### Phase 0 — Release-Plan beschließen (dieses Dokument)
Scope + offene Fragen (Abschnitt 7) klären.

### Phase 1 — App-Rename (Verwaltung→Admin, WaWi→Orga)
- Verzeichnis-Rename mit `git mv` (History erhält).
- Blueprint-URL-Prefixe, Service-Unit-Namen, Env-Var-Prefixe.
- Navbar-Labels + App-Switcher-Icons (Admin = 🔧 oder Eigenes, Orga = 🗂 oder Eigenes — tbd).
- 301-Redirects `/wawi/*` → `/orga/*`, `/verwaltung/*` → `/admin/*` für Übergangszeit.
- Installer passt systemd-Units und ENV-Files an.
- Tests: alle vorhandenen Integrationstests grün.
- **Zeit-Schätzung:** 1 Tag.

### Phase 2 — Layout-Vereinheitlichung auf `/common/templates/`
- Extraktion der Navbar (inkl. neuem Logo), Login-Logo-Block, Sidebar-Gerüst, Toast-Komponente, Footer.
- `ChoiceLoader` in **allen vier** Apps (aktuell nur Orga/WaWi hat ihn).
- Per App nur noch Nav-Items, App-Titel, App-Farbakzent konfigurierbar.
- **Zeit-Schätzung:** 1–2 Tage.

### Phase 3 — Konfigurations-Schema + `KONFIGURATION`-Tabelle
- Neue Tabelle `DORFKERN_KONFIG(SCHLUESSEL, WERT, TYP, KATEGORIE, GEAENDERT_AM, GEAENDERT_VON)`.
- `common/konfig.py`-Modul mit `get(key, default)` / `set(key, value)` / Cache mit TTL.
- Migrations-Script: ENV/ini-Werte einmalig in die Tabelle kopieren.
- Alle Apps lesen über `common/konfig.py` (ENV nur noch als Notfall-Override).
- **Zeit-Schätzung:** 2 Tage.

### Phase 4 — Terminal-Registry (DB statt Cookie)
- Neue Tabelle `TERMINAL(TERMINAL_ID, HOSTNAME, MAC_ADRESSE, IP, TYP, APP_INSTANZ, LETZTER_KONTAKT)`.
- Auto-Discovery beim Start: Host matcht per MAC oder Hostname → Zuweisung.
- Admin-UI: Terminals anlegen/umbenennen/Zuweisung ändern.
- Cookie-Fallback entfernt, Migrations-Dialog beim ersten Start.
- **Zeit-Schätzung:** 2 Tage.

### Phase 5 — Admin-App: Konfigurations-UI
- Navigation: Allgemein, Datenbank, Dienste, Terminals, Integrationen (HACCP, Google), App-Aktivierungen.
- Service-Control: Start/Stop-Buttons über systemd (lokal) bzw. SSH (remote).
- Host-Verteilung: je App-Instanz einen Host zuordnen. Admin pingt Health-Endpoints.
- HACCP-Konfig-UI: TFA-Credentials, Poll-Intervalle, Sensor-Mapping.
- Google-Mittagstisch-UI: Spreadsheet-ID, Service-Account-JSON-Upload, Wochen-Layout.
- **Zeit-Schätzung:** 4–6 Tage.

### Phase 6 — Rechtemodell + Permission-Objekte
- Schema-Entwurf unten (Abschnitt 6).
- Import aus CAO: `MITARBEITER.GRUPPE` (Mitarbeiter, Ladenleitung, Geschäftsführung, Administratoren).
- Administrator-Gruppe = implizit alle Objekte.
- Admin-UI: Matrix Gruppe × Permission-Objekt (zzgl. für Schichtplan: Lesen/Pflegen).
- Einbindung in Views: `@rechte_benoetigt("kiosk.backwaren")`-Decorator; Navigation filtert auf das, was der User darf.
- **Zeit-Schätzung:** 4–5 Tage.

### Phase 7 — App-Aktivierungen + Feature-Gating im Switcher
- `APP_AKTIVIERUNG(APP, AKTIV, LIZENZ_BIS)`-Tabelle.
- Admin-UI: Ein/Ausschalten je App.
- Switcher zeigt nicht-aktive Apps ausgegraut (kein Link).
- **Zeit-Schätzung:** 1 Tag.

### Phase 8 — Datenquellen-Abstraktion für Kiosk/Backwaren
- `BackwarenDatenquelle`-Interface: `artikel_liste()`, `bestand(artikel_id)`, `schreibe_verkauf(...)`.
- Adapter: `CaoMysqlQuelle` (existiert, kapseln), `GoogleSheetQuelle`, `ExcelQuelle`, `CsvQuelle`.
- Admin-UI zur Adapter-Wahl + adapter-spezifischer Config.
- Dokumentation für weitere Adapter-Implementierungen.
- **Zeit-Schätzung:** 3–4 Tage.

### Phase 9 — Installer & Deployment
- Installer unterstützt Mehr-Host-Setup (ein „Admin-Host" + mehrere „Terminal-Hosts").
- Non-interaktiver Modus für Massen-Rollouts.
- Verschlüsselte Config-Bundles (für Mandanten-Erstinstallation).
- **Zeit-Schätzung:** 2–3 Tage.

### Phase 10 — Dokumentation & Handover
- Admin-Handbuch (Rollen, Permissions, Konfiguration, Troubleshooting).
- Betreiber-Handbuch für neue Dorfläden (Installationsweg, Inbetriebnahme).
- CHANGELOG-Konsolidierung.
- **Zeit-Schätzung:** 2 Tage.

---

## 5. Datenmodell-Entwürfe

### 5.1 `DORFKERN_KONFIG` (Phase 3)

```sql
CREATE TABLE IF NOT EXISTS DORFKERN_KONFIG (
  SCHLUESSEL      VARCHAR(128) PRIMARY KEY,
  WERT            TEXT,
  TYP             ENUM('STRING','INT','BOOL','JSON','SECRET') NOT NULL DEFAULT 'STRING',
  KATEGORIE       VARCHAR(64) NOT NULL,  -- 'DB','EMAIL','HACCP','MITTAGSTISCH','APP_ORGA',...
  BESCHREIBUNG    TEXT,
  GEAENDERT_AM    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  GEAENDERT_VON   INT,  -- MA_ID
  INDEX (KATEGORIE)
);
```
Secrets werden symmetrisch mit einem Master-Key (aus `caoxt.ini`) verschlüsselt, damit nur der Bootstrap-Config-Pfad Klartext enthält.

### 5.2 `TERMINAL` (Phase 4)

```sql
CREATE TABLE IF NOT EXISTS TERMINAL (
  TERMINAL_ID     INT AUTO_INCREMENT PRIMARY KEY,
  BEZEICHNUNG     VARCHAR(64) NOT NULL,   -- "Kasse 1", "Backwaren-Kiosk"
  TYP             ENUM('KASSE','KIOSK','ADMIN','ORGA') NOT NULL,
  HOSTNAME        VARCHAR(128),
  MAC_ADRESSE     VARCHAR(17),
  IP_LETZTE       VARCHAR(45),
  AKTIV           BOOLEAN DEFAULT TRUE,
  LETZTER_KONTAKT DATETIME,
  UNIQUE KEY (TYP, BEZEICHNUNG)
);
```

### 5.3 Rechte-Modell (Phase 6)

```sql
-- Eine Rolle (z.B. Ladenleitung) wird aus MITARBEITER.GRUPPE gelesen; hier nur lokale Ergänzungen.
CREATE TABLE IF NOT EXISTS DORFKERN_PERMISSION_OBJEKT (
  OBJEKT_KEY      VARCHAR(64) PRIMARY KEY,   -- 'kiosk.backwaren', 'kasse.storno',...
  APP             ENUM('KIOSK','KASSE','ORGA','ADMIN') NOT NULL,
  BEZEICHNUNG     VARCHAR(128) NOT NULL,
  BESCHREIBUNG    TEXT,
  UNTERSCHEIDUNG  ENUM('KEINE','LESE_PFLEGE') DEFAULT 'KEINE'
);

CREATE TABLE IF NOT EXISTS DORFKERN_ROLLE_PERMISSION (
  ROLLE           VARCHAR(64) NOT NULL,       -- 'Mitarbeiter','Ladenleitung',...
  OBJEKT_KEY      VARCHAR(64) NOT NULL,
  RECHT           ENUM('LESEN','PFLEGEN','BEIDES') NOT NULL DEFAULT 'BEIDES',
  PRIMARY KEY (ROLLE, OBJEKT_KEY),
  FOREIGN KEY (OBJEKT_KEY) REFERENCES DORFKERN_PERMISSION_OBJEKT(OBJEKT_KEY)
);
```

**Administratoren** sind hart implizit berechtigt (kein Eintrag nötig, Wildcard im Prüf-Code).

### 5.4 Geplante Permission-Objekte (nach User-Vorgabe)

| App | OBJEKT_KEY | Unterscheidung |
|---|---|---|
| KIOSK | `kiosk.zugriff` | – |
| KIOSK | `kiosk.backwaren` | – |
| KIOSK | `kiosk.bestellverwaltung` | – |
| KIOSK | `kiosk.mittagstisch` | – |
| KIOSK | `kiosk.stempeluhr` | – |
| KASSE | `kasse.zugriff` | – |
| KASSE | `kasse.storno` | – |
| KASSE | `kasse.einstellungen` | – |
| ORGA | `orga.<menu_key>` für jeden Sidebar-Eintrag | – außer: |
| ORGA | `orga.schichtplan` | **LESE_PFLEGE** |

### 5.5 `APP_AKTIVIERUNG` (Phase 7)

```sql
CREATE TABLE IF NOT EXISTS DORFKERN_APP_AKTIVIERUNG (
  APP             VARCHAR(32) PRIMARY KEY,   -- 'KIOSK','KASSE','ORGA','ADMIN'
  AKTIV           BOOLEAN NOT NULL DEFAULT TRUE,
  LIZENZ_BIS      DATE,
  HINWEIS         VARCHAR(255)
);
```

---

## 6. Architektur-Prinzipien (Dorfkern v2)

1. **Single Source of Truth = Datenbank.** `caoxt.ini` bleibt nur noch als Bootstrap (DB-Verbindung + Master-Key). Alles andere in `DORFKERN_KONFIG`.
2. **Common-First.** Jedes UI-Pattern, das in ≥ 2 Apps vorkommt, wandert nach `/common/templates/`.
3. **Fail Closed bei Rechten.** Wer kein explizites Permission-Objekt hat, sieht die Funktion nicht. Navigation generiert sich aus den Rechten.
4. **Adapter vor Direktzugriff.** Keine Fach-App ruft direkt `mysql.connector`-Methoden; immer über `common/db.py` oder einen Adapter (Backwaren-Datenquelle).
5. **Keine Breaking Changes ohne Migrationspfad.** Jede URL-/Env-Var-/Cookie-Änderung hat einen Übergangsmechanismus für ≥ 1 Release.

---

## 7. Offene Entscheidungen (vor Phase 1)

Bitte beantworten, damit Phase 1 starten kann:

1. **Produktname:** Ist „Dorfkern" der offizielle Produktname (erscheint z.B. in Fußzeilen, Admin-Titel)? Oder nur internes Arbeitswort?
2. **Mandantenfähigkeit:**
   - **Variante A:** Eine Instanz = ein Laden (eine DB, eine Code-Installation pro Laden). Skalierung durch mehrere Installationen. *(Einfacher, aktuelles Modell.)*
   - **Variante B:** Eine Instanz = viele Läden (Tenant-ID in allen Tabellen). *(Aufwendiger, ermöglicht SaaS-Modell.)*
   - Mein Vorschlag: **A**, solange kein konkretes SaaS-Szenario verfolgt wird.
3. **Rechte-Quelle:** Ist CAO **die** Wahrheit für Benutzer + Rollen, oder führen wir eine eigene Benutzer-Tabelle und synchronisieren? Mein Vorschlag: CAO bleibt Wahrheit für Mitarbeiter, Permission-Objekte sind Dorfkern-eigene Tabelle, Mapping Rolle → Objekte auch Dorfkern-eigen.
4. **App-Umbenennung — URL-Redirects:** Wie lange sollen `/wawi/*` und `/verwaltung/*` noch als 301-Redirect erhalten bleiben? Vorschlag: bis einschließlich nächste Major-Version.
5. **Icons Admin/Orga:** Ersetzen wir ⚙️/📦 im App-Switcher durch Eigene, oder reichen die bestehenden Emojis zunächst?
6. **Service-Control über Netzwerk (Phase 5):** Über SSH mit hinterlegtem Key, oder über einen eigenen kleinen Agent-Dienst auf jedem Host? Vorschlag: SSH in v2, Agent optional in v3.
7. **Datenquellen-Schreibrichtung (Phase 8):** Sollen Google-Sheet-/CSV-Adapter **schreibend** sein (Verkäufe zurückschreiben) oder nur **lesend** (Bestand importieren)? Schreibend ist deutlich heikler (Konflikte, Format).
8. **TSE-Relevanz prüfen:** Alle Konfigurations-Änderungen daraufhin prüfen, ob sie zertifizierungsrelevant sind? Vorschlag: Ja, Checkliste bei jedem Phase-Merge; Zertifizierungs-relevante Felder bleiben in Kasse und werden nicht über Admin-UI editierbar.
9. **Rollout-Strategie Habacher Dorfladen vs. neue Läden:** Erst bei Habacher durchlaufen lassen, dann neue Läden? Oder Dev-Line für neue Läden, Habacher bleibt auf v1? Vorschlag: Habacher als Referenz-Installation auf v2 migrieren, dann Rollout an weitere.
10. **Release-Nummerierung:** Wie wird diese Release-Linie versioniert (z.B. `v2.0.0`)? Nutzung in `caoxt.ini [Version]`?

---

## 8. Risiken

| Risiko | Abmilderung |
|---|---|
| Rename verwaist Import-Pfade/Scripts außerhalb des Repos | Installer-Upgrade erkennt alte Pfade und migriert |
| Rechte-Migration bricht bestehende Benutzer | Pflicht-Pfad: CAO-Rollen importieren, Default-Zuweisung für jede Rolle anbieten |
| Terminal-Zuweisung bei identischer MAC (VMs/Container) | Fallback auf Hostname; manuell überschreibbar |
| Secrets-Speicherung in DB | Master-Key aus `caoxt.ini` (Dateirechte 600), Secrets-Typ verschlüsselt |
| TSE-Zertifizierung berührt | Alle Kasse-Änderungen durch Kassen-Review (Checkliste in jeder PR) |
| Datenquellen-Adapter inkonsistent | Strikte Interface-Definition + Contract-Tests |

---

## 9. Nächste Schritte

1. **Dieses Dokument reviewen** und offene Fragen (Abschnitt 7) beantworten.
2. Nach Freigabe: **Phase 1 (App-Rename)** auf feature-branch starten.
3. Jede Phase endet mit Merge auf master + manueller Freigabe zum Push.

---

*Dokument liegt im Worktree `recursing-kare-deec3d` unter `RELEASE_DORFKERN_V2.md`. Änderungen erfolgen über Standard-PR-Flow auf `master`.*
