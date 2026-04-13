# Benutzerhandbuch: Kiosk-App

**Version:** 0.4.0
**Letzte Aktualisierung:** 2026-04-13

---

## Überblick

Die Kiosk-App (`kiosk-app/`) ist die Self-Service-Informationsstation des Dorfladens Habach. Mitarbeiter können darüber Artikel scannen, Warenkörbe verwalten und Bestellungen abwickeln.

---

## Anmeldung

Die Kiosk-App bietet zwei Anmeldearten:

### Kartenlogin (Barcode-Scan)
Standardmäßig ist der Tab **„Karte scannen"** aktiv. Mitarbeiterausweis vor den Barcode-Scanner halten – die Anmeldung erfolgt automatisch. Es werden nur Mitarbeiterkarten akzeptiert (KARTEN.TYP='M').

### Passwort-Login mit Touch-Tastatur
Tab **„Passwort"** wählen. Benutzername und Passwort eingeben – bei Bedarf über die eingeblendete Touch-Tastatur (QWERTZ-Layout). Shift (⇧) für Großbuchstaben, Backspace (⌫) zum Löschen, OK zum Absenden.

Nach der Anmeldung zeigt die Navigationsleiste rechts oben den Anmeldenamen, die aktuelle Uhrzeit und das Datum.

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

## Terminal 9: Kunden-Selbstbedienung (Backwaren)

Terminal 9 ist ein spezielles Kunden-Terminal für Backwarenbestellungen.

### Terminal einrichten
1. Im Menü auf **🖥️ Terminal** klicken
2. Terminal **9** auswählen → Seite lädt im Kundenmodus neu
3. Die Einstellung wird als Browser-Cookie gespeichert (1 Jahr gültig)

### Kundenkarte scannen
Auf dem Kunden-Scan-Bildschirm die Kundenkarte (KARTEN.TYP='K') vor den Scanner halten. Nach erfolgreichem Scan öffnet sich die Bestellübersicht.

### Bestellungen verwalten
- **Meine Bestellungen:** Übersicht aller eigenen Bestellungen
- **Neue Bestellung:** Einmalige oder wiederkehrende Bestellung anlegen
- **Stornieren:** Bestehende Bestellung stornieren

Bestellungen anderer Kunden sind nicht sichtbar.

### Zurück zur Mitarbeiter-Ansicht
1. Auf **🔑 Login** in der Menüleiste klicken
2. Als Mitarbeiter anmelden
3. Über **🖥️ Terminal** auf ein anderes Terminal (z.B. 8) wechseln

Kunden können über **← Kundenkarte scannen** von der Login-Seite zurück zum Scan-Bildschirm.

---

## Bekannte Einschränkungen

- Terminal 9: Bestellungen bearbeiten (Positionen ändern) noch nicht verfügbar – nur Stornieren möglich
- Terminal 9: Datum/Uhrzeit-Auswahl nutzt native HTML5-Eingabefelder statt Custom-Picker
- *Diese Datei wird bei jedem Release aktualisiert.*
