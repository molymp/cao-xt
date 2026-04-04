# Benutzerhandbuch: Kiosk-App

**Version:** 0.2.0
**Letzte Aktualisierung:** 2026-04-04

---

## Überblick

Die Kiosk-App (`kiosk-app/`) ist die Self-Service-Informationsstation des Dorfladens Habach. Mitarbeiter können darüber Artikel scannen, Warenkörbe verwalten und Bestellungen abwickeln.

---

## Anmeldung

Beim Start der Kiosk-App erscheint ein Login-Formular. Hier mit Benutzername und Passwort anmelden (gleiche Zugangsdaten wie in Kasse und WaWi). Nach der Anmeldung zeigt die Navigationsleiste rechts oben den Anmeldenamen, die aktuelle Uhrzeit und das Datum.

Zum Abmelden: Schaltfläche **Abmelden** in der Navigationsleiste verwenden.

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

## Navigationsleiste

Die Navigationsleiste am oberen Rand zeigt:

- **Links:** Logo mit Firmenname und Mandantname
- **App-Switcher:** Schnellzugriff auf Kiosk / Kasse / WaWi (aktive App hervorgehoben). Klick auf „Kiosk" führt zur Startseite.
- **Mitte:** Navigationsmenü (Artikelauswahl, Geparkt, Journal, Verwaltung, …)
- **Rechts:** Angemeldeter Nutzer, Uhrzeit, Datum

---

## Funktionen

| Funktion | Beschreibung |
|----------|-------------|
| Artikelauswahl | Anzeige und Auswahl aller verfügbaren Artikel |
| Geparkt | Geparkte Warenkörbe einsehen und fortsetzen |
| Journal | Buchungshistorie |
| Verwaltung | Artikel- und Systemverwaltung |
| Bestellungen | Bestelleingang und -verwaltung |
| Mittagstisch | Mittagsangebote verwalten |

---

## Bekannte Einschränkungen

- *Diese Datei wird bei jedem Release aktualisiert.*
