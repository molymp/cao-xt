# Benutzerhandbuch: Kasse-App

**Version:** 0.1.0
**Letzte Aktualisierung:** 2026-04-04

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

## Bekannte Einschränkungen

- *Diese Datei wird bei jedem Release aktualisiert.*
