# Benutzerhandbuch – WaWi (Warenwirtschaft)

**Version:** 0.5.0
**Stand:** 2026-04-16
**App:** `wawi-app` · Port 5003

---

## Übersicht

Die WaWi-App ist das Warenwirtschafts-Modul des Dorfladens Habach. Sie läuft auf Port 5003 und ist über die Navbar (Schaltfläche „📦 WaWi") aus Kasse und Kiosk erreichbar.

---

## Login

Die WaWi bietet zwei Anmeldearten:

### Kartenlogin (Barcode-Scan)
Standardmäßig ist der Tab **„Karte scannen"** aktiv. Mitarbeiterausweis vor den Barcode-Scanner halten – die Anmeldung erfolgt automatisch. Es werden nur Mitarbeiterkarten akzeptiert (KARTEN.TYP='M').

### Passwort-Login mit Touch-Tastatur
Tab **„Passwort"** wählen. Benutzername und Passwort eingeben – bei Bedarf über die eingeblendete Touch-Tastatur (QWERTZ-Layout). Shift (⇧) für Großbuchstaben, Backspace (⌫) zum Löschen, OK zum Absenden.

Nach dem Login erscheint das Dashboard.

---

## Sidebar-Navigation

| Bereich | Seite | Beschreibung |
|---------|-------|-------------|
| Dashboard | `/` | Tageseinnahmen, Monatsumsatz, offene Vorgänge |
| Stammdaten → Artikel | `/wawi` | Artikelsuche & Detailansicht |
| Stammdaten → Preispflege | `/wawi/preispflege` | EK / VK5 / Faktor aller aktiven Artikel (N/F/S) |
| Buchhaltung → Datev-Export | `/wawi/datev-export` | DATEV-Buchungsstapel erzeugen, herunterladen und prüfen |
| Weitere → Reporting | `/reporting` | CFO-Reports: MwSt, Warengruppen-Umsatz |

---

## Preispflege (HAB-235)

Unter **Stammdaten → Preispflege** werden alle aktiven Artikel angezeigt – Normal (N), Freie (F) und Stückliste (S). Gelöschte und VK-gesperrte Artikel werden ausgeschlossen.

### Spalten

| Spalte | Bedeutung |
|--------|-----------|
| Art-Nr. | CAO-Artikelnummer |
| Typ | Artikeltyp: N (Normal), F (Frei), S (Stückliste) |
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

## DATEV-Export (`/wawi/datev-export`) (HAB-372)

Erreichbar über Sidebar → **Buchhaltung → Datev-Export** oder direkt unter `/wawi/datev-export`.

### Funktion

Erzeugt einen DATEV-kompatiblen Buchungsstapel (CSV) aus den CAO-Faktura-Daten für einen gewählten Monat. Die Datei kann direkt in DATEV importiert werden.

### Export auslösen

1. **Monat** und **Jahr** über die Dropdowns auswählen.
2. **„Export generieren"** klicken.
3. Bei Erfolg: Vorschau-Tabelle wird angezeigt. Die Datei erscheint in der Dateiliste unten.
4. Bei Fehler (z. B. keine Buchungen im Zeitraum): Fehlermeldung in Rot.

### Dateiliste

Alle erzeugten Export-Dateien werden unterhalb des Formulars aufgelistet:

| Spalte | Bedeutung |
|--------|-----------|
| Dateiname | `habadola2datev_YYYY-MM_as-of_TIMESTAMP.csv` |
| Zeitraum | Exportierter Monat/Jahr |
| Erstellt | Erzeugungszeitpunkt |
| Größe | Dateigröße in KB |
| Aktionen | **Vorschau** (tabellarische Ansicht) und **Download** |

### Tabellarische Vorschau

Klick auf **Vorschau** zeigt den Inhalt der Export-Datei als scrollbare Tabelle an. So lassen sich die Buchungen vor dem DATEV-Import kontrollieren.

### Aufbau der Export-Datei

Die CSV-Datei ist **Tab-getrennt**, **UTF-8** kodiert (ohne BOM) und verwendet **CR** (`\r`) als Zeilenende.

#### Spalten

| Spalte | Beschreibung |
|--------|-------------|
| Waehrungskennung | Immer `EUR` |
| SollHabenKennzeichen | `S` (Soll) oder `H` (Haben) |
| Umsatz | Betrag mit Komma als Dezimaltrenner (z. B. `123,45`) |
| BUSchluessel | DATEV-Buchungsschlüssel (leer bei Automatikkonten) |
| Gegenkonto | FiBu-Gegenkonto |
| Belegfeld1 | Belegnummer (VRENUM, BELEGNUM o. Ä.) |
| Belegfeld2 | (leer) |
| Datum | Buchungsdatum im Format `TTMM` |
| Konto | FiBu-Konto |
| Kostfeld1 | Kostenstelle (= Gegenkonto) |
| Kostfeld2 | (leer) |
| Kostmenge | (leer) |
| Skonto | Skontobetrag falls vorhanden |
| Buchungstext | Beschreibung der Buchung (s. u.) |
| Festschreibung | DATEV-Festschreibungskennzeichen |

#### Buchungsteile und Buchungstexte

Der Export setzt sich aus mehreren Buchungsteilen zusammen, die per SQL-UNION verknüpft werden:

| Teil | Buchungsart | Buchungstext-Muster | Beispiel |
|------|------------|---------------------|----------|
| 1a–1d | Lieferantenrechnungen (0/19/7/7,8 %) | `Name ORGNUM MwSt%` | `Molkereivertrieb Miesbach 1120762 0%` |
| 1e | Versorger-Rechnungen (Kundengruppe 998) | `Name* VRENUM Beschreibung` | `Stadtwerke Weilheim* 5012 Strom Jan` |
| 2 | Lieferantenzahlungen | `VERW_ZWECK` (bei Umbuchung: + Partnername) | `Rechnung 1120762` |
| 3a–3c | Kundenrechnungen (0/19/7 %) | `Name MwSt%` | `Mustermann 19%` |
| 4 | Kundenzahlungen | `VERW_ZWECK` | `Ausgleich Rechnung 5001` |
| 5a–5c | Lieferanten-Tagesaggregate (0/19/7 %) | `TTMM-Konto-MinVRENUM-MaxVRENUM` | `1503-70010-4980-4985` |
| 6 | Kassenzahlungen | `GV_TYP TTMM` (Gegenkonto bedingt: Geldtransit → 1360, sonst FiBu-Gegenkonto) | `Bareinzahlung 1503` |
| 7a–7c | Kunden-Tagesaggregate (0/19/7 %) | `TTMM-Konto-MinVRENUM-MaxVRENUM` | `1503-10010-6001-6012` |
| 8 | SB-Einzahlungen (Hibiscus) | `kommentar` oder `SB-Einzahlung id` | `SB-Einzahlung 4521` |
| 9a | TELECASH-Kartenzahlungen (Hibiscus) | `Kartennummer` (ab Position 9 im Zweck) | `5432XXXXXXXX1234` |
| 9b | First-Data-Kartenzahlungen (Hibiscus) | `Kartentyp` (aus Zweck extrahiert) | `VISA` |

#### Filterung

- **Storno-Buchungen** werden bei Lieferantenrechnungen über `STADIUM < 125` und bei Zahlungen über `STORNO = 0` gefiltert.
- **Nullumsatz-Einträge** (Umsatz = `0,00`) werden automatisch übersprungen, da DATEV diese beim Import als Fehler behandelt.

#### Datenquellen

- Teile 1–7: CAO-Faktura-Tabellen (`JOURNAL`, `JOURNALPOS`, `ZAHLUNGEN`, `ADRESSEN`)
- Teile 8–9: Hibiscus-Banking-Tabelle (`hibiscus.umsatz`) – der DB-User benötigt Lesezugriff auf das `hibiscus`-Schema.

### Speicherort

Export-Dateien werden unter `wawi-app/app/datev_exports/` gespeichert (gitignored). Pro Export wird eine neue Datei mit Zeitstempel im Namen angelegt.

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
