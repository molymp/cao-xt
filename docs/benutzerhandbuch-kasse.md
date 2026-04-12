# Benutzerhandbuch: Kasse-App

**Version:** 0.2.0
**Letzte Aktualisierung:** 2026-04-12

---

## Überblick

Die Kasse-App (`kasse-app/`) ist die Kassierapplikation des Dorfladens Habach. Sie läuft auf einem Raspberry Pi und ermöglicht den Verkaufsprozess an der Kasse.

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
| Warenkorb | Artikel hinzufügen, entfernen, Menge ändern |
| Bezahlvorgang | Bar- und Kartenzahlung |
| Bon-Druck | Automatischer Bondruck nach Bezahlung |
| Tagesabschluss | Kassenschluss und Tagesabrechnung |

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
