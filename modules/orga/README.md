# Orga-Modul – Warenwirtschaft

Teil des **cao-xt**-Projekts für den Habacher Dorfladen.

## Scope

Phasenweise Erweiterung von CAO-Faktura um eine eigene Warenwirtschaft:

| Phase | Inhalt | Status |
|-------|--------|--------|
| 1 | Artikelpreispflege & VK-Ermittlung | In Entwicklung |
| 2 | EK-Preise, Lagerbestand außerhalb CAO | Geplant |
| 3 | Lieferantenverwaltung, Bestellwesen | Geplant |

## Tech-Stack

- **Python Flask** – Blueprint (`modules/orga/routes.py`)
- **MySQL** – CAO-Faktura-Datenbank (DictCursor, kein ORM)
- **Tabellenpräfix** `XT_WAWI_` – keine Kollision mit CAO-Tabellen
- **CAO-DB** read-only für Stammdaten (ARTIKEL, WARENGRUPPEN, ARTIKEL_PREIS)

## Abhängigkeiten

```
mysql-connector-python
flask
```

## Datenbankschema

```sql
-- Phase 1: Migrationsscript ausführen
mysql -u <user> -p <db_name> < modules/orga/schema.sql
```

Tabellen (Phase 1):

| Tabelle | Beschreibung |
|---------|--------------|
| `XT_WAWI_PREISHISTORIE` | Append-only Preishistorie (GoBD-konform) |
| `XT_WAWI_PREISGRUPPEN` | VK-Preisgruppen (Stammdaten) |

## GoBD-Grundlage

- Alle buchungsrelevanten Tabellen: `CREATED_AT`, `CREATED_BY`
- **Keine** inhaltlichen UPDATEs auf `XT_WAWI_PREISHISTORIE`
- Preisänderungen als neue Einträge (append-only), Vorgänger erhält `GUELTIG_BIS`
- Geldbeträge als Integer-Cent (`INT`, Suffix `_CT`)

Detaillierte Architekturentscheidungen: [DECISIONS.md](./DECISIONS.md)

## API-Routen (Phase 1)

| Methode | Route | Funktion |
|---------|-------|----------|
| GET | `/orga/api/artikel/suche?q=` | Artikelsuche (CAO read-only) |
| GET | `/orga/api/artikel/<artnum>` | Artikeldetails |
| GET | `/orga/api/artikel/<artnum>/vk?ebene=5` | VK-Preis ermitteln |
| GET | `/orga/api/artikel/<artnum>/preise` | Preishistorie |
| POST | `/orga/api/artikel/<artnum>/preise` | Neuen Preis setzen (GoBD) |
| GET | `/orga/api/preishistorie` | Preishistorie-Übersicht (Audit-Log) |

## Integration

```python
# In einer bestehenden Flask-App:
from modules.orga import create_blueprint
app.register_blueprint(create_blueprint(), url_prefix='/orga')
```
