# CAO-XT Kassen-App – Architekturentscheidungen

> **Konvention:** Jede Architektur- oder Designentscheidung wird hier eingetragen
> (Format: Datum, Problem, Entscheidung, Begründung, Alternativen).
> Eintrag erfolgt im selben Commit wie der zugehörige Code.

---

## 2026-04-02 · Warenbestand-Abbuchung: direktes MENGE_AKT-Update (HAB-34)

**Problem:**
Kassenbuchungen in der Kasse-App verändern bisher nicht `ARTIKEL.MENGE_AKT` in der
CAO-Faktura-Datenbank. Der angezeigte Warenbestand veraltet dadurch mit jeder Buchung.

**Entscheidung:**
Option A – direktes `UPDATE ARTIKEL SET MENGE_AKT = MENGE_AKT ± %s WHERE REC_ID = %s`
innerhalb der bestehenden `get_db_transaction()`-Transaktion in:

- `zahlung_abschliessen()` → Abbuchung (MENGE_AKT −= MENGE)
- `vorgang_stornieren()`  → Rückbuchung (MENGE_AKT += MENGE)

Zusätzlich `SELECT ... FOR UPDATE` vor jedem Update als Deadlock-Schutz bei
parallelen Terminals.

**Begründung:**
- Schnell umsetzbar (~2–3 Std.), keine Schema-Änderungen nötig
- Volle Transaktionskontrolle: Lager-Update rollt bei TSE- oder DB-Fehler
  gemeinsam mit Zahlung und Kassenbuch zurück
- Keine Abhängigkeit von noch ungeklärten JOURNAL/JOURNALPOS-Semantiken (HAB-21)

**Alternativen (nicht gewählt):**
- **Option B – JOURNAL/JOURNALPOS-Einträge** (CAO-nativ): Belege erscheinen
  im CAO-Kassenjournal und sind DATEV-exportfähig, aber komplexer und abhängig
  von CAO-internem Buchungsverhalten (GEBUCHT-Flag). Klärung durch CAO-Experte
  über HAB-21 noch ausstehend. Bei positiver Klärung kann Option B ergänzend
  hinzugefügt werden.
- **Option A+B kombiniert**: möglich nach Klärung HAB-21.

**Auswirkungen:**
- DB-Benutzer benötigt `UPDATE`-Berechtigung auf `ARTIKEL`-Tabelle.
  Falls nicht vorhanden: Eskalation an COO/Board erforderlich (in
  Akzeptanzkriterien HAB-34 dokumentiert).
- Skipped: Positionen mit `ARTIKEL_ID IS NULL` oder `ARTIKEL_ID <= 0`
  (Warengruppen-Buchungen, CAO-Konvention ARTIKEL_ID = −99).
- Kein CAO-seitiger Audit-Trail für diese Bestandsänderungen (akzeptiert für v1).
