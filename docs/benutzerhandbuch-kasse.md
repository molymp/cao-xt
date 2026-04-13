# Benutzerhandbuch: Kasse-App

**Version:** 0.3.0
**Letzte Aktualisierung:** 2026-04-13

---

## Überblick

Die Kasse-App (`kasse-app/`) ist die Kassierapplikation des Dorfladens Habach. Sie läuft auf einem Raspberry Pi und ermöglicht den Verkaufsprozess an der Kasse.

---

## Anmeldung

Die Kasse-App bietet zwei Anmeldearten:

### Kartenlogin (Barcode-Scan)
Standardmäßig ist der Tab **„Karte scannen"** aktiv. Mitarbeiterausweis vor den Barcode-Scanner halten – die Anmeldung erfolgt automatisch. Es werden nur Mitarbeiterkarten akzeptiert (KARTEN.TYP='M').

### Passwort-Login mit Touch-Tastatur
Tab **„Passwort"** wählen. Benutzername und Passwort eingeben – bei Bedarf über die eingeblendete Touch-Tastatur (QWERTZ-Layout). Shift (⇧) für Großbuchstaben, Backspace (⌫) zum Löschen, OK zum Absenden.

---

## Starten der App

```bash
cd kasse-app
flask run
```

Oder via systemd:
```bash
sudo systemctl start kasse-app
```

---

## Funktionen

| Funktion | Beschreibung |
|----------|-------------|
| Artikelsuche | Suche nach Artikeln via Barcode oder Name |
| Kundenkarten-Scan | Kundenkarte scannen → Kunde wird automatisch zugewiesen |
| Warenkorb | Artikel hinzufügen, entfernen, Menge ändern |
| Bezahlvorgang | Bar- und Kartenzahlung |
| Bon-Druck | Automatischer Bondruck nach Bezahlung |
| Tagesabschluss | Kassenschluss und Tagesabrechnung |

---

## Parken ein-/ausschalten

Die Parken-Funktion kann in der **Verwaltungs-App** unter **Funktionen** deaktiviert werden.
Wenn deaktiviert:
- Die Buttons „Parken" und „Geparkt" werden ausgeblendet
- Das Geparkte-Bons-Overlay ist nicht verfügbar
- Die Seite muss nach der Änderung neu geladen werden (kein Live-Refresh)

**Hinweis:** Deaktivierung ist nur möglich, wenn keine Bons geparkt sind.

---

## Kundenkarten-Scan

Während des Kassiervorgangs kann eine **Kundenkarte** gescannt werden. Die Karte wird automatisch erkannt (Barcode beginnt mit „KK"), und der zugehörige Kunde wird dem Vorgang zugewiesen:

- **Name und Ort** des Kunden erscheinen in der Kundenanzeige
- **Kundenspezifische Preisebene** wird automatisch angewendet
- **Zahlart** des Kunden wird übernommen (falls hinterlegt)

Kundenkarten sind in der CAO-Datenbank als KARTEN mit TYP='K' gespeichert. Die Zuordnung zum Kunden erfolgt über KARTEN.ID → ADRESSEN.REC_ID.

---

## Manager-Bereich

Erreichbar über den Tab **Manager** in der Kasse-App.

### Übersicht
- Häufige Aktionen (Kassenlade öffnen, Kassensturz, Abendroutine/Z-Bon, Morgenroutine) sind direkt über große Touch-freundliche Buttons erreichbar.
- Der **Kasse**-Button in der Navigationsleiste führt jederzeit zur Kassier-Startseite zurück.

### Morgenroutine
- Zeigt das Zählbrett (Münzen/Scheine) und rechts daneben eine Übersicht über den gezählten Betrag.
- Entnommene Beträge können inline eingetragen werden.

### Abendroutine / Z-Bon
- Z-Abschluss wird direkt im Manager-Bereich ausgeführt (kein separater Bildschirmwechsel).
- Kassensturz und Transfer werden inline geführt.

### Journal
- Volltext-Suche und Datumsfilter (Diese Woche / Letzte Woche / Dieser Monat / individuell) sind prominent platziert.
- Bon-Details werden per Klick auf den Bon-Eintrag aufgeklappt – kein Seitenwechsel nötig.
- Die Bon-Liste ist scrollbar; der Bildschirm selbst scrollt nicht.
- **Nachdruck** (statt „Nochmal") druckt den Bon erneut.
- **Positionen in neuen Bon kopieren** (statt „Kopieren") übernimmt alle Positionen in einen neuen Bon.

### Touch-Optimierung
- Alle Buttons und interaktiven Elemente haben mindestens 48–52 px Höhe/Breite.
- Zählbrett-Tasten sind 52 × 52 px.

---

## Bekannte Einschränkungen

- *Diese Datei wird bei jedem Release aktualisiert.*
