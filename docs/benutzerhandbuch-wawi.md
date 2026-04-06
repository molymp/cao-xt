# Benutzerhandbuch – WaWi (Warenwirtschaft)

**Version:** 0.4.0
**Stand:** 2026-04-07
**App:** `wawi-app` · Port 5003

---

## Übersicht

Die WaWi-App ist das Warenwirtschafts-Modul des Dorfladens Habach. Sie läuft auf Port 5003 und ist über die Navbar (Schaltfläche „📦 WaWi") aus Kasse und Kiosk erreichbar.

---

## Login

Zugangsdaten sind identisch mit der Kassen-App (CAO-Mitarbeiterdaten).
Nach dem Login erscheint das Dashboard.

---

## Sidebar-Navigation

| Bereich | Seite | Beschreibung |
|---------|-------|-------------|
| Dashboard | `/` | Tageseinnahmen, Monatsumsatz, offene Vorgänge |
| Stammdaten → Artikel | `/wawi` | Artikelsuche & Detailansicht |
| Stammdaten → Preispflege | `/wawi/preispflege` | EK / VK5 / Marge aller Normalartikel |
| Weitere → Reporting | `/reporting` | CFO-Reports: MwSt, Warengruppen-Umsatz |

---

## Preispflege (HAB-235)

Unter **Stammdaten → Preispflege** werden alle Normalartikel mit VK5 > 0 angezeigt.

### Spalten

| Spalte | Bedeutung |
|--------|-----------|
| Art-Nr. | CAO-Artikelnummer |
| Bezeichnung | Kassenname des Artikels |
| Warengruppe | Zugeordnete Warengruppe |
| EK (€) | Einkaufspreis aus CAO-Stammdaten |
| VK5 Brutto (€) | Barverkaufspreis inkl. MwSt – **inline editierbar** |
| Marge % | Berechnete Bruttomarge: `(VK5_netto − EK) / VK5_netto × 100` |
| MwSt % | MwSt-Satz je CAO-Steuercode (0 / 7 / 7,8 / 19 %) |

### Filtern nach Warengruppe

Dropdown oben links → gewünschte Warengruppe wählen → Tabelle lädt automatisch neu.

### Sortierung

Klick auf Spaltenüberschrift sortiert die Tabelle. Standard: **Marge aufsteigend** (niedrigste Marge zuerst).

### VK5 inline bearbeiten

1. Auf den VK5-Wert klicken → Eingabefeld erscheint.
2. Neuen Brutto-Preis (€) eingeben – Komma oder Punkt als Dezimaltrenner.
3. `Enter` zum Speichern oder `Escape` zum Abbrechen.
4. Der neue VK5 wird sofort in der CAO-Datenbank (`ARTIKEL.VK5B`) gespeichert.
5. Marge-Badge und Zeilenfarbe aktualisieren sich ohne Seitenreload.

### Farbliche Kennzeichnung

| Farbe | Bedeutung |
|-------|-----------|
| Roter Zeilenhintergrund + rotes Badge | Marge < 10 % – Handlungsbedarf |
| Gelbes Badge | Marge 10–20 % – Beobachten |
| Grünes Badge | Marge ≥ 20 % – Gut |

---

## Artikel-Suche (`/wawi`)

Freitextsuche nach Art.-Nr., Bezeichnung, Kassenname oder Barcode.
Zeigt Basisdetails, aktuelle VK-Preise aller Ebenen (VK1–VK5) und EK.

---

## Reporting (`/reporting`)

- **MwSt-Tabelle:** Aufschlüsselung nach 7 % / 19 % je Monat (letzte 12 Monate).
- **Warengruppen-Umsatz:** Brutto-Umsatz und COGS nach Warengruppe für gewählten Monat.
- **Finance-KPIs:** Aktueller und Vormonat im Vergleich (Umsatz, Belege, Tages-Ø, Ø 6 Monate).

---

## CFO-Berichte (`/wawi/berichte`)

Erreichbar über Sidebar → **Weitere → Reporting / CFO-Reports** oder direkt unter `/wawi/berichte`.

### Verfügbare Berichte

| Bericht | URL | Beschreibung |
|---------|-----|--------------|
| Übersicht | `/wawi/berichte` | Startseite mit Links zu allen 4 Berichten |
| Tagesumsatz | `/wawi/berichte/tagesumsatz` | Tagesumsätze nach Zahlart (Zeitraumfilter: Von/Bis) |
| Monatsübersicht | `/wawi/berichte/monatsuebersicht` | VK/EK je Monat + Balken-Chart (Jahresauswahl) |
| Kassenbuch | `/wawi/berichte/kassenbuch` | FiBu-Konto 1000 – Kasseneinnahmen/-ausgaben |
| EC-Umsätze | `/wawi/berichte/ec-umsaetze` | EC-Kartentransaktionen nach Zahlungsart |

### Zeitraumfilter

Alle Berichte mit Datum-Filter akzeptieren `?von=YYYY-MM-DD&bis=YYYY-MM-DD` als URL-Parameter. Die Formularfelder auf der Seite setzen diese Parameter automatisch.

### CSV-Export

Jeder Bericht hat einen **CSV exportieren**-Button. Die heruntergeladene Datei ist UTF-8-BOM-kodiert für direkte Öffnung in Excel (ohne Zeichensatzprobleme bei Umlauten).
