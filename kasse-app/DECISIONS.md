# DECISIONS.md – CAO-XT Kassen-App

Architektur- und Designentscheidungen für `kasse-app/`. Analoges Dokument zu `kiosk-app/DECISIONS.md`.

---

## Übersicht

Webbasierte Kassensoftware (KassenSichV §146a AO) als Python-Flask-Modul im cao-xt-Repository.
Zielgerät: Touchscreen-Terminal im Ladenlokal (Habacher Dorfladen).

**Technologie-Stack**
- Python Flask (Port 5002, analog kiosk-app auf 5001)
- MySQL – CAO-Faktura-Datenbank, DictCursor (Spaltennamen UPPERCASE)
- ESC/POS über TCP für Bondrucker
- Fiskaly Cloud TSE (REST API) oder Swissbit USB TSE (libWorm) für KassenSichV-Signierung

---

## Datenbankschema

### Tabellenpräfix `XT_KASSE_`

Alle neuen Tabellen tragen das Präfix `XT_KASSE_`, um Kollisionen mit CAO-Tabellen zu vermeiden.

| Tabelle | Zweck |
|---------|-------|
| `XT_KASSE_TERMINALS` | Terminal-Konfiguration (Drucker, TSE, Firmendaten) |
| `XT_KASSE_TSE_GERAETE` | TSE-Gerätekatalog – dauerhaft, alle historischen Geräte (Auditpflicht) |
| `XT_KASSE_VORGAENGE` | Kassenvorgänge / Belege |
| `XT_KASSE_VORGAENGE_POS` | Positionen je Vorgang |
| `XT_KASSE_ZAHLUNGEN` | Zahlarten je Vorgang |
| `XT_KASSE_KASSENBUCH` | Kassenbuch (GoBD-konform) |
| `XT_KASSE_TAGESABSCHLUSS` | Z-Bons |
| `XT_KASSE_ZAEHLER` | Atomare Bon-/Z-Nummernvergabe |
| `XT_KASSE_LIEFERSCHEINE` | Zuordnung Bon → CAO-Lieferschein |
| `XT_KASSE_TSE_LOG` | TSE-Transaktionslog (Audit-Trail) |
| `XT_KASSE_EAN_REGELN` | Inhouse-EAN-Regeln (Preis-EAN, Gewichts-EAN, Zeitschriften) |

### CAO-Tabellen (read-only)
`ARTIKEL`, `WARENGRUPPEN`, `MENGENEINHEIT`, `ARTIKEL_PREIS`,
`ADRESSEN`, `ADRESSGRUPPEN`, `MITARBEITER`,
`REGISTRY` (MwSt-Sätze, Userfeld-Labels, Lieferschein-Nummerierung),
`ARTIKEL_SCHNELLZUGRIFF`, `FIRMA`

### CAO-Tabellen (schreibend)
`LIEFERSCHEIN`, `LIEFERSCHEIN_POS` – nur bei der Funktion "Bon → Lieferschein wandeln"

### Beträge immer in Cent (INT)
Alle Geldbeträge werden als Integer-Cent gespeichert. Keine Dezimalzahlen für Geld.
**Grund:** Vermeidung von Gleitkomma-Rundungsfehlern, einfachere Ganzzahlarithmetik.

### Snapshot-Felder in Positionen
`BEZEICHNUNG`, `ARTNUM`, `MWST_SATZ` usw. in `XT_KASSE_VORGAENGE_POS` werden beim Erfassen als Snapshot gespeichert.
**Grund:** Artikelpreise/-bezeichnungen können sich ändern; der Bon muss unveränderlich bleiben (GoBD §146 Abs. 4 AO).

### BON_NR-Vergabe über separaten Zähler
`XT_KASSE_ZAEHLER` mit `SELECT ... FOR UPDATE` verhindert Race Conditions bei Parallelbetrieb mehrerer Anfragen.

### Nachträgliche Schema-Änderungen (ALTER TABLE)
Da `schema.sql` nur `CREATE TABLE IF NOT EXISTS` enthält, werden neue Spalten per separatem ALTER TABLE eingefügt:
```sql
ALTER TABLE XT_KASSE_TERMINALS ADD COLUMN SOFORT_DRUCKEN TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE XT_KASSE_TERMINALS ADD COLUMN SCHUBLADE_AUTO_OEFFNEN TINYINT(1) NOT NULL DEFAULT 1;
ALTER TABLE XT_KASSE_TERMINALS ADD COLUMN FISKALY_ADMIN_PUK VARCHAR(100);
ALTER TABLE XT_KASSE_VORGAENGE ADD COLUMN KUNDEN_ID INT NULL;
ALTER TABLE XT_KASSE_VORGAENGE ADD COLUMN KUNDEN_NR VARCHAR(20) NULL;
ALTER TABLE XT_KASSE_VORGAENGE ADD COLUMN KUNDEN_NAME VARCHAR(100) NULL;
ALTER TABLE XT_KASSE_VORGAENGE ADD COLUMN KUNDEN_ORT VARCHAR(100) NULL;
ALTER TABLE XT_KASSE_VORGAENGE ADD COLUMN KUNDEN_PR_EBENE TINYINT NULL;
```

---

## Architektur

### Modul-Aufteilung
- `config.py` – liest DB-Verbindung aus `caoxt.ini`, Terminal-Nr aus Env-Var `KASSE_TERMINAL_NR`
- `db.py` – Verbindungsmanagement, Context Manager `get_db()` / `get_db_transaction()`
- `kasse_logik.py` – Geschäftslogik (Vorgänge, Positionen, Preisberechnung, Lieferschein)
- `tse.py` – TSE-Dispatcher: Fiskaly Cloud TSE, Swissbit USB TSE, Trainings-/Demo-Modus
- `swissbit_worm.py` – ctypes-Wrapper um libWorm (C-Bibliothek für Swissbit USB TSE)
- `druck.py` – ESC/POS Bondruck über TCP, Kassenlade-Impuls
- `dsfinvk.py` – DSFinV-K Export (ZIP-Archiv gemäß GoBD/BMF)
- `app.py` – Flask-Routen, API-Endpunkte

### Kein ORM
Direktes SQL mit DictCursor (PyMySQL).
**Grund:** CAO-Datenbankstruktur ist vorgegeben und komplex; ORM-Mapping würde keinen Mehrwert bringen.

### Authentifizierung
Gegen `MITARBEITER`-Tabelle. Passwort-Vergleich als MD5-Hash in Großbuchstaben (CAO-kompatibel).
Session-basiert (Flask `session`).

### Multi-Terminal-Fähigkeit
Jedes Terminal hat eine eigene `TERMINAL_NR` (1–9), konfiguriert über Env-Var `KASSE_TERMINAL_NR`.
Terminals können sich Drucker, Kassenbuch und TSS teilen, aber jedes Terminal braucht eine eigene TSE-`CLIENT_ID` (KassenSichV-Anforderung).

---

## TSE-Integration

### Gerätetypen und Dispatcher
`tse.py` unterstützt drei TSE-Typen, die pro Terminal über `XT_KASSE_TSE_GERAETE` konfiguriert werden:

| Typ | Implementierung | Signaturen |
|-----|----------------|------------|
| `FISKALY` | REST API gegen `fiskaly.com` | Kryptographisch echte Signaturen (BSI TR-03153) |
| `SWISSBIT` | ctypes → libWorm (C-Bibliothek) | Kryptographisch echte Signaturen (BSI TR-03153) |
| `DEMO` | Platzhalter in `tse.py` | Keine echten Signaturen (Testbetrieb) |

Die Dispatch-Reihenfolge in jeder TSE-Funktion: Trainings-Modus-Prüfung → SWISSBIT → FISKALY (Legacy-Fallback bei fehlender `TSE_ID`).

### TSE-Gerätekatalog (`XT_KASSE_TSE_GERAETE`)
Alle TSE-Geräte werden dauerhaft gespeichert – auch dekommissionierte. Auditpflicht nach KassenSichV.
Ein Terminal referenziert sein aktives Gerät über `TSE_ID` (FK). Wechsel erfolgt über die TSE-Verwaltung (`/admin/tse`), nicht durch Löschen.

### Fiskaly Cloud TSE
Eine `TSS_ID` (Technical Security System) kann mehrere `CLIENT_ID`s haben – eine pro Terminal.
Beim ersten Speichern mit vollständigen Credentials wird der Client automatisch angelegt:
1. TSS entsperren (Admin-PUK), auf INITIALIZED setzen (Admin-PIN)
2. Client anlegen und aktivieren
3. `FISKALY_CLIENT_ID` in `XT_KASSE_TERMINALS` speichern

### Swissbit USB TSE
Anbindung via libWorm (C-Bibliothek, Linux-only). Wrapper: `swissbit_worm.py`.
- `WormTse` – Context Manager (öffnet/schließt Verbindung zum Block-Device)
- `verfuegbar()` – prüft ob libWorm geladen werden kann (auf macOS: immer `False`)
- Transaktions-ID ist eine uint64-Nummer (als String gespeichert für API-Kompatibilität mit Fiskaly)
- Start und Finish können in separaten `WormTse`-Sessions erfolgen (Nummer bleibt auf Gerät)
- Storno: Start + Finish in einer einzigen Session (Atomizität)

Die CAO-Faktura-Datenbank enthält ca. 582.000 Signaturen in `TSE_LOG` vom alten CAO-Kassenmodul; die Swissbit USB TSE hat ~20 Mio. Kapazität – Wiederverwendung ist möglich.

### TSE-Transaktionen
- `tse_start` → beim Beginn der Zahlung
- `tse_finish` → nach erfolgreicher Buchung
- `tse_cancel` → bei Abbruch
- `tse_storno` → Storno-Beleg (eigene Transaktion mit negativen Beträgen)
- `tse_tagesabschluss` → Tagesabschluss bekommt eigene TSE-Transaktion

---

## Betriebsmodi (Trainings-, Demo- und Testbetrieb)

Es gibt **keinen separaten „Test-Modus"** – die vorhandenen Konzepte decken alle Szenarien ab:

| Modus | Wo konfiguriert | TSE-Code läuft | Signaturen echt | Bon-Aufdruck | Zweck |
|-------|----------------|----------------|-----------------|--------------|-------|
| **Trainings-Modus** | Terminal-Flag (schnell umschaltbar) | ❌ Nein | – | `TRAININGSBON` | Personalschulung, Demos |
| **DEMO-TSE** | TSE-Gerät (`TYP=DEMO`) | ✅ Ja | ❌ Platzhalter | `TRAININGSBON` | Entwicklung, Tests ohne Hardware |
| **Fiskaly `test`-Umgebung** | TSE-Gerät (`FISKALY_ENV=test`) | ✅ Ja | ✅ Kryptographisch | – | Integrationstests gegen Sandbox-API |
| **Produktivbetrieb** | TSE-Gerät (Fiskaly live / Swissbit) | ✅ Ja | ✅ Kryptographisch | – | Normalbetrieb |

**Wann welcher Modus:**
```
Mitarbeiter einarbeiten          → Trainings-Modus (an/aus per Klick)
Kasse ohne TSE-Hardware zeigen   → Trainings-Modus oder DEMO-TSE aktivieren
Code-Änderungen an tse.py testen → DEMO-TSE (voller Pfad, kein echtes Gerät nötig)
Fiskaly-Integration debuggen     → TSE-Gerät mit FISKALY_ENV=test
Abgelaufene Swissbit USB-TSE     → DEMO-TSE (statt wegwerfen)
Produktivbetrieb                 → Fiskaly live oder Swissbit (echte Signaturen)
```

**Warum kein separater Test-Modus-Toggle:** Ein zusätzlicher Toggle wäre entweder ein Alias für den Trainings-Modus (TSE überspringen) oder für die DEMO-TSE (Platzhalter-Signaturen). Die Dreiteilung Terminal-Flag / TSE-Gerätetyp / TSE-Umgebung ist ausreichend und vermeidet Konflikte zwischen überlagernden Flags.

---

## GoBD / KassenSichV-Compliance

### Soft-Delete statt DELETE
Positionen werden mit `STORNIERT=1` markiert, niemals physisch gelöscht.
Vorgänge erhalten STATUS `STORNIERT` oder `ABGEBROCHEN`.
**Grund:** GoBD §146 Abs. 4 AO verbietet Löschung oder nachträgliche Veränderung von Buchungsunterlagen.

### Storno als Gegenbuchung
Ein Storno erzeugt immer einen neuen Bon mit negativen Beträgen (Gegenbuchung), anstatt den Original-Bon zu löschen.

### BON_NR fortlaufend und lückenlos
Die Bon-Nummerierung darf keine Lücken haben. Beim Kopieren eines Bons im Journal wird daher ein bereits vorhandener leerer offener Bon wiederverwendet, anstatt ihn zu `ABGEBROCHEN` zu setzen und einen neuen anzulegen.
```python
# kasse_logik.py – vorgang_kopieren()
if offen and not vorgang_positionen(offen['ID']):
    neuer = offen  # Leeren Bon direkt nutzen
else:
    neuer = vorgang_neu(terminal_nr, mitarbeiter)
```

---

## UI / Frontend

### Single-Page-Ansatz für Kasse
Die Hauptkasse (`kasse.html`) lädt den aktuellen Vorgang per AJAX und aktualisiert den Warenkorb ohne Seitenneuladen. Navigation zu separaten Seiten nur für Journal, Kassenbuch, Admin.

### Zahlungsabwicklung als Overlay
Die Zahlung erfolgt in einem Modal-Overlay über der Kassenseite, nicht als separate Route (`/zahlung`).
**Grund:** Navigationswechsel verlor den Kundenstatus im JS-State; Overlay umgeht das Problem vollständig.

### Zahlarten (implementiert)
- **BAR** – mit Numpad für gegebenen Betrag, Rückgeldberechnung
- **BAR PASSEND** – Kurzweg ohne Betrageingabe
- **EC-Karte** – manuelle Abwicklung am EC-Gerät (kein ZVT), mit Bedienungsanweisung im UI

Nicht implementiert: Kundenkonto-Zahlung, Gutschein (bewusst weggelassen – kein Bedarf).

### On-Screen-Tastatur (QWERTZ)
Für das Betreff-/Notiz-Feld gibt es eine einblendbare QWERTZ-Tastatur (adaptiert von kiosk-app).
Aktiviert via `readonly`-Attribut + `onclick="zeigeTastatur(this)"` am Input-Feld.
Autofokus-Handler im Warenkorb wird deaktiviert wenn Tastatur aktiv (`_tastaturAktiv`-Flag).

### Kundenzustand im Frontend
Beim Laden der Kasse wird der offene Vorgang per API abgerufen. Wenn ein Kunde gesetzt ist (`KUNDEN_ID`), wird dieser aus den Vorgang-Daten wiederhergestellt (inkl. `KUNDEN_PR_EBENE`), damit nach Navigation / Seitenreload der Kundenkontext erhalten bleibt.

### Preisebene
Beim Setzen eines Kunden wird seine Preisebene (`PR_EBENE` aus `ADRESSEN`) im Vorgang gespeichert (`KUNDEN_PR_EBENE`). Die Artikelpreise werden daraufhin neu berechnet. Die Preisebene wird beim Wiederherstellen des Kundenstatus aus dem Vorgang ausgelesen.

---

## Drucker / Kassenlade

### ESC/POS über TCP
Verbindung zu Bondrucker über IP:Port (default 9100). Kein USB-/serieller Drucker.

### SOFORT_DRUCKEN (Terminaleinstellung)
Wenn aktiviert: Bon wird direkt nach dem Buchen gedruckt.
Wenn deaktiviert: Bon muss manuell über "Letzter Bon drucken" gedruckt werden.

### SCHUBLADE_AUTO_OEFFNEN (Terminaleinstellung)
Wenn aktiviert: Kassenlade öffnet nach Abschluss einer Barzahlung automatisch.
Nur wirksam wenn `KASSENLADE > 0` (Lade vorhanden).

### Kassenlade-API
`POST /api/lade/oeffnen` – manuelle Auslösung über Button in der Kassenseite.

---

## API-Routen (Übersicht)

| Methode | Route | Funktion |
|---------|-------|----------|
| GET | `/kasse` | Hauptkasse |
| GET | `/kasse/journal` | Belegjournal |
| GET | `/kasse/kassenbuch` | Kassenbuch |
| GET | `/kasse/tagesabschluss` | Tagesabschluss-Vorschau |
| GET | `/kasse/abschluesse` | Liste der Z-Bons |
| GET | `/kasse/xbon` | X-Bon (Zwischenabschluss) |
| POST | `/api/vorgang/neu` | Neuen Bon anlegen |
| GET | `/api/vorgang/offen` | Offenen Bon des Terminals laden |
| GET | `/api/vorgang/suche` | Bons nach Datum/Bon-Nr. suchen |
| GET | `/api/vorgang/<id>` | Vorgang mit Positionen und Zahlungen |
| POST | `/api/vorgang/<id>/position` | Position hinzufügen |
| DELETE | `/api/vorgang/<id>/position/<pid>` | Position stornieren (Soft-Delete) |
| PATCH | `/api/vorgang/<id>/position/<pid>/menge` | Menge ändern |
| PATCH | `/api/vorgang/<id>/position/<pid>/rabatt` | Rabatt setzen |
| PATCH | `/api/vorgang/<id>/kunde` | Kunden zuweisen |
| PATCH | `/api/vorgang/<id>/notiz` | Notiz/Betreff setzen |
| POST | `/api/vorgang/<id>/parken` | Vorgang parken |
| POST | `/api/vorgang/<id>/entparken` | Geparkten Vorgang fortsetzen |
| POST | `/api/vorgang/<id>/abbrechen` | Vorgang abbrechen (GoBD-konform) |
| POST | `/api/vorgang/<id>/zahlung` | Zahlung abschließen (inkl. TSE, Druck) |
| POST | `/api/vorgang/<id>/storno` | Vorgang stornieren (Gegenbuchung) |
| POST | `/api/vorgang/<id>/kopieren` | Positionen in neuen Bon kopieren |
| POST | `/api/vorgang/<id>/bon_nochmal` | Bon nochmals drucken (Kopie) |
| POST | `/api/vorgang/<id>/lieferschein` | Bon in CAO-Lieferschein wandeln |
| POST | `/api/vorgang/<id>/neuberechnen` | Preise auf neue Preisebene anpassen |
| GET | `/api/geparkte` | Alle geparkten Vorgänge des Terminals |
| GET | `/api/schnelltasten` | Schnellzugriff-Buttons laden |
| GET | `/api/artikel/suche` | Artikelsuche (Freitext) |
| GET | `/api/artikel/barcode/<code>` | Artikel per Barcode/EAN (inkl. Sonder-EAN) |
| GET | `/api/artikel/warengruppen` | Alle Warengruppen (Hierarchie) |
| GET | `/api/artikel/browser` | Artikelliste für Browser (?wg=<id> optional) |
| GET | `/api/ean-regeln` | Alle EAN-Regeln |
| POST | `/api/ean-regeln` | EAN-Regel anlegen/speichern |
| DELETE | `/api/ean-regeln/<id>` | EAN-Regel löschen |
| GET | `/api/kunden/suche` | Kundensuche (Freitext) |
| GET | `/api/kundengruppen` | Alle Kundengruppen |
| GET | `/api/kunden/gruppe/<id>` | Kunden einer Gruppe (?id=-1 = alle) |
| POST | `/api/kassenbuch` | Kassenbuch-Eintrag (Einlage/Entnahme/Anfangsbestand) |
| POST | `/api/tagesabschluss` | Z-Bon erstellen und drucken |
| POST | `/api/xbon/drucken` | X-Bon drucken |
| POST | `/api/drucker/letzter-bon` | Letzten Bon nochmals drucken (Kopie) |
| POST | `/api/drucker/test` | Testseite drucken |
| POST | `/api/lade/oeffnen` | Kassenlade öffnen |
| GET | `/admin/` | Admin-Übersicht |
| GET/POST | `/admin/terminal` | Terminal konfigurieren |
| POST | `/admin/terminal/trainings_modus` | Trainings-Modus umschalten |
| GET | `/admin/tse` | TSE-Geräteverwaltung |
| GET/POST | `/admin/tse/neu` | TSE-Gerät anlegen/bearbeiten |
| POST | `/admin/tse/<id>/aktivieren` | TSE-Gerät für Terminal aktivieren |
| POST | `/admin/tse/<id>/ausser_betrieb` | TSE-Gerät dekommissionieren |
| GET | `/admin/export` | DSFinV-K Export-Seite |
| POST | `/admin/export/starten` | DSFinV-K Export als ZIP erstellen |
| GET | `/admin/export/download/<datei>` | Exportdatei herunterladen |

---

## Artikel-Browser

Overlay-Dialog für die manuelle Artikelauswahl, erreichbar über den „Artikelauswahl"-Button rechts neben den Schnellzugriff-Kategorietabs.

### Datenquellen

| Spalte | DB-Quelle | Anzeige |
|--------|-----------|---------|
| Art.-Nr. | `ARTIKEL.ARTNUM` | Interne CAO-Artikelnummer |
| Bezeichnung | `ARTIKEL.KAS_NAME` ∣ `ARTIKEL.KURZNAME` | Kassenname bevorzugt |
| PLU | `ARTIKEL.USERFELD_04` | Kassenrufnummer (konfiguriert in `REGISTRY MAIN\ARTIKEL\USERFELDER FELD04`) |
| PLU-2 | `ARTIKEL.USERFELD_05` | Zweite PLU (`FELD05`) |
| EAN | `ARTIKEL.BARCODE` | EAN-Barcode (lesend, nicht für Scan-Lookup) |
| Typ | `ARTIKEL.ARTIKELTYP` | N=Normal, L=Lohn (kein Bestand), S=Stückliste |
| ME | `MENGENEINHEIT.BEZEICHNUNG` | Mengeneinheit (JOIN) |
| Bestand | `ARTIKEL.MENGE_AKT` | Aktueller Lagerbestand (negativ = rot) |
| VK | `ARTIKEL.VK1B`–`VK5B` | Preisebene 5 = Standard/Barverkauf |
| Akt. | `ARTIKEL_PREIS.PREIS` | Aktionspreis (`PT2='AP'`, Gültigkeitsfilter) |
| MwSt. | aus `STEUER_CODE` | Aus MwSt-Cache |

### Warengruppen-Hierarchie

`WARENGRUPPEN.TOP_ID = -1` bedeutet Wurzel-Knoten (CAO-Konvention).
Kinder haben `TOP_ID = parent_id`. Schema-Erkennung (Spaltenname `REC_ID`/`WG_ID`, `BEZEICHNUNG`/`NAME`, `TOP_ID`/`PARENT_ID`, `SORT`) erfolgt einmalig per `DESCRIBE` und wird dauerhaft gecacht (`_wg_schema_cache`).

Die Ebene **„Alle"** (ID = 0) steht ganz oben – sie lädt alle Artikel ohne WG-Filter und ist der Standard beim Öffnen.
Beim Anklicken einer WG werden alle Nachkommen per BFS (`_wg_nachkommen()`) einbezogen, d. h. Artikel in Untergruppen erscheinen auch in der Elterngruppe.

### SQL-Konstanten

`_BROWSER_SELECT`, `_BROWSER_JOINS`, `_BROWSER_ORDER` in `kasse_logik.py` kapseln die erweiterte Abfrage (inkl. JOINs auf `MENGENEINHEIT` und `ARTIKEL_PREIS`). Dadurch lässt sich die Browser-Query an einer Stelle pflegen.

### Frontend-Caching

- `_artBrWGs` – Warengruppen, dauerhaft bis Seitenneuladung (ändern sich selten)
- `_artBrAlleArt` – alle Artikel (Lazy-Load beim ersten Suchen), wird bei `artBrowserSchliessen()` geleert um Veralterung zu vermeiden
- `_artBrWGSummen` – Artikel-Gesamtanzahl je WG inkl. Nachkommen (client-seitige BFS-Aggregation)

### Such- vs. WG-Modus

Suche und WG-Auswahl schließen sich gegenseitig aus. Beim Tippen in das Suchfeld wird die aktive WG als `_artBrVorSucheWG` gemerkt und nach dem Leeren wiederhergestellt. Suchefelder: Bezeichnung, Art.-Nr., PLU, PLU-2, EAN, Matchcode.

---

## EAN-Regeln (`XT_KASSE_EAN_REGELN`)

Flexible Erkennung von Inhouse-EANs über Präfix-Matching. Ergänzt den normalen Barcode-Lookup um spezielle Formate:

| Typ | Format | Besonderheit |
|-----|--------|-------------|
| `PREIS` | `XX AAAA Z PPPPP Z` | Preis in Stellen 8–12 (5-stellig, Cent) |
| `GEWICHT` | `XX AAAA Z GGGGG Z` | Gewicht in Stellen 8–12 (Gramm) × Preis/kg |
| `ZEITSCHRIFT` | `977…` / `978…` / `979…` | Zeitschriften-ISSN / Bücher-ISBN, Preis aus EAN-Tabelle |
| `PRESSE` | Sonstige Präfixe | Freie Präfix-Zuordnung zu Artikel/WG |

**`ARTIKEL_LOOKUP`-Flag:** Wenn gesetzt, wird der Artikel anhand von `ARTNUM` aus Stellen 3–6 der Inhouse-EAN gesucht (Format `XX AAAA Z …`). Artikel-Prüfziffer wird validiert.

**Caching:** EAN-Regeln werden 60 s gecacht (`_ean_regeln_cache`). Nach Änderungen über die Admin-API wird der Cache sofort geleert (`ean_regeln_cache_loeschen()`).

---

## Noch nicht implementiert (Phase 2)

- **ZVT-Protokoll**: Automatische EC-Terminal-Ansteuerung
- **Kundendisplay**: Zweites Display für Kundenanzeige
