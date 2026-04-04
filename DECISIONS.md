# Architekturentscheidungen (DECISIONS.md)

Dieses Dokument protokolliert alle wesentlichen technischen und architekturellen Entscheidungen im cao-xt Projekt.

**Format:**
```
## [DATUM] [KURZTITEL]
- **Problem:** Was war das Problem oder die Anforderung?
- **Entscheidung:** Was wurde entschieden?
- **Begründung:** Warum diese Entscheidung?
- **Alternativen:** Welche Alternativen wurden erwogen?
- **Konsequenzen:** Was sind die Auswirkungen?
- **Referenz:** HAB-XX (Paperclip-Issue)
```

---

## 2026-04-04 wawi-app als eigenständige Flask-App auf Port 5003

- **Problem:** Das bestehende WaWi-Modul (`modules/wawi`) hatte keinen eigenen Einstiegspunkt für den Browser; CFO-Kennzahlen waren nicht zugänglich.
- **Entscheidung:** Neue Flask-App `wawi-app` analog zu `kasse-app` und `kiosk-app` erstellt (Port 5003). WaWi-Blueprint aus `modules/wawi/routes.py` wird eingebunden. kasse-app und kiosk-app erhalten einen WaWi-Schnellzugriff-Button in der Navbar.
- **Begründung:** Trennung der Apps nach Aufgabe (Kasse, Kiosk, WaWi) hält die Codebasis übersichtlich und erlaubt unabhängige Starts/Deployments.
- **Alternativen:** WaWi als Blueprint in kasse-app integrieren (Kopplung zu hoch); separater Webserver mit anderem Framework (zu fremdartig im Stack).
- **Konsequenzen:** Dritter Port im LAN (5003). DB-Zugangsdaten werden analog aus `caoxt/caoxt.ini` gelesen. `wawi-app` ist unabhängig startbar.
- **Referenz:** [HAB-131](/HAB/issues/HAB-131)

---

## 2026-04-04 DECISIONS.md und Benutzerhandbücher als Merge-Pflicht eingeführt

- **Problem:** Board-Mitglieder konnten nicht nachvollziehen, was sich bei einem Release geändert hat und warum Entscheidungen so getroffen wurden.
- **Entscheidung:** Ab sofort ist jeder Merge in den `master` Branch nur zulässig, wenn DECISIONS.md, die relevanten Benutzerhandbücher und CHANGELOG.md aktualisiert wurden.
- **Begründung:** Transparenz für das Board, Nachvollziehbarkeit für zukünftige Entwickler.
- **Alternativen:** Externe Wiki-Lösung (zu komplex), nur Kommentare in Commits (nicht zugänglich genug).
- **Konsequenzen:** Mehr Dokumentationsaufwand pro Feature, aber dauerhaft bessere Übersicht.
- **Referenz:** [HAB-105](/HAB/issues/HAB-105)
