# Changelog

Alle wichtigen Änderungen am cao-xt Projekt werden hier dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

---

## [Unreleased]

### Hinzugefügt
- Neue Flask-App `wawi-app` auf Port 5003 mit Dashboard (CFO-Kennzahlen), Sidebar-Navigation und WaWi-Blueprint-Integration (HAB-131)
- WaWi-Button in Navbar von kasse-app und kiosk-app (HAB-131)

### Geändert
- `kasse-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt (HAB-131)
- `kiosk-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt (HAB-131)

## [0.2.0] – 2026-04-04

### Behoben
- Kundenauswahl korrekt mit geparkt/entparkt verknüpfen – Kunde wird beim Parken zurückgesetzt und beim Entparken wiederhergestellt; Geparkte-Bons-Liste zeigt Kundennamen (HAB-95)
- 3 Abend-Routine UI-Bugs behoben: Kassensturz nach Z-Bon gesperrt, Weiterleitung nach Transfer Kasse→Bank, Status-Wiederherstellung bei nach_bank=1 (HAB-100)

## [0.1.0] – 2026-04-04

### Hinzugefügt
- DECISIONS.md für Architekturentscheidungen eingeführt
- CHANGELOG.md eingeführt
- Benutzerhandbücher unter `docs/` angelegt
- Merge-Pflicht für Dokumentationsaktualisierung in AGENTS.md verankert

### Geändert
- *noch keine*

### Behoben
- *noch keine*
