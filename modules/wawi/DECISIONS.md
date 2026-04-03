# DECISIONS.md – CAO-XT WaWi-Modul

Architektur- und Designentscheidungen für `modules/wawi/`.

---

## Übersicht

Warenwirtschafts-Modul (WaWi) als Python-Flask-Blueprint im cao-xt-Repository.
Phase 1: Artikelpreispflege & VK-Ermittlung.

**Technologie-Stack**
- Python Flask (Blueprint; Port 5003 im Standalone-Betrieb)
- MySQL – CAO-Faktura-Datenbank, DictCursor (mysql.connector)
- Tabellenpräfix `XT_WAWI_` für alle neuen Tabellen
- CAO-Stammdaten (ARTIKEL, WARENGRUPPEN, ARTIKEL_PREIS) read-only

---

## Datenbankschema

### Tabellenpräfix `XT_WAWI_`

Alle neuen WaWi-Tabellen tragen das Präfix `XT_WAWI_`, analog `XT_KASSE_` in der Kassen-App.

| Tabelle | Zweck |
|---------|-------|
| `XT_WAWI_PREISHISTORIE` | Append-only Preishistorie je Artikel + Ebene (GoBD-Audit-Trail) |
| `XT_WAWI_PREISGRUPPEN` | VK-Preisgruppen (Stammdaten, Ebenen 1–5) |

### CAO-Tabellen (read-only)

`ARTIKEL`, `WARENGRUPPEN`, `MENGENEINHEIT`, `ARTIKEL_PREIS`

---

## GoBD-Architektur-Entscheidungen

### Append-only Preishistorie

Preise werden **niemals überschrieben**. Jede Preisänderung erzeugt einen neuen Datensatz
mit neuem `GUELTIG_AB`. Der bisherige offene Eintrag wird per `UPDATE ... SET GUELTIG_BIS`
soft-closed (nur das Ablaufdatum wird gesetzt – kein inhaltliches Feld wird verändert).

**Grund:** GoBD §146 Abs. 4 AO verbietet die Veränderung oder Vernichtung von
buchungsrelevanten Aufzeichnungen. Preisänderungen sind für Nachkalkulation, Betriebsprüfungen
und Steuerprüfungen relevant.

**Konsequenz:** `XT_WAWI_PREISHISTORIE` enthält den vollständigen Audit-Trail jedes Preises.
Zu jedem Zeitpunkt lässt sich der damals gültige Preis rekonstruieren.

### `created_at` / `created_by` in jeder buchungsrelevanten Zeile

Alle Tabellen mit buchungsrelevantem Inhalt tragen:
- `CREATED_AT DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` – Erfassungszeitpunkt (Datenbankseite)
- `CREATED_BY VARCHAR(100) NOT NULL` – Benutzername des Erfassers (Anwendungsseite)

Diese Felder dürfen nach dem INSERT **niemals verändert** werden.

### Kein DELETE auf `XT_WAWI_PREISHISTORIE`

Historische Preiseinträge dürfen nicht gelöscht werden. Falls ein Eintrag irrtümlich angelegt
wurde, wird ein Korrektur-Eintrag mit Kommentar angelegt (Storno-Prinzip).

---

## Geldbeträge als Integer-Cent

Alle Geldbeträge werden als `INT` in Cent gespeichert (Spaltenname-Konvention: `_CT`-Suffix).

**Grund:** Vermeidung von Gleitkomma-Rundungsfehlern; konsistent mit `XT_KASSE_VORGAENGE_POS`.

---

## VK-Preisermittlung (Prioritätskette)

Bei der VK-Preisermittlung (`vk_berechnen()`) gilt folgende Priorität:

1. **WaWi-Preishistorie** (`XT_WAWI_PREISHISTORIE`) – manuell gepflegte Preise, Quelle `wawi`
2. **CAO-Aktionspreis** (`ARTIKEL_PREIS` mit `PT2='AP'`, Gültigkeitsfilter) – Quelle `aktion`
3. **CAO-Standardpreis** (`VK5B` bzw. `VKxB` je Ebene) – Quelle `cao`

Die Quelle wird im API-Response zurückgegeben, damit Clients die Herkunft kennen.

**Hintergrund:** CAO-DB ist weiterhin das führende System für Stammdaten. Das WaWi-Modul
ergänzt CAO-Preise, überschreibt sie aber nur wenn explizit ein WaWi-Preis gepflegt wurde.

---

## Kein ORM

Direktes SQL mit DictCursor (mysql.connector).

**Grund:** CAO-Datenbankstruktur ist vorgegeben und historisch gewachsen; ORM-Mapping
würde keinen Mehrwert bringen. Konsistent mit kasse-app und kiosk-app.

---

## Flask Blueprint statt eigenständige App (Phase 1)

Die WaWi-Routen sind als Flask-Blueprint (`modules/wawi/routes.py`) implementiert.

**Grund:** Die WaWi-Funktionen sollen perspektivisch in bestehende Apps (z. B. kasse-app)
eingebettet werden können, ohne eine weitere eigenständige Flask-App auf einem weiteren Port
betreiben zu müssen.

Im Standalone-Betrieb (Port 5003) kann das Blueprint über eine minimale `__main__.py`
gestartet werden (wird in Phase 2 ergänzt).

---

## CAO-DB als führendes System für Stammdaten

Artikelstamm, Warengruppen und Mengeneinheiten verbleiben in der CAO-DB (Firebird/MySQL).
Das WaWi-Modul greift read-only auf diese Daten zu.

**Grund:** CAO-Faktura ist das ERP-System des Dorfladens; eine parallele Datenhaltung
würde zu Inkonsistenzen führen. Migration auf ein eigenes Stammdatensystem ist erst
relevant wenn CAO abgelöst wird.

---

## Authentifizierung

Analog kasse-app: gegen `MITARBEITER`-Tabelle, Passwort als MD5-Hash in Großbuchstaben.
Session-basiert (Flask `session`). Im Blueprint über `_benutzer()` in `routes.py`.

---

## Noch nicht implementiert (Phase 2+)

- **Einkaufspreispflege (EK)**: EK-Preise und Kalkulation
- **Lagerbestandsführung**: MENGE_AKT-Tracking außerhalb CAO
- **Lieferantenverwaltung**: eigene XT_WAWI_-Tabellen
- **Standalone-Entrypoint**: `__main__.py` für Port 5003
- **Automatischer Preisabgleich**: WaWi → CAO VKxB zurückschreiben
