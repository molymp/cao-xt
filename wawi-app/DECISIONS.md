# CAO-XT WaWi-App – Architekturentscheidungen

> **Konvention:** Jede Architektur- oder Designentscheidung wird hier eingetragen
> (Format: Datum, Problem, Entscheidung, Begründung, Alternativen).
> Eintrag erfolgt im selben Commit wie der zugehörige Code.

---

## 2026-04-03 · Zwei separate Datenbanken: CAO read-only + WaWi read-write (HAB-52)

**Problem:**
Die CAO-Faktura-Datenbank enthält den Artikelstamm (ARTIKEL, WARENGRUPPE, LIEFERANT).
Preisdaten sollen separat verwaltet werden, damit:
a) die CAO-DB nicht durch WaWi-Writes verändert wird,
b) GoBD-konforme Unveränderlichkeit der Preishistorie garantiert werden kann.

**Entscheidung:**
Zwei getrennte MariaDB-Datenbanken:
- `cao_2018_001` (CAO-DB): nur lesend, über `get_cao_db()` Context-Manager
- `cao_wawi` (WaWi-DB): lesen/schreiben, über `get_wawi_db()` / `get_wawi_transaction()`

Beide haben eigene Connection Pools (`wawi_cao_pool`, `wawi_pool`) in `db.py`.

**Begründung:**
- Klare Trennung: CAO-Schema bleibt unberührt (kein Risiko für laufenden Betrieb)
- WaWi-DB kann eigenständig gesichert und migriert werden
- GoBD-Anforderung (append-only Preishistorie) ist strukturell erzwingbar

**Alternativen (nicht gewählt):**
- Preise in CAO-DB direkt schreiben (z.B. ARTIKEL.VK_PREIS): keine GoBD-konforme
  Historisierung möglich, CAO-interne Felder könnten überschrieben werden.
- Flat-File / SQLite für Preise: keine Transaktionssicherheit, kein Multi-User-Betrieb.

---

## 2026-04-03 · GoBD: WAWI_PREISHISTORIE append-only (HAB-52)

**Problem:**
Steuerrechtliche Anforderung (GoBD): Preisänderungen müssen unveränderlich protokolliert
werden. Eine nachträgliche Änderung oder Löschung darf technisch nicht möglich sein.

**Entscheidung:**
- `WAWI_PREISHISTORIE` erhält **keine** UPDATE- oder DELETE-Berechtigungen im Anwendungs-Code.
- Jede Preisänderung ist ein neuer INSERT (append-only).
- Der aktuelle Preis wird über View `v_aktuelle_preise` (MAX(erstellt_am)) ermittelt.
- Code-Konvention: In `preise.py` existiert ausschließlich `preis_speichern()` (INSERT),
  kein `preis_aendern()` oder `preis_loeschen()`.

**Begründung:**
- GoBD §146 Abs. 4 AO: Buchungen dürfen nicht nachträglich verändert werden.
- Vollständige Preis-Audit-Trail ermöglicht Steuerprüfung ohne separate Log-Tabelle.

**Alternativen (nicht gewählt):**
- Soft-Delete mit `gueltig_bis`-Datum: komplexer, aber äquivalent — nicht nötig für Phase 1.

---

## 2026-04-03 · Gleicher Tech-Stack wie kasse-app / kiosk-app (HAB-52)

**Problem:**
Wahl des Frameworks für die neue WaWi-App.

**Entscheidung:**
Gleicher Stack: Python 3 + Flask 3.0, mysql-connector-python, Jinja2-Templates, Vanilla JS.
Kein React/Vue, keine ORM-Schicht (SQLAlchemy).

**Begründung:**
- Konsistenz mit bestehenden Apps erleichtert Wartung durch dasselbe kleine Team.
- Kein zusätzliches Build-Tooling nötig (kein Node.js/npm auf dem Raspberry Pi).
- Direktes SQL ermöglicht präzise Kontrolle über Abfragen (Performance, GoBD-Compliance).

**Alternativen (nicht gewählt):**
- FastAPI + HTMX: interessant für Phase 2, aber Bruch zum bestehenden Muster.
- SQLAlchemy ORM: erleichtert Migrationen, aber unnötige Abstraktionsschicht für
  dieses einfache Schema.

---

## 2026-04-03 · Cross-DB JOIN in Python statt SQL (HAB-52)

**Problem:**
Artikelliste benötigt Stammdaten aus CAO-DB und aktuelle Preise aus WaWi-DB.
MariaDB erlaubt keine direkten Cross-DB JOINs über unterschiedliche Server/User.

**Entscheidung:**
Zweistufige Abfrage in Python:
1. Artikel aus CAO-DB laden (mit Pagination/Filtern)
2. Aktuelle Preise für die geladenen Artikel-IDs aus WaWi-DB per Batch-Query
3. In Python zusammenführen (`_aktuelle_preise_batch()`)

**Begründung:**
- Funktioniert unabhängig davon, ob CAO-DB und WaWi-DB auf demselben Server laufen.
- Batch-Query (IN-Clause mit max. 50 IDs pro Seite) ist performant genug für den Use-Case.

**Alternativen (nicht gewählt):**
- MariaDB FEDERATED engine / Cross-DB JOIN: nur bei gleichem Server möglich, fragile Konfiguration.
- WaWi-DB auf demselben Schema wie CAO: verletzt die read-only-Trennung (s.o.).

---

## 2026-04-03 · Kein Login in WaWi-App Phase 1 (HAB-52)

**Problem:**
WaWi-App läuft im internen Netz (LAN des Dorfladens). Login-System würde Scope
von Phase 1 erheblich erweitern.

**Entscheidung:**
Kein Login in Phase 1. Benutzername für `erstellt_von` kommt aus `config.WAWI_BENUTZER_DEFAULT`
(Default: `'wawi'`, überschreibbar per Env-Var `WAWI_BENUTZER`).

**Begründung:**
- WaWi wird nur von Ladenleitung/Einkauf im internen Netz genutzt.
- GoBD erfordert einen Benutzernamen — das Config-Default reicht für Phase 1.
- Login kann in Phase 2 mit Flask-Login ergänzt werden, ohne Schema-Änderungen.

**Auswirkungen:**
- Für Phase 2: Login-System implementieren und `_benutzer()` auf Session umstellen.
