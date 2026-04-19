# Benutzerhandbuch – WaWi (Warenwirtschaft)

**Version:** 0.6.0
**Stand:** 2026-04-19
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
| Personal → Mitarbeiter | `/wawi/personal/` | Mitarbeiter-Stammdaten, Arbeitszeit, Urlaub, Stempel |
| Personal → Schichtplan | `/wawi/personal/schichtplan` | Wochenplan-Matrix und Zeitraster |
| Personal → Schichten | `/wawi/personal/schichten` | Schicht-Stammdaten und Pausenregelung |
| Buchhaltung → Datev-Export | `/wawi/datev-export` | DATEV-Buchungsstapel erzeugen, herunterladen und prüfen |
| Weitere → Reporting | `/reporting` | CFO-Reports: MwSt, Warengruppen-Umsatz |
| Temperatur → HACCP | `/wawi/haccp` | Temperaturüberwachung, Sichtkontrolle, Alarme |

---

## Temperaturüberwachung / HACCP (`/wawi/haccp`)

Das HACCP-Modul überwacht Kühl- und Tiefkühlgeräte über TFA.me-Cloud-Sensoren. Es dokumentiert die Temperaturkette lückenlos, alarmiert bei Abweichungen und bildet die tägliche Sichtkontrolle als geführten Workflow ab.

### Dashboard-Widgets auf der WaWi-Startseite

Auf der WaWi-Startseite (`/`) erscheinen zwei HACCP-Ampel-Widgets, sobald das Modul konfiguriert ist:

| Widget | Ampel grün | Ampel gelb | Ampel rot |
|--------|-----------|-----------|-----------|
| **🌡️ Temperaturstatus** | Alle Sensoren im Soll | Sensor offline oder Batterie schwach | Offener Temperatur-Alarm |
| **✅ Sichtkontrolle heute** | Alle Geräte quittiert | – | Nicht alle Geräte quittiert |

Jedes Widget hat einen Direktlink auf das jeweilige Teildashboard (`HACCP öffnen →` bzw. `Jetzt quittieren →`).

### HACCP-Hauptseite (`/wawi/haccp`)

Zeigt je Gerät eine Kachel mit:
- aktueller Temperatur und Zeitpunkt des letzten Messwerts,
- Soll-Bereich (Min/Max) und Karenzzeit,
- Sichtkontroll-Status (heute quittiert / offen),
- Status-Farbe: `ok` (im Soll), `warn` (20 %-Puffer zur Grenze), `alarm` (überschritten), `offline` (Messwert älter als STALE_MIN).

Oben auf der Seite: Liste der offenen Alarme und ein **Multi-Sensor-Chart** (alle Kurven übereinander, Farbe per Golden-Angle-Hue für maximale Unterscheidbarkeit).

#### Historie nachladen

Button **„Historie nachladen"** holt fehlende Messwerte aus der TFA-Cloud (max 7 Tage zurück — API-Limit). Wird idempotent eingespielt; Duplikate werden an der `UNIQUE(GERAET_ID, ZEITPUNKT_UTC)`-Sperre verworfen. Der Rate-Limit der TFA-API ist 10 Calls/h.

### Sichtkontrolle (`/wawi/haccp/sichtkontrolle`)

Tägliche Sichtkontrolle für alle Geräte auf einer Seite. Pro Gerät genügt ein Tap/Klick in die Checkbox; optional eine Sammelbemerkung. **„Alle quittieren"** schließt die Tageskontrolle in einem Rutsch ab. Einmal quittiert, verschwindet das Gerät aus der Liste der offenen.

### Gerätedetail (`/wawi/haccp/<id>`)

Pro Gerät:
- **Stammdaten:** Name, Standort, Warengruppe, aktiv-ja/nein, letzte Kalibrierung.
- **Grenzwerte** (versioniert): Temp-Min/Max, Karenzzeit (Minuten), Stale-Minuten, optional Drift-Überwachung. Jede Änderung legt eine neue Version an — nötig für die HACCP-Audit-Historie.
- **Zeitreihen-Chart:** Temperatur + Feuchte, Zeitraum per Datepicker wählbar (deutsches Format `TT.MM.JJJJ`). Zeitachse im 24h-Format, y-Achse eine Nachkommastelle.
- **Alarm-Historie:** Zeigt alle alten und offenen Alarme mit Korrekturmassnahmen.
- **CSV-Export:** Messwerte im gewählten Zeitraum als UTF-8-BOM-CSV (Excel-kompatibel).
- **Einzel-Backfill:** Nur dieses Gerät nachladen.

### Alarme

Das System kennt fünf Alarm-Typen, jeweils mit eigenem Auslöse-Kriterium:

| Typ | Code | Auslöser |
|-----|------|----------|
| Temperatur zu hoch | `temp_hoch` | Messwert über `MAX` länger als `KARENZ_MIN` Minuten |
| Temperatur zu tief | `temp_tief` | Messwert unter `MIN` länger als `KARENZ_MIN` Minuten |
| Drift | `drift` | Abweichung vom Rolling-Median > `DRIFT_K` anhaltend ≥ `KARENZ_MIN` Minuten |
| Sensor offline | `offline` | Kein Messwert seit mehr als `STALE_MIN` Minuten |
| Batterie schwach | `battery` | Sensor meldet `LOW_BATT` — ohne Karenzzeit, sofort |

Absolut-Alarme (`temp_hoch`/`temp_tief`) haben Vorrang vor `drift` — kippt die Temperatur ins rote Band, wird der Drift-Alarm automatisch geschlossen und durch den Absolut-Alarm ersetzt.

#### Ablauf der Eskalation

1. **Alarm öffnet**, sobald das Auslöse-Kriterium erfüllt ist.
2. **Stufe 1** (DELAY_MIN=0 → sofort, sonst nach Delay): Mail an die erste Empfängerstufe der Alarmkette.
3. **Stufe 2 / 3**: Weitere Eskalation, wenn der Alarm nach Stufe-n-Delay noch offen ist.
4. **Alarm schließt automatisch**, sobald der Messwert mindestens `ABSCHLUSS_KARENZ_MIN` Minuten (Default 10) durchgängig wieder im Soll liegt. Einzelne „gute" Messwerte nach einer Überschreitung reichen nicht — das verhindert Flattern bei Temperaturen knapp an der Grenze.

**Pflichtfeld Korrekturmassnahme:** Jeder geschlossene Alarm muss mit einem Eintrag dokumentiert werden (`Alarme → Korrekturmassnahme eintragen`). Ohne diesen Eintrag bleibt der Alarm in der Liste „zu dokumentieren" sichtbar.

#### Was ist ein Drift-Alarm?

Beispiel: Ein Kühlschrank ist auf 4 °C eingestellt, Grenzwert `MAX = 7 °C`. Über Wochen liegt der Tagesdurchschnitt bei 4,2 °C. Wenn der Kompressor zu schwach wird oder die Dichtung schleicht, steigt die Temperatur langsam an — etwa auf 5,8 °C. Das ist **noch unter dem Grenzwert**, löst also keinen Absolut-Alarm aus. Ein absoluter Ausfall bliebe unbemerkt, bis die 7 °C wirklich überschritten wären — und dann ist die Ware womöglich schon warm geworden.

Der Drift-Check schaut deshalb zusätzlich auf die **Veränderung gegenüber dem Normalbetrieb**:

- `DRIFT_FENSTER_H` (Default **24 Stunden**): Aus den Messwerten der letzten N Stunden wird der **rolling Median** berechnet.
- `DRIFT_K` (Beispiel **2,0 °C**): Zulässige Abweichung des aktuellen Werts vom Median.
- `KARENZ_MIN`: Abweichung muss **durchgängig** so lange bestehen, bevor der Alarm feuert (verhindert Fehlalarme beim Öffnen der Tür).

Im Beispiel: Median der letzten 24 h = 4,2 °C, aktueller Wert 5,8 °C → Abweichung 1,6 °C → noch unter `DRIFT_K` → kein Alarm. Steigt die Temperatur auf 6,5 °C (Abweichung 2,3 °C) und bleibt dort 15 Minuten, öffnet ein `drift`-Alarm — **bevor** der absolute Grenzwert überschritten ist.

Die Drift-Überwachung ist **pro Gerät optional** (`DRIFT_AKTIV`-Flag in den Grenzwerten). Für Geräte mit stark schwankender Grundlast (z. B. Verkaufskühltruhen mit häufigem Türöffnen) ist sie oft nicht sinnvoll und kann abgeschaltet werden.

### Alarmkette (`/wawi/haccp/alarmkette`)

Pflege der E-Mail-Empfänger pro Stufe. Jeder Eintrag: Stufe (1/2/3), Name, E-Mail, Verzögerung in Minuten.

### HACCP-Poller (Daemon)

Ein Hintergrund-Daemon (`modules.haccp.poller`) zieht im konfigurierten Intervall (`HACCP_POLL_INTERVALL_S`, Default 120 s) die aktuellen Messwerte aller TFA-Sensoren, persistiert sie idempotent und evaluiert die Alarmlogik.

#### Start / Stop / Status

Über `dorfkern-ctl`:

```bash
./dorfkern-ctl start haccp-poller     # nur den Poller starten
./dorfkern-ctl stop haccp-poller      # Poller stoppen
./dorfkern-ctl restart haccp-poller   # Poller neu starten
./dorfkern-ctl status                 # Status aller Apps inkl. Poller
```

Die Installationsroutine bietet den Poller ab Werk als opt-in an (Phase 4), sofern `TFA_API_KEY` in der Konfiguration gesetzt ist.

#### Auto-Backfill nach Ausfall

Beim Start prüft der Poller den letzten erfolgreichen Heartbeat (`XT_HACCP_POLLER_STATUS.LAST_SUCCESS_AT`):

- **Kein Heartbeat** → Erstlauf, nichts nachholen.
- **Heartbeat < 15 min** → normaler Restart, nichts nachholen.
- **Heartbeat älter** → Lücke seit letztem Heartbeat aus der Cloud ziehen, gekappt auf das API-Limit von 7 Tagen (ältere Lücken sind in der TFA-Cloud nicht mehr rekonstruierbar). Bei längeren Ausfällen chunked der Backfill automatisch in 7-Tages-Blöcke.

Fehler beim Backfill werden geloggt, blockieren aber nicht den Start des normalen Poll-Zyklus.

#### Watchdog

Zusätzlich steht `modules.haccp.watchdog` zur Verfügung (cron-tauglich): Prüft minütlich, ob der Heartbeat älter als ein Grenzwert ist, und verschickt dann eine Mail an die Alarmkette-Stufe 1.

```bash
# Beispiel cron-Eintrag:
* * * * * cd /opt/cao-xt && .venv/bin/python3 -m modules.haccp.watchdog --max-alter-min 10 --cooldown-min 60
```

### Konfiguration

In `wawi-app/app/config.py` (oder `config_local.py` / ENV):

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `TFA_API_KEY` | *(leer)* | Account-Key für die TFA.me-Cloud-API. Pflicht. |
| `TFA_BASE_URL` | `https://go.tfa.me` | API-Basis-URL (nur für Tests ändern). |
| `HACCP_POLL_INTERVALL_S` | `120` | Poll-Zyklus des Daemons in Sekunden. |

### Sensor-Verwaltung

Neue Sensoren werden vom Poller beim ersten empfangenen Messwert **automatisch angelegt** (Auto-Discovery) — Name, Standort und Warengruppe können dann im UI nachgepflegt werden. Ebenso spiegelt der Poller bei jedem Zyklus die TFA-Metadaten (interne ID, Gerätename, Messintervall) in die lokale Datenbank, sofern sie sich geändert haben.

### HACCP-Rechtsgrundlagen

Die Temperaturüberwachung setzt folgende Vorschriften um:

- **VO (EG) Nr. 852/2004 (EU-Lebensmittelhygieneverordnung), Art. 5:** Verpflichtet Lebensmittelunternehmer zur Einrichtung, Durchführung und Aufrechterhaltung von Verfahren, die auf den **HACCP-Grundsätzen** beruhen.
- **HACCP – Hazard Analysis and Critical Control Points (7 Grundsätze):**
  1. Gefahrenanalyse durchführen
  2. Kritische Kontrollpunkte (CCP) festlegen
  3. Grenzwerte für jeden CCP definieren
  4. Überwachung der CCPs einrichten
  5. Korrekturmaßnahmen festlegen
  6. Verifizierung (regelmäßige Überprüfung des Systems)
  7. Dokumentation und Aufzeichnungen führen
  Die Temperaturkette der Kühl-/Tiefkühlgeräte ist im Dorfladen ein typischer CCP — Abweichungen können direkt zu Gesundheitsgefahren (Keimwachstum) führen.
- **DIN 10508 („Temperaturen für Lebensmittel"):** Empfiehlt branchenübliche Richtwerte, z. B.:
  - Tiefkühlkost: ≤ −18 °C
  - Speiseeis: ≤ −18 °C (bei Abgabe ≤ −10 °C zulässig)
  - Frisches Fleisch: ≤ +7 °C (Geflügel ≤ +4 °C, Hackfleisch ≤ +2 °C)
  - Milch und Milcherzeugnisse: ≤ +8 °C (Rohmilch +6 °C)
  - Feinkost, leicht verderblich: ≤ +7 °C
- **LMHV (Lebensmittelhygiene-Verordnung, DE):** Nationale Umsetzung; verlangt die **lückenlose Einhaltung der Kühlkette** und die Dokumentation bei abgabefähigen Lebensmitteln.
- **Dokumentationspflicht:** Aufzeichnungen über Temperatur-Monitoring und Korrekturmaßnahmen müssen in der Regel **mindestens 1 Jahr** (bei langer Haltbarkeit auch länger) aufbewahrt werden. Das HACCP-Modul speichert Messwerte, Alarme und Korrekturmassnahmen revisionssicher in der Datenbank — ein Export für das Lebensmittelkontrollamt ist jederzeit möglich (CSV pro Gerät im Gerätedetail).

Das Modul deckt dabei explizit die Grundsätze 3 (Grenzwerte), 4 (Überwachung), 5 (Korrekturmaßnahmen) und 7 (Dokumentation) ab. Grundsätze 1, 2 und 6 (Gefahrenanalyse, CCP-Festlegung, Verifizierung) bleiben organisatorisch — sie sind Teil des HACCP-Konzepts des Dorfladens und werden nicht vom System ersetzt.

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

---

## Personal (`/wawi/personal`)

Das Personalmodul verwaltet Mitarbeiter-Stammdaten, Arbeitszeiten, Urlaub, Schichtplanung und Auswertungen komplett unabhängig von CAO.MITARBEITER (eigene `XT_PERSONAL_*`-Tabellen mit GoBD-konformem Änderungsprotokoll). Zugriff haben alle Mitarbeiter der CAO-Gruppen „Administratoren" oder „Ladenleitung".

### Mitarbeiter-Übersicht

Die Startseite (`/wawi/personal/`) zeigt alle Mitarbeiter in einer Tabelle. Toggle **„Nur aktive / Auch Ausgetretene"** blendet ausgetretene MA ein/aus; die Auswahl wird pro Browser-Session gemerkt. Klick auf eine Zeile öffnet das Detail.

### Mitarbeiter-Detail

Der Detailbildschirm ist in Karten gegliedert:

| Karte | Inhalt |
|-------|--------|
| **Stammdaten** | Personalnummer, Kürzel, Name, Geburtstag, Adresse, Kontakt, Eintritt/Austritt |
| **Stundensatz** | Append-only Historie aller Stundensätze (EUR brutto/Stunde, gültig ab) |
| **Arbeitszeit** | Versionierte AZ-Modelle (s. u.) |
| **Urlaub** | Jahres-KPI und Urlaubsanträge (s. u.) |
| **Abwesenheit** | Krank, Fortbildung, Sonstiges (s. u.) |
| **Stempel** | Übersicht der Stempeluhr-Buchungen |
| **Arbeitszeitkonto** | Soll/Ist-Saldo pro Monat und kumuliert |
| **Änderungsprotokoll** | Lückenloses GoBD-Log aller Änderungen (Stammdaten, AZ, Urlaub) |

Neuanlage über Button **„+ Neu"** auf der Übersicht. Geburtsdatum nutzt den Jahr-/Monats-Sprung-Datepicker (Geburtstag eines 80-Jährigen in 4 statt ~1000 Klicks erreichbar).

### Arbeitszeitmodelle und Lohnart

Jeder Mitarbeiter hat eine Historie von Arbeitszeitmodellen (`XT_PERSONAL_AZ_MODELL`), jedes mit:

- **Lohnart:** Minijob, Teilzeit, Vollzeit, Werkstudent, Aushilfe, Azubi
- **Wochen- oder Monatsstunden** (Woche ↔ Monat = 4,33)
- **Optionale Wochenverteilung** Mo–So (in Stunden pro Tag)
- **Jahresurlaubstage**
- **Gültig ab** (Zeitachse, Vorgänger wird beim Speichern automatisch auf `neu_ab − 1 Tag` gekürzt)

**Live-Minijob-Warnung:** Beim Bearbeiten zeigt die Seite via AJAX, ob die geplante Monatssumme (Stunden × Stundensatz) die aktuell gültige Minijob-Grenze überschreitet. Die Grenze ist versioniert pro Jahr gepflegt (Default: Mindestlohn × 130 / 3); für 2026 z. B. **603 €**.

### Urlaub

Die Urlaubs-Karte zeigt eine KPI-Zeile pro Jahr:

```
Anspruch + Korrektur = Gesamt − Geplant − Genehmigt − Genommen = Rest
```

- **Anspruch** stammt aus `URLAUB_JAHR_TAGE` des zum **01.07.** gültigen AZ-Modells.
- **Korrekturen** sind append-only Buchungen (z. B. Übertrag Vorjahr, unterjährige Anpassung) mit Pflicht-Begründung.
- **Anträge** durchlaufen den Workflow `geplant → genehmigt → genommen` (plus terminal `abgelehnt`/`storniert`).
- **Arbeitstage** pro Antrag werden anhand der Wochenverteilung des gültigen AZ-Modells berechnet (Fallback Mo–Fr).
- **Auto-Abschluss:** Anträge mit Status `genehmigt` und BIS-Datum vor heute wechseln beim Öffnen der Detailseite automatisch auf `genommen`.

Jahr-Umschalter oben (Vorjahr / aktuell / Folgejahr). Rest-Tage werden rot angezeigt, wenn negativ.

### Abwesenheiten

Krank-, Fortbildungs- und sonstige ganztägige Abwesenheiten werden separat erfasst und wirken auf das Arbeitszeitkonto als volle Soll-Stunden (der Tag gilt als erfüllt, auch ohne Stempel). Ein Abwesenheits-**Kalender** bietet die Team-Sicht: alle MA übereinander, farbcodiert pro Typ, mit Filter nach Monat und Typ.

### Stempeluhr (Übersicht im WaWi)

Die Buchungen der Kiosk-Stempeluhr landen in `XT_PERSONAL_ZEITEN`. In der Mitarbeiter-Detailkarte **Stempel** sieht die Ladenleitung:

- alle Stempel-Paare (Kommen/Gehen) pro Tag inkl. Dauer,
- manuell erfasste Korrekturen (mit Begründung und Ersteller),
- Abbau-Korrekturen (Plus-/Minusstunden) mit Datum und Grund,
- unvollständige Paare (Kommen ohne Gehen oder umgekehrt) in rot mit Handlungshinweis.

Korrektur- und Abbau-Buchungen können in dieser Ansicht manuell nachgetragen werden.

### Arbeitszeitkonto und Stundenzettel

Die Karte **Arbeitszeitkonto** zeigt Soll (aus dem AZ-Modell), Ist (Summe aus Stempel + Urlaub + Krank + Feiertag + Korrekturen) und den Saldo pro Monat sowie kumuliert über das Jahr.

**Stundenzettel als PDF:** Pro Monat lässt sich ein Stundenzettel exportieren. Die PDF enthält:

- Tages-Tabelle mit Spalten Arbeit, Abwesenheit, Urlaub, Krank, Abbau, Feiertag, Bemerkung
- **Summenzeile** als letzter Eintrag der Tabelle
- Monats-Summary rechts: `Gesamt − Soll + Korrekturen = Saldo aktueller Monat`, dazu `Saldo Vormonate` und `Saldo kumuliert` (fett, mit feiner/starker Linie hervorgehoben)
- Block **Arbeitszeit an Sonntagen / Feiertagen** (als separater Zusatz-Ausweis, nicht doppelt gezählt)

Die Saldo-Berechnung zählt **Abbau-Korrekturen** nur einmal (über `korrektur_monat_min`, nicht über `gesamt`), damit Vorzeichen und Kumulierung stimmen. `Saldo kumuliert` = Saldo aller Vormonate + Saldo aktueller Monat.

### Schichten (`/wawi/personal/schichten`)

Stammdaten der möglichen Schicht-Blöcke. Drei Typen:

| Typ | Beispiel | Zeitbezug |
|-----|----------|-----------|
| **fix** | Frühdienst 06:00–13:00 | Fixe Anfangs-/Endzeit, inkl. Nachtschicht |
| **flex** | Buchhaltung, Reinigung | Freie Zeiteinteilung, Dauer pro Zuordnung |
| **aufgabe** | Kassenabschluss, Bestellung | Ohne Zeitbezug, nur „erledigt"-Marker |

Jeder Typ hat eine eigene Farbe in der Plan-Matrix; Aufgaben-Schichten sind zusätzlich mit Diagonalstreifen markiert.

**Pausenregelung** (versioniert, nach ArbZG §4): Schwellen 6 h → 30 min, 9 h → 45 min; Pause kann als bezahlt oder unbezahlt konfiguriert werden. Wirkt automatisch auf die Ist-Stunden-Anzeige im Schichtplan (brutto vs. netto).

### Schichtplan – End-to-End-Workflow

Typische Wochenplanung im Dorfladen (Beispiel: Ladenleitung plant KW 17 für 8 Mitarbeiter):

1. **Vorbereitung (einmalig pro Saison):**
   - Schicht-Stammdaten unter `Schichten` anlegen: *Frühdienst* (06:00–13:00, fix), *Spätdienst* (13:00–20:00, fix), *Buchhaltung* (flex), *Kassenabschluss* (aufgabe), …
   - Pausenregelung einmalig hinterlegt (Default reicht meist).

2. **Plan öffnen:** `Personal → Schichtplan` → aktuelle KW oder Ziel-KW auswählen (Kalender). Matrix zeigt MA × Mo–So, leere Zellen hellgrau.

3. **Zuordnungen anlegen:**
   - Klick auf eine Zelle öffnet das **Bottom-Sheet-Overlay**.
   - Button-Grid zeigt alle Schichttypen (farbig). Auswahl setzt den Schichtblock.
   - Bei Flex-Schichten: Quick-Buttons 1 h / 1½ h / 2 h / 3 h / 4 h / 5 h / 8 h oder manuelle Dauer über Numpad.
   - Bei Aufgaben: reines Anklicken genügt, Dauer fließt nicht ins Ist ein.

4. **Zeitraster-Ansicht prüfen:** Umschalten auf `Schichtplan → Zeitraster`. Y-Achse = Uhrzeit (50 px/h — typischer 6–20-Uhr-Tag passt ohne Scrollen), X-Achse = Wochentage. Fix-Schichten erscheinen als positionierte Blöcke; mehrere MA auf derselben Schicht werden als Liste (Vorname + Nachname-Initial) im Block ausgegeben. Flex-/Aufgaben-Zuordnungen darunter in getrennten Listen.

5. **Bearbeiten:**
   - In der Matrix: Klick auf einen Schicht-Chip → Overlay mit allen MA der Schicht (entfernen oder weiteren zuordnen).
   - Bereits zugeordnete MA sind im Dropdown „Weiteren zuordnen" ausgeblendet.

6. **Konfliktprüfung:**
   - Die KPI-Spalte pro MA zeigt `Ist / Soll` (netto nach Pausenabzug) plus Zusatzzeile brutto.
   - Urlaub und Eintritts-/Austritts-Konflikte werden beim Zuordnen als Warnung gezeigt, die Zuordnung aber trotzdem angelegt (Planer entscheidet).

7. **Kopieren aus Vorwoche (optional):**
   - Status-Bar → **„Kopieren…"** → Ziel-KW wählen (Default nächste KW, Schnell-Buttons +1/+2/+4 Wochen).
   - Ziel-KW muss leer, in der Zukunft und nicht freigegeben sein.
   - Urlaubs-Konflikte werden als Hinweise aufgelistet, der Planer nacharbeitet.

8. **Vorlage speichern/anwenden (optional):**
   - Status-Bar → **„Vorlagen…"** → aktuelle Woche unter frei wählbarem Namen speichern (kalenderunabhängig, Wochentage 0–6).
   - Später: Vorlage auswählen → Ziel-KW → Anwenden. Gleiche Regeln wie beim Kopieren.

9. **Freigabe:** Button **„Woche freigeben"** in der Status-Bar.
   - Status wechselt auf `freigegeben`, Matrix wird ausgegraut, `×`-Buttons verschwinden.
   - Jeder zugeordnete MA mit hinterlegter E-Mail erhält automatisch seinen persönlichen Wochen-Schichtplan als Mail (Plain + HTML, Reply-To = Freigebender).
   - Im **Dev-Modus** (`DEVMODE=1` in CAO-REGISTRY) gehen alle Mails an den Freigebenden selbst mit `[DEV]`-Prefix.
   - Log-Eintrag `freigegeben` mit Zeitpunkt und Freigeber-Name.

10. **Nacharbeit:** Button **„Entsperren"** erlaubt Änderungen nach Freigabe; anschließend erneute Freigabe möglich. Log behält die Historie.

Die SMTP-Konfiguration wird primär aus der CAO-REGISTRY (`MAINKEY='MAIN\EMAIL'`) gelesen, mit Fallback auf `XT_EMAIL_*`-ENV und `[Email]`-Sektion in `caoxt.ini`. Bei leerem SMTP blockiert die Freigabe nicht — sie läuft ohne Mail-Versand durch.
