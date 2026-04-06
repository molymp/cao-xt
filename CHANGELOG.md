# Changelog

Alle wichtigen Änderungen am cao-xt Projekt werden hier dokumentiert.
Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

---

## [Unreleased]

### Hinzugefügt
- Commit-ID-Anzeige: In allen drei Apps (Kasse, Kiosk, WaWi) wird der aktuelle Git-Commit-Hash oben links als kleiner orangener Hinweis angezeigt (position:fixed, kein Layout-Einfluss) ([HAB-244](/HAB/issues/HAB-244))
- Verbindliche Merge-Pflicht: Sofort-Merge nach Board-Freigabe, 48h-Limit für offene Branches, Rebase-Strategie für Parallelarbeit ([HAB-267](/HAB/issues/HAB-267))
- `.githooks/pre-push`: Versionierter Git-Hook mit Paperclip-Approval-Pflicht für `master`/`main` Pushes ([HAB-242](/HAB/issues/HAB-242))
- `deploy-review.sh`: Script zum atomaren Deployment von Feature-Branches in den Review-Worktree inkl. automatischem WaWi-Server-Neustart ([HAB-194](/HAB/issues/HAB-194))
- `deploy-review.sh`: Robusteres Port-Handling (SIGTERM + PID-Datei) ([HAB-194](/HAB/issues/HAB-194))
- Neue Flask-App `wawi-app` auf Port 5003 mit Dashboard (CFO-Kennzahlen), Sidebar-Navigation und WaWi-Blueprint-Integration ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Button in Navbar von kasse-app und kiosk-app ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Navbar: App-Switcher (Kiosk → Kasse → WaWi), Logo-Wrapper, Uhrzeit/Datum, Login-Name ([HAB-139](/HAB/issues/HAB-139))
- Kasse-Navbar: App-Switcher mit aktiv/inaktiv-Zuständen, Login-Name ([HAB-139](/HAB/issues/HAB-139))
- Kiosk-App: Session-Login (Login-Required, Login/Logout-Routen), App-Switcher, Context-Processor ([HAB-139](/HAB/issues/HAB-139))
- Verbindlicher Merge-Workflow `review → master` dokumentiert ([HAB-196](/HAB/issues/HAB-196))
- Kasse: %-Schnellauswahl-Knöpfe für Prozentsatz-Rabatt ([HAB-142](/HAB/issues/HAB-142))
- Kiosk-App: vollständiger Session-Login-Mechanismus (Login/Logout, Login-Required, login.html) mit Anzeige von Login-Name, Uhrzeit und Datum rechts in der Navbar ([HAB-162](/HAB/issues/HAB-162))
- Kiosk-App: `firma_name` und `db_name` im Context-Processor; FIRMA_NAME-Konfigurationsvariable ([HAB-149](/HAB/issues/HAB-149))

### Geändert
- `kasse-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt ([HAB-131](/HAB/issues/HAB-131))
- `kiosk-app/app/config.py`: WAWI_URL / WAWI_PORT ergänzt ([HAB-131](/HAB/issues/HAB-131))
- WaWi-Reporting: SQL Datumsformat-Escaping und Warengruppen-SQL korrigiert ([HAB-139](/HAB/issues/HAB-139))
- Kasse: EP-Button auf Größe der X-Schaltfläche angepasst; Numpad-Grid quadratisch ([HAB-147](/HAB/issues/HAB-147), [HAB-148](/HAB/issues/HAB-148))
- WaWi-App: Logo „WaWi" jetzt vertikal unter Firmenname (flex-column), nicht mehr daneben ([HAB-149](/HAB/issues/HAB-149))
- Kiosk-App: App-Switcher in `<header>` verschoben (war in `<nav>`); Firmenname und Mandantname im Logo; Nav-Knöpfe mit Rahmen und einheitlicher Höhe; „Kiosk"-Button navigiert zur Startseite ([HAB-149](/HAB/issues/HAB-149))

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
