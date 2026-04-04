# Benutzerhandbuch: Kiosk-App

**Version:** 0.1.0
**Letzte Aktualisierung:** 2026-04-04

---

## Überblick

Die Kiosk-App (`kiosk-app/`) ist die Self-Service-Informationsstation des Dorfladens Habach. Kunden können darüber Informationen zu Produkten und Angeboten abrufen.

---

## Starten der App

```bash
cd kiosk-app
flask run
```

Oder via systemd:
```bash
sudo systemctl start kiosk-app
```

---

## Funktionen

| Funktion | Beschreibung |
|----------|-------------|
| Produktübersicht | Anzeige aller verfügbaren Artikel |
| Angebotsseite | Aktuelle Sonderangebote |
| Suche | Artikel nach Name oder Kategorie suchen |

---

## Bekannte Einschränkungen

- *Diese Datei wird bei jedem Release aktualisiert.*
