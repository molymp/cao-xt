# Benutzerhandbuch: Kiosk-App

**Version:** 0.5.0
**Letzte Aktualisierung:** 2026-04-19

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
| Geparkt | Geparkte Warenkörbe einsehen und fortsetzen (nur wenn Parken aktiviert) |
| Journal | Buchungshistorie |
| Verwaltung | Artikel- und Systemverwaltung |
| Bestellungen | Bestelleingang und -verwaltung |
| Mittagstisch | Mittagsangebote verwalten |

### Parken ein-/ausschalten

Die Parken-Funktion kann in der **Verwaltungs-App** unter **Funktionen** deaktiviert werden.
Wenn deaktiviert:
- Die Buttons „Parken" und „Geparkt" werden ausgeblendet
- „Abbrechen" wandert neben „Buchen & Drucken" (breiteres Layout)
- Die Seite muss nach der Änderung neu geladen werden (kein Live-Refresh)

**Hinweis:** Deaktivierung ist nur möglich, wenn keine Warenkörbe geparkt sind.

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

## Stempeluhr

Die Stempeluhr ist auf jedem Kiosk-Terminal verfügbar und wird von allen Mitarbeitern für die tägliche Zeiterfassung genutzt — unabhängig vom Login-Nutzer, damit auch während einer aktiven Kassen-Session gestempelt werden kann.

### Buchen mit Mitarbeiterkarte

1. **Karte scannen:** Mitarbeiterausweis (KARTEN.TYP='M') vor den Scanner halten. Die App öffnet automatisch die Stempeluhr-Seite des erkannten Mitarbeiters.
2. **PIN eingeben:** Numpad erscheint; persönliche 4-stellige PIN eingeben → OK.
3. **Menü:** Begrüßung mit Namen und aktueller Status (eingestempelt seit / nicht eingestempelt). Darunter die Aktions-Kacheln:

| Kachel | Wirkung |
|--------|---------|
| **🟢 Kommen** | Neue Anwesenheit beginnt ab jetzt |
| **🔴 Gehen** | Aktuelle Anwesenheit endet jetzt |
| **✏️ Korrektur** | Zeit nachtragen oder korrigieren (mit Datum/Zeit-Picker und Pflicht-Begründung) |
| **🏥 Abwesenheit** | Krank / Fortbildung / Sonstiges ganztägig melden |
| **🏖️ Urlaub** | Urlaubsantrag von-bis stellen |
| **🔑 PIN ändern** | Eigene PIN neu setzen (alte PIN zur Bestätigung) |
| **📅 Übersicht** | Eigene Stempel-Historie des laufenden Monats |

Jede Aktion zeigt nach dem Speichern eine große grüne Bestätigung („Kommen gebucht um 07:12") und kehrt nach 3 s automatisch auf die Startseite zurück.

### Korrektur

Falls das Kommen/Gehen vergessen wurde oder die Zeit falsch war:

1. **Korrektur** im Menü wählen.
2. **Typ** auswählen: Kommen / Gehen / Korrekturbuchung (Plus- oder Minusstunden).
3. **Datum** über Datepicker (Jahr-/Monats-Sprung vorhanden).
4. **Uhrzeit** über Drum-Wheel-Picker (native Eingabe parallel möglich).
5. **Begründung** — Pflichtfeld, über QWERTZ-Touch-Tastatur.
6. **Speichern.** Die Korrektur erscheint in der Mitarbeiter-Stempelhistorie mit deutlicher Kennzeichnung „Korrektur" und dem buchenden Benutzer im Audit-Log.

### Abwesenheit und Urlaub

- **Abwesenheit:** Ganztägige Meldung Krank/Fortbildung/Sonstiges für heute oder einen wählbaren Zeitraum. Die App berechnet die betroffenen Arbeitstage anhand der Wochenverteilung aus dem Arbeitszeitmodell des Mitarbeiters.
- **Urlaub:** Urlaubsantrag von-bis. Nach dem Absenden hat der Antrag den Status `geplant` — die Ladenleitung genehmigt ihn später im WaWi.

Beide Kacheln nutzen den Dual-Mode-Datepicker (Touch + Tastatur gleichwertig).

### Übersicht

Klick auf **📅 Übersicht** zeigt alle Stempel-Paare des aktuellen Monats:

- Datum, Kommen, Gehen, Dauer
- Abwesenheits-/Urlaubstage in eigenen Farben
- Korrekturen mit Hinweis-Badge
- am Ende: Summe Ist, Soll laut Arbeitszeitmodell, Saldo

Abmelden passiert implizit durch Inaktivität oder **Zurück**-Button → nächste Kartenscan-Erwartung.

### PIN-Selfservice

Die PIN kann jeder Mitarbeiter selbst ändern:

1. **🔑 PIN ändern** im Menü.
2. Alte PIN eingeben.
3. Neue PIN 2× eingeben.
4. **Speichern.**

Bei vergessener PIN setzt die Ladenleitung die PIN im WaWi (Mitarbeiter-Detail) zurück; der Mitarbeiter vergibt dann beim nächsten Stempel-Vorgang eine neue.

---

## Bekannte Einschränkungen

- Terminal 9: Bestellungen bearbeiten (Positionen ändern) noch nicht verfügbar – nur Stornieren möglich
- Terminal 9: Datum/Uhrzeit-Auswahl nutzt native HTML5-Eingabefelder statt Custom-Picker
- *Diese Datei wird bei jedem Release aktualisiert.*
