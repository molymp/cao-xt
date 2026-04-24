# WaWi-Personal – Architekturentscheidungen

Teil der Zeitmanagement-Reihe (Phasen P1–P5). Dieses Modul: **P1 Mitarbeiterverwaltung + P3 Stempeluhr**.

## Grundsatzentscheidung: Entkopplung von CAO.MITARBEITER

**Entscheidung:** Die Personal-/Zeitmanagement-Domäne ist vollständig von CAO entkoppelt.
Eigene Tabellen mit Präfix `XT_PERSONAL_`. **Kein** INSERT/UPDATE auf CAO-Tabellen.

**Begründung:**

1. **Unbekanntes Signaturformat.** CAO schreibt bei UPDATE auf MITARBEITER einen Snapshot
   in `MITARBEITER_LOG` mit einem ~500-Byte-HASHSUM-Blob (Base64-Text, konstanter
   Header-Prefix `8q/fXQo6…`). Dieses Format gilt für **alle** CAO-`_LOG`-Tabellen
   (ADRESSEN_LOG, ARTIKEL_LOG, BENUTZERRECHTE_LOG, …, jeweils mit eigenem Header-Prefix) und
   konnte aus den vorhandenen Daten nicht reproduziert werden – im Unterschied zur
   varchar-basierten JOURNAL.HASHSUM, deren MD5+Salt-Algorithmus in
   `reference_cao_journal_write.md` dokumentiert ist.
2. **Kein fachlicher Overlap.** CAO hat keine HR-/Zeitmanagement-Features
   (die existierenden `ZEITEN_*`-Tabellen sind projekt-/aufgabenbasiert – `TYP enum('P','A')`
   = Projekt/Aufgabe – und passen nicht zu „Kommen/Gehen"-Stempeluhr im Schichtbetrieb).
3. **Klare Datenhoheit.** Unser Modul ist Single Source of Truth für alle
   personal-relevanten Daten. Keine Doppelpflege, keine Divergenz zwischen CAO-Desktop
   und WaWi-App.

## CAO-Integration trotzdem vorhanden – aber nur lesend

- **Authentifizierung** nutzt weiterhin CAO-`MITARBEITER`-Login (MD5-Hash, siehe
  `common/auth.py`). Unverändert.
- **Zugriff auf Personal-Backoffice:** Abfrage `BENUTZERRECHTE` → Gruppenzugehörigkeit.
  Erlaubt sind die Gruppen `Administratoren` und `Ladenleitung` (Auflösung per
  `MODUL_NAME` aus BENUTZERRECHTE, keine hardcodierten GRUPPEN_IDs).
- **Keine Schreibzugriffe auf CAO-Tabellen durch dieses Modul.** CAO-Desktop pflegt
  MITARBEITER.LOGIN_NAME / USER_PASSWORD weiter eigenständig.
- **Separate Berechtigungen für Kiosk-Stempeluhr** (P3): das dortige
  Zeiterfassungs-Berechtigungsmodell ist nicht an CAO-Gruppen gekoppelt, sondern lebt in
  `XT_PERSONAL_*` (wird in P3 detailliert).

## GoBD-konforme Audit-Tabelle im eigenen Format

`XT_PERSONAL_MA_LOG` speichert jede Änderung an `XT_PERSONAL_MA` als JSON-Snapshot
(alte und neue Werte, Operation, Zeitstempel, ausführender CAO-User).
Append-only, keine UPDATE/DELETE. Schlüsselerkenntnisse:

- Geld als Integer-Cent, auch in Historientabellen (konsistent mit Kasse/WaWi).
- Datumsspalten (GEBDATUM, EINTRITT, AUSTRITT) ohne Zeitanteil (`DATE`, nicht `DATETIME`).
- `CAO_MA_ID` optional (NULL erlaubt): nur für MAs, die zusätzlich einen CAO-Login
  haben (für spätere Karten-Zuordnung / Stempeluhr). Mehrfach-Zuordnung ist
  ausgeschlossen (`UNIQUE`).

## Beträge in Cent – Beispiel

Stundensatz `13.90 €` wird als `STUNDENSATZ_CT = 1390` gespeichert.
Die UI formatiert mit dem vorhandenen `eur`-Filter aus `wawi-app/app/app.py`.

## Seed-Daten (Import aus ShiftJuggler-CSV)

- Import-Script: `modules/wawi/personal/tools/import_csv.py`.
- CSV-Datei **nicht im Repo**. Lokal erwartet in `modules/wawi/personal/_seed_local/`
  (per `.gitignore` ausgeschlossen) oder explizit per `--csv <pfad>`.
- Reiner Bootstrap-Pfad für lokale Entwicklungs-/Testumgebung. Für Produktion
  separater, dokumentierter Import-Lauf.

## P3 Stempeluhr – Entscheidungen

**Tabellen:** `XT_PERSONAL_STEMPEL` (append-only Stempel-Events) +
`XT_PERSONAL_STEMPEL_KORREKTUR` (GoBD-konformes Änderungs-Log mit JSON-Snapshots
und Pflicht-Grund).

**Keine Schema-Änderung an CAO.`KARTEN`.** Mitarbeiterkarte und optional RFID
werden beide als `KARTEN.TYP='M'` geführt, bestehende Auth-Funktion
`common.auth.mitarbeiter_login_karte(guid)` wird wiederverwendet.

**Kiosk-Route öffentlich (`/stempeluhr`), kein Cookie-Login.** Der Karten-Scan
IST die Authentifizierung; eine Terminal-0-/Cookie-Logik wäre zusätzlicher
Komplexitätsaufwand ohne Mehrwert.

**Richtungs-Logik „last event wins":** Beim Scan wird der letzte Stempel des
MA geladen (unabhängig vom Datum) und kommen↔gehen gewechselt. Vorteil:
robust gegen Nachtschichten und vergessene Ausstempel-Vorgänge. Korrekturen
erfolgen über die Admin-UI.

**Keine UNIQUE-Constraint auf `(PERS_ID, ZEITPUNKT)`.** Mehrere legitime
Stempel pro Tag/Minute möglich (z.B. Pause in Sekunden-Auflösung); Paarbildung
passiert im View-Layer (`_stempel_paare_tag`).

**`GRUND` ist Pflicht bei jeder Korrektur.** Python-Layer erzwingt mit
`ValueError`, DB-Spalte ist `NOT NULL`. Korrektur-Historie (Insert/Update/Delete)
bleibt vollständig im Log sichtbar, auch nach Stempel-Löschung.

**Terminal-Nummer rein informativ** (`TINYINT UNSIGNED NULL`, aus
`TERMINAL_NR`-Env/Cookie des Kiosk). Nicht in Auth/Berechtigung verwoben.

## Offene Punkte für spätere Phasen

- **P1b:** Lohnart-Lookup-Tabelle + Lohnkonstanten (Mindestlohn, Minijob-Grenze)
  versioniert.
- **P1b:** Arbeitszeitmodelle mit Wochenverteilung (versioniert pro MA).
- **P1c:** Urlaubsanspruch + Korrekturbuchungen + „geplant/genehmigt/genommen"-Sicht.
- **P5:** DATEV-Lohn-Export (separates Format, nicht das vorhandene Finanzbuchhaltungs-Modul).
