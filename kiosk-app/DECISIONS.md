# Habacher Dorfladen Kiosk – Projektdokumentation

**Letzte Aktualisierung:** 26.03.2026 (App-Update-Verwaltung, Mitarbeiter-Handbuch)

> ⚠️ **Pflicht zur Aktualität**
> Diese Datei ist die zentrale Architekturdokumentation des Projekts.
> **Jede Änderung an Design-Entscheidungen, Parametern, Routen, DB-Schema oder
> Terminal-Rollen muss hier sofort eingetragen werden** – idealerweise im gleichen
> Commit wie der zugehörige Code. Veraltete Dokumentation ist schlimmer als keine.

---

## Hardware

### Raspberry Pi 5 (Hauptgerät)
- RAM: 4 GB oder 8 GB, Speicher: microSD A2 oder NVMe/PCIe-HAT+
- Läuft Flask + Chromium, verbindet sich mit MariaDB und Drucker

### Weitere Terminals (optional)
- Beliebige Geräte mit modernem Browser im LAN
- Terminal-Nr per Cookie gesetzt (1–9), kein Python nötig

### Touchscreen: Pisichen HD-160
- 16 Zoll IPS, 2560×1600 (2,5K), 144 Hz, 10-Punkt-Touch USB-HID
- Anschluss: HDMI + Micro-HDMI-Adapter + USB für Touch

### Bondrucker: Bisofice POS-8370
- LAN (Ethernet), TCP/IP Port 9100, feste IP per DHCP-Reservierung
- 80 mm Papier (Breite je nach Papiertyp variiert), Auto-Cutter vorhanden
- ESC/POS – Ansteuerung direkt per Raw-Socket (kein python-escpos)
- CP437-Encoding, Umlaute → ASCII-Digraphen (ä→ae etc.)
- Drucker-IP in DB-Tabelle `drucker` gepflegt, nicht in config.py
- Hinweis: Ökopapier (beige/recycled) kann Sensor-Probleme verursachen
  → Weißes Standard-Thermopapier empfohlen

---

## Software

- OS: Raspberry Pi OS Bookworm (Debian 12, 64-bit), Wayland/Labwc
- Python 3.11+ → Aufruf: python3 / pip3
- Abhängigkeiten: flask, mysql-connector-python (kein python-escpos!)
- Architektur: Flask (Port 5001) + Chromium Kiosk
- Schriften: Lobster (Überschriften/Preise), Nunito (Rest), via Google Fonts
- Farben: Habacher Dorfladen Grün/Gold-Schema

---

## Kassensystem

- CAO Faktura / CAO-Kasse Pro
- Sammelartikel "Backwaren": ARTNUM 7408, WARENGRUPPE='101'
- Preis aus EAN-Barcode (PPPPP-Stellen), nicht aus Artikelstamm
- Scanner: HID/Keyboard-Emulation
- REC_ID (int) = echter PK in CAO → Join-Schlüssel in allen Views
- ARTNUM (varchar) = nur Anzeige, nicht als ID verwenden

---

## Barcode-Format

Inhouse-EAN-13 (1D), Format: XX AAAAZ PPPPPZ (13 Stellen)
  XX    = 21 (Bereichscode, fest)
  AAAA  = 7408 (Sammelartikel Backwaren, fest)
  Z     = Prüfziffer des Artikelteils
  PPPPP = Gesamtpreis Warenkorb in Cent
  Z     = EAN-13-Prüfziffer (errechnet)
Barcode enthält NUR Gesamtpreis. Einzelpositionen nur auf Bon.

---

## Datenhaltung

- Server: MariaDB (<DB_HOST>:<DB_PORT>)
  Im Produktivbetrieb lokale LAN-IP verwenden!
- Benutzer: <DB_USER> / <DB_PASSWORD>
- Unsere DB: Backwaren
- CAO-DB: cao_2018_001, Tabelle ARTIKEL
- Felder: REC_ID (PK), ARTNUM, KURZNAME, VK5B (Preis Euro), WARENGRUPPE
- Filter: WARENGRUPPE = '101' – CAO ist maßgeblich
- VK5B in Euro, Konvertierung: ROUND(VK5B * 100) = Cent

### Datenbankbenutzer einrichten

  CREATE USER 'kiosk_user'@'%' IDENTIFIED BY 'PASSWORT';
  GRANT SELECT ON cao_2018_001.* TO 'kiosk_user'@'%';
  GRANT SELECT, INSERT, UPDATE, DELETE, CREATE VIEW ON Backwaren.* TO 'kiosk_user'@'%';
  FLUSH PRIVILEGES;

---

## Datenbankschema (DB: Backwaren)

T0:  drucker              – id, name, ip_adresse, port, standard, aktiv
T0b: terminal_drucker     – terminal_nr (1-9) → drucker_id
T1:  kategorien           – id, name, sort_order
     1 Brot, 2 Semmeln, 3 Baguette/Sonstiges,
     4 Vorbestellbar, 5 Süßes-Kuchen, 6 Süßes-Gebäck
T2:  produkte             – id (=REC_ID), kategorie_id (NULL=Sonstige),
                            bild_pfad, einheit (ENUM), wochentage (VARCHAR20),
                            zutaten (TEXT), aktiv (0/1/2), hinweis
T3:  warenkoerbe          – id, erstellt_am, geaendert_am, status (offen/
                            geparkt/abgebrochen), gesamtbetrag_cent,
                            gesperrt_von (1-9), gesperrt_am,
                            erstellt_von (1-9, zuletzt bearbeitendes Terminal)
T4:  warenkorb_positionen – warenkorb_id, produkt_id, name_snapshot,
                            preis_snapshot_cent, menge, zeilen_betrag_cent
T5:  journal_warenkoerbe  – autarkes Archiv, kein FK auf warenkoerbe,
                            warenkorb_id, terminal_nr, gebucht_am,
                            gesamtbetrag_cent, ean_barcode,
                            bon_text (TEXT), bon_data (LONGBLOB),
                            status (gebucht/storniert), storniert_am
T6:  journal_positionen   – journal_id FK, snapshots
T7:  bestellungen         – id, bestell_nr (B-YYYY-NNNN), name, telefon,
                            typ (einmalig/wiederkehrend), abhol_datum,
                            wochentag (Mo…So), start_datum, end_datum,
                            abhol_uhrzeit, status (offen/gedruckt/storniert),
                            gedruckt_datum (letztes Druckdatum – täglich reset
                            bei wiederkehrend), kanal (kiosk/…), notiz,
                            zahlungsart (sofort/abholung), ean_barcode VARCHAR(13),
                            bon_data LONGBLOB (gespeicherter Kassierbon für Nachdruck)
T8:  bestell_positionen   – bestell_id FK (CASCADE DELETE), produkt_id,
                            name_snapshot, preis_cent, menge

Views:
  v_artikel_verwaltung  – LEFT JOIN, alle CAO-Artikel inkl. Kiosk-Felder
  v_kiosk_produkte      – JOIN produkte LEFT JOIN kategorien, aktiv > 0,
                          auch ohne kategorie_id (→ '– Sonstige –')
  v_verwaiste_produkte  – produkte ohne CAO-Eintrag
  v_offene_warenkoerbe  – geparkte Körbe inkl. erstellt_von
  v_journal_uebersicht  – Journal mit Positionsanzahl

### Bestellungs-Modul

- Bestellnummer: `B-{YEAR}-{id:04d}`, generiert nach INSERT mit lastrowid
- wochentag VARCHAR(2): gleiche Kürzel wie produkte.wochentage (Mo/Di/Mi/Do/Fr/Sa/So)
- Produkt-Filter: wochentage='' → immer verfügbar; sonst FIND_IN_SET-Abfrage
- Einmalig nach Druck: status → 'gedruckt', gedruckt_datum = heute
- Wiederkehrend nach Druck: status bleibt 'offen', nur gedruckt_datum = heute
- Heute-View (_HEUTE_SQL): zeigt alle nicht-stornierten, nicht-pausierten
  Bestellungen für heute (auch bereits gedruckte – sie verschwinden NICHT)
- Pausierte Bestellungen (`pausiert=1` mit `pause_bis IS NULL OR pause_bis >= heute`)
  werden im Heute-Tab und in der Tagesansicht ausgeblendet
- Badge-Zähler (_BADGE_SQL): nur wirklich offene (einmalig: status='offen';
  wiederkehrend: gedruckt_datum IS NULL OR gedruckt_datum < heute)
  Ebenfalls pausierte Bestellungen ausgeschlossen
  → JS-Polling alle 30 Sekunden, sichtbar in Nav auf allen Seiten
- URL-Struktur: `/bestellungen/<id>` verwendet den internen DB-PK `id`,
  NICHT `bestell_nr` → kein Konflikt z.B. B-2026-0042 vs. B-2027-0042
- Bon-Vorschub vor Schnitt: 2 Leerzeilen (nicht 3)

#### Zahlungsart

- Bei Erfassung wählen: "Sofort zahlen" oder "Bei Abholung zahlen"

**Sofort zahlen:**
  - EAN aus Gesamtbetrag generieren (ean_modul.generiere_ean)
  - Phase 1 (try/except): generiere_bon_bytes + bon_data in DB speichern
    → Fehler: druckfehler-Response (gespeichert, Nachdruck jederzeit möglich)
  - Phase 2 (try/except): _sende_an_drucker (Kassierbon mit EAN für Kunden)
    → Fehler: druckfehler-Response (bon_data bereits in DB)
  - status bleibt 'offen' – der Kassierbon ist KEIN Ersatz für die Pickliste!
    Die Bestellung erscheint weiterhin in der Übersicht und braucht noch
    eine Pickliste (wird wie alle anderen über den 🖨-Button gedruckt).
  - status='gedruckt' erst wenn Pickliste aus der Übersicht gedruckt wird.

**Bei Abholung zahlen:**
  - Keine Sofortbuchung, status='offen'
  - Nach Speichern: Frage "Bestätigungsbon drucken?"
    → Ja: /api/bestellungen/{id}/nachdruck mit {bestaetigung: true}
          → Pickliste OHNE Preise, OHNE EAN (nur Bestätigung für Kunden)
    → Nein: direkt zur Übersicht

#### Nachdruck (/api/bestellungen/{id}/nachdruck POST)

Body-Parameter `bestaetigung` steuert den Modus:

| bestaetigung | zahlungsart | Ergebnis |
|---|---|---|
| true | egal | Bestätigungsbon: Pickliste ohne Preise, ohne EAN |
| false | sofort + bon_data | Kassierbon (gespeicherte bon_data) |
| false | abholung | Pickliste mit Preisen + EAN |

- Buttons "↺ Nachdruck" (bestellungen.html) und "🖨 Nachdruck" (bestellung_detail.html)
  rufen den Endpunkt ohne bestaetigung-Flag auf (→ regulärer Nachdruck/Pickliste)

#### Pickliste / Bestätigungsbon (druck.py:drucke_pickliste)

Parameter:
- `mit_preisen=True`        Einzelpreise + Gesamtbetrag anzeigen
- `ean_barcode`             EAN-13 Barcode am Ende (Zahlung bei Abholung)
- `bereits_bezahlt=True`    statt Barcode: "Bereits bezahlt" (Sofort-Zahler)
- `gesamt_hinweis=N`        Betrag in Cent → "Zahlung bei Abholung / X,XX EUR"
                            (Bestätigungsbon nach Abholung-Bestellung)
- `pause_hinweis=str`       Zeigt Pause-Hinweis, überschreibt alle anderen Blöcke
- `titel_ueberschrift=str`  Überschreibt den automatischen Titel
                            ("Pickliste" / "Bestellbestaetigung")
- `aenderung_cent=int`      Differenzbetrag-Block für Änderungsbons:
                            > 0 → "Nachzahlung: X,XX EUR" + Barcode
                            = 0 → "Keine Nachzahlung"
                            < 0 → "Auszuzahlender Betrag: X,XX EUR" (fett, groß)

Priorität Titelblock: pause_hinweis → titel_ueberschrift → gesamt_hinweis → Standard
Priorität Zahlungsblock: pause_hinweis → aenderung_cent → gesamt_hinweis →
                         bereits_bezahlt → ean_barcode

Diff-Positionen (Änderungsbon):
- `_aenderung="entfernt"` → Artikel als "0x Name" + negativer Betrag drucken
  (negativer Betrag nur wenn `_neg_betrag=True`, d.h. nur bei Sofort-Zahlung)
- `_aenderung="neu"` → Artikel mit Suffix "NEU" drucken
- `_orig_menge` → Originalmenge für entfernte Artikel (für Betragsberechnung)

Preis-Strings (ep, gp) werden durch _ascii() gejagt → € → EUR (kein ? mehr)

Kassierbon (generiere_bon_bytes / _bon_bytes):
- Parameter `bestell_nr`: zeigt Bestellnummer (B-YYYY-NNNN) statt "Bon Nr: XXXX"
- Parameter `notiz`: druckt Notizzeile auf dem Bon
- Migration für bestehende DB: init_bestellungen.sql (CREATE TABLE IF NOT EXISTS +
  idempotente ALTER TABLE für zahlungsart / ean_barcode / bon_data)

#### Änderungsbon (beim Speichern einer Bestellung)

- Alte Positionen werden VOR dem Speichern gelesen (alt_gesamt_cent)
- Nach dem Speichern: Diff-Liste aus alten und neuen Positionen aufgebaut
- **Sofort-Zahlung:** `diff_cent = neu - alt`; separater Differenz-EAN bei > 0;
  `aenderung_cent=diff_cent`, `titel_ueberschrift="Geaenderte Bestellung"`
- **Abholung einmalig:** aktualisierter Picklisten-Bon mit neuem EAN
- **Abholung wiederkehrend:** Picklisten-Bon ohne EAN, mit `gesamt_hinweis`
- EAN-Barcode in DB (`bestellungen.ean_barcode`) wird bei jeder Speicherung
  für Abholung-Bestellungen auf den neuen Gesamtbetrag aktualisiert

#### Storno-Bon (bereits bezahlte Bestellungen)

- Positionen + Gesamtbetrag werden VOR dem Stornieren gelesen
- `zahlungsart == "sofort"`: Storno-Bon mit `titel_ueberschrift="Stornierung"`,
  `aenderung_cent=-total_cent` → zeigt "Auszuzahlender Betrag" groß + fett
- `zahlungsart == "abholung"`: kein Storno-Bon (nichts bezahlt)

### Mitarbeiter-Handbuch (doku/handbuch.html)

- Selbst enthaltene HTML-Datei (kein Framework-Dependency zur Laufzeit)
- 5 Kapitel: Verkauf Backwaren, Bon parken & Journal, Artikelverwaltung,
  Bestellabwicklung, Mittagstisch – mit Mermaid.js-Ablaufdiagrammen
- Flask liest die Datei und injiziert `window.TERMINAL_NR` als JS-Variable
- Terminal 1–7: read-only (kein Edit-Toolbar sichtbar)
- Terminal 8: WYSIWYG-Bearbeitungsmodus via `contenteditable`
  Bilder per Upload → POST `/handbuch/upload` → gespeichert in `doku/`
  Speichern → POST `/handbuch/speichern` → überschreibt handbuch.html (Backup: .bak)
- Terminal 9: nur Kapitel 4 (Bestellabwicklung) wird angezeigt
- Mermaid v10: `startOnLoad: false`, `data-source` sichert Quelltext vor SVG-Ersatz,
  `mermaid.run()` nach DOMContentLoaded manuell aufgerufen
- Screenshots: gespeichert in `doku/screenshot_<timestamp>.png`
- Zurück-Button: prüft `document.referrer` – gleicher Origin → zurück;
  sonst → `/` (keine Browser-History-Abhängigkeit)

### Mittagstisch-Modul (Google Sheets)

Kein eigenes DB-Schema – Google Sheet ist Single Source of Truth.

  Spreadsheet-ID: <SPREADSHEET_ID>
  Service Account: <SERVICE_ACCOUNT_EMAIL>
  Credentials:     app/<credentials>.json  (NICHT einchecken!)

Sheet-Tabs: ein Tab pro Woche, Name = "KW13_2026" (ISO-Woche)
Zellen pro Tab:
  A1       Titel "Wochenplan Mittagstisch"
  A3:C7    Datum | Wochentag | Gericht (Mo–Fr)
  A9, C9   Label "Außerdem täglich:" | Text
  A10, C10 Label "Jetzt neu:" | Text
  A12      Telefon (fest)
  A13      Hinweis (fest)

Neuer Tab: Inhalte der Vorwoche werden als Vorlage kopiert (Gerichte übernommen).
Datum/Wochentag werden automatisch berechnet, nie manuell eingegeben.

---

### Schema-Skripte

  schema.sql               – Vollständiges Schema (für Neuanlage)
  init_bestellungen.sql    – Nur T7+T8, für bestehende Installationen

---

## App-Dateien

app/
  config.py           – DB, Port 5001, TERMINAL_NR (Fallback), EAN
  db.py               – Connection Pool (5 Verbindungen), cent_zu_euro_str()
  ean.py              – EAN-13-Generierung + Selbsttest
  druck.py            – Bondruck + Picklisten-Druck via Raw-TCP-Socket (ESC/POS)
  mittagstisch.py     – Google Sheets Lesen/Schreiben (gspread)
  app.py              – Flask-Routen, get_terminal_nr() aus Cookie,
                        context_processor (terminal_nr + update_verfuegbar
                        automatisch in allen Templates verfügbar)
  requirements.txt    – flask, mysql-connector-python, gspread, google-auth
  <credentials>.json                        – Service-Account-Key (NICHT in Git!)

Projektroot:
  mittagstisch_apps_script.js  – Google Apps Script Web App für Google Sites (Option C)
  produktbilder/      – <REC_ID>.jpg/png/webp → automatisch erkannt
  doku/
    handbuch.html     – Mitarbeiter-Handbuch (selbst enthaltene HTML-Datei)
    screenshot_*.png  – Hochgeladene Screenshots (über Edit-Modus Terminal 8)
  templates/
    base.html             – Navigation (inkl. Update-Badge, Handbuch-Link),
                            Lade-Overlay (data-lade="..." Attribut auf Nav-Links
                            → zeigt "Bitte kurz warten…" für langsame Seiten),
                            Toast, Zoom-Funktion, Terminal-Cookie,
                            Bestätigungs-Overlay
    kiosk.html            – Produktauswahl (Kategorie-Tabs + Anzahl)
                            + Warenkorb-Spalte
    offen.html            – Geparkte Körbe (mit Terminal-Herkunft)
    journal.html          – Buchungshistorie (Warenkorb-Nr!),
                            Bon-Vorschau, Nachdruck, Storno
    admin_artikel.html    – Artikelverwaltung, Zoom-Buttons,
                            Terminal-Selector (1-9)
    bestellungen.html     – Übersicht Heute + Alle, Bulk-Druck, Storno
    bestellung_neu.html   – Neue Bestellung, Produkt-AJAX, Bildschirmtastatur
    bestellung_detail.html– Bestellung bearbeiten/stornieren
    update.html           – App-Update-Seite (nur Terminal 8)

---

## Client-Cookie-Einstellungen

Cookies werden pro Browser/Gerät gespeichert (1 Jahr):

  kiosk_zoom      – Zoomfaktor in % (75/85/100/110/120/135/150)
                    Einstellung über ±-Buttons in der Verwaltung
  kiosk_terminal  – Terminal-Nr (1-9)
                    Einstellung über 1-9-Buttons in der Verwaltung
                    Fallback: config.TERMINAL_NR

---

## Terminal-Isolierung

- Jeder Browser hat eigene Terminal-Nr (Cookie)
- Offener Warenkorb: nur eigenes Terminal (gesperrt_von = terminal_nr)
- Geparkte Körbe: für alle Terminals sichtbar und übernehmbar
- Bei Übernahme: erstellt_von wird auf übernehmendes Terminal gesetzt
- Journal: terminal_nr = buchendendes Terminal (im Bon und in Tabelle)

### Terminal-Rollen

| Terminal | Rolle | Besonderheiten |
|---|---|---|
| 1–7 | Mitarbeiter | Vollzugriff außer Handbuch-Bearbeitung und App-Update |
| 8 | Superuser | Handbuch bearbeitbar, App-Update und Rollback möglich |
| 9 | Kundenterminal | Nur Bestellabwicklung + Handbuch-Kapitel „Bestellabwicklung" |

---

## App-Update (Terminal 8)

- Hintergrund-Thread (`update-checker`) prüft alle 10 Minuten via `git fetch`
  ob neue Commits auf `origin/master` vorhanden sind
- Bei verfügbarem Update: pulsierender 🔄-Badge in der Navbar (nur Terminal 8)
- Seite `/update` zeigt aktuelle Version, neue Commits und Versions-Verlauf
- Update: `git pull origin master` → automatischer App-Neustart via `os.execv`
- Rollback: `git reset --hard <hash>` → automatischer Neustart
- `ROLLBACK_MIN_COMMIT = "abb491c"` — ältester Commit mit Update-Funktion;
  Rollback auf ältere Versionen wird nicht angeboten (fehlende Rollback-Seite)
- Bei künftigen Breaking Changes (Schema, Protokoll) diesen Wert aktualisieren

---

## Bondruck (druck.py)

- Verbindung: direkter TCP-Socket zu Drucker-IP (aus DB)
- Alle Bytes in EINEM sendall() → kein Piepsen zwischen Zeilen
- Encoding: CP437, Umlaute via _ascii()-Mapping
- Bonnummer auf Bon = warenkorb_id (= was Kunde auf Bildschirm sah)
- Letzte 2 Ziffern der Bonnummer: fett + doppelte Größe (ESC/POS)
- Bon-Vorschau im Browser: identisches Layout inkl. großer Ziffern
- Schnitt: GS V 0x01 (Teilschnitt, getestet OK)
- Heizzeit: Standard (ESC 7 entfernt – verursachte Piepsen)
- ESC/POS-Befehle: nur universell unterstützte Standardbefehle

Bon-Inhalt:
  - "Habacher Dorfladen" (doppelte Größe, fett)
  - Bonnummer (letzte 2 Ziffern groß)
  - Datum/Uhrzeit, Terminal
  - Positionen (Name, Menge×EP, GP)
  - Gesamt (rechtsbündig, fett)
  - EAN-13 Barcode (GS k 0x43, neues Format, 13 Ziffern)
  - 2 Zeilen Vorschub + Teilschnitt

---

## Performance

- Connection Pool: 5 DB-Verbindungen, wiederverwendet (spart TCP-Handshake)
- Produkt-Cache: 30s TTL für v_kiosk_produkte (teurer Cross-DB-JOIN)
  → wird bei Admin-Speicherung sofort geleert
- Bild-Cache: einmalig beim Start aus produktbilder/ eingelesen
- Google Fonts: nicht-blockierend geladen (media=print → onload)

---

## Produktbilder

Ablage: app/produktbilder/<REC_ID>.<ext>
Formate: jpg, jpeg, png, webp
Beispiel: 6247.jpg für Artikel mit REC_ID 6247
Erkennung: automatisch beim App-Start, kein DB-Eintrag nötig
CSS: object-fit: cover – füllt Kachel proportional, kein Rand

---

## App-Seiten

  /                   Artikelauswahl (Kategorie-Tabs + Anzahl) + Warenkorb
  /offen              Geparkte Körbe übernehmen (mit Terminal-Herkunft)
  /journal            Buchungshistorie (Warenkorb-Nr), Bon-Vorschau,
                      Nachdruck, Storno (mit Overlay-Bestätigung)
  /admin/artikel      Artikelverwaltung: Kategorie, Einheit, Wochentag,
                      Zutaten, Status, Zoom-Buttons, Terminal-Selector
  /mittagstisch       Wochenplan-Editor: aktuelle + nächste + übernächste Woche,
                      Speichern → direkt in Google Sheets
  /mittagstisch/speichern  POST-API für den Editor
  /produktbilder/<id> Statische Produktbilder
  /bestellungen            Übersicht: Heute (mit Druck) + Alle
  /bestellungen/neu        Neue Bestellung erfassen
  /bestellungen/<id>       Bestellung bearbeiten / stornieren
  /api/bestellungen/badge  GET – Anzahl offener heutiger Bestellungen (Badge)
  /api/bestellungen/produkte  GET ?wochentag=Mo – Produkte gefiltert nach Tag
  /api/bestellungen/neu    POST – Bestellung speichern
  /api/bestellungen/<id>/speichern  POST – Bestellung aktualisieren
  /api/bestellungen/<id>/stornieren POST – Bestellung stornieren
  /api/bestellungen/<id>/nachdruck  POST – Nachdruck (Kassierbon oder Pickliste)
  /api/bestellungen/drucken         POST – Picklisten drucken (ids:[…])
  /handbuch                         GET  – Mitarbeiter-Handbuch (Terminal-abhängig)
  /handbuch/speichern               POST – Handbuch speichern (nur Terminal 8)
  /handbuch/upload                  POST – Bild hochladen nach doku/ (nur Terminal 8)
  /doku/<path>                      GET  – Statische Dateien aus doku/ (Bilder)
  /update                           GET  – App-Update-Seite (nur Terminal 8)
  /api/update/ausfuehren            POST – git pull + App-Neustart (nur Terminal 8)
  /api/update/rollback/<hash>       POST – git reset --hard + Neustart (nur Terminal 8)

---

## Workflow

  Artikel antippen:   Menge +1 (keine Doppelzeile)
  Plus/Minus:         Menge ±1; bei 0 → Zeile löschen
  Parken:             status=geparkt, gesperrt_von=NULL
  Übernehmen:         status=offen, gesperrt_von + erstellt_von = Terminal
  Abbrechen:          status=abgebrochen, kein Journal-Eintrag
  Buchen:             Snapshots + Journal + Bon drucken
                      warenkorb_id = Bonnummer (auf Bon + im Journal)
                      → Erfolgs-Overlay zeigt bon_nr (= warenkorb_id),
                        letzte 2 Ziffern groß – NICHT journal_id
  Nachdruck:          aus Journal, als KOPIE kennzeichnen
  Stornieren:         status=storniert (mit Overlay-Bestätigung)

---

## Sicherheitsabfragen (Overlay, kein Browser-Dialog)

  Warenkorb verwerfen → "Verwerfen"
  Storno              → "Stornieren"
  Verwaiste löschen   → "Löschen"

---

## Offene Punkte

1. App auf Pi deployen (aktuell noch auf Mac)
2. Lokale LAN-IP in config.py eintragen (statt myfritz-Adresse)
3. Produktbilder für Artikel anlegen
4. Mittagstisch: Apps Script in Google Sheet einfügen und als Web App bereitstellen
   (siehe mittagstisch_apps_script.js + Anleitung im Dateiheader)
5. Mittagstisch: Web-App-URL in Google Sites per "Einbetten"-Block einbinden
6. Bestellungen: weitere Eingangskanäle anbinden (Telefon, Web, …)
7. Handbuch: Diagramm "Ablauf Bestellung am Liefertag" – Mermaid-Syntaxfehler prüfen
8. Handbuch: Screenshot-Platzhalter mit echten Screenshots befüllen (über Terminal 8)

---

## Deployment (Pi)

  cd baeckerei-kiosk/app

  # Abhängigkeiten
  pip3 install -r requirements.txt --break-system-packages

  # DB anlegen (Neuinstallation)
  mysql -h <LAN-IP> -P 3333 -u cao -p<DB_PASSWORD> < ../schema.sql

  # Oder: nur Bestellungs-Tabellen auf bestehender DB
  mysql -h <LAN-IP> -P 3333 -u cao -p<DB_PASSWORD> < ../init_bestellungen.sql

  # Drucker in DB eintragen
  INSERT INTO Backwaren.drucker (name, ip_adresse, port, standard, aktiv)
    VALUES ('Bondrucker', '192.168.x.x', 9100, 1, 1);
  INSERT INTO Backwaren.terminal_drucker (terminal_nr, drucker_id) VALUES (1, 1);

  # EAN-Selbsttest
  python3 ean.py

  # App starten
  python3 app.py

  # Chromium im Kiosk-Modus (Zoom per --force-device-scale-factor oder App-Zoom)
  chromium-browser --kiosk --noerrdialogs http://localhost:5001
