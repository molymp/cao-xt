"""
CAO-XT Orga-App – CFO-Berichte (Phase 1)

Enthält parametrisierbare SQL-Queries für:
  1. Tagesumsatz         (JOURNAL + ZAHLUNGSARTEN)
  2. Monatsübersicht     (JOURNAL, VK/EK je Monat)
  3. Kassenbuch          (ZAHLUNGEN, FIBU_KTO=1000)
  4. EC-Umsätze          (JOURNAL + ZAHLUNGSARTEN = EC-KARTE)

SQL-Vorlagen stammen aus HAB-237 (CAO-Experte); alle :Param-Stellen
durch %s-Platzhalter für mysql.connector ersetzt.
"""

from __future__ import annotations

import io
import csv
from datetime import date, datetime
from typing import Any

from db import get_cao_db


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _serialize(val: Any) -> Any:
    """Wandelt Datetime/Decimal für JSON-Serialisierung um."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if hasattr(val, '__float__'):
        return float(val)
    return val


def _rows_to_dicts(rows: list[dict]) -> list[dict]:
    """Normalisiert alle Werte in einer Row-Liste."""
    return [{k: _serialize(v) for k, v in row.items()} for row in rows]


def _csv_response(zeilen: list[dict], spalten: list[str], dateiname: str) -> bytes:
    """Erzeugt eine UTF-8-BOM-kodierte CSV-Datei als bytes."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=spalten,
        delimiter=';',
        extrasaction='ignore',
        lineterminator='\r\n',
    )
    writer.writeheader()
    for z in zeilen:
        writer.writerow({k: str(v).replace('.', ',') if isinstance(v, float) else v
                         for k, v in z.items()})
    return buf.getvalue().encode('utf-8-sig')


# ── 1. Tagesumsatz ─────────────────────────────────────────────────────────────

TAGESUMSATZ_SQL = """
SELECT
    DATE(J.RDATUM)                        AS Datum,
    IFNULL(ZA.NAME, '?')                  AS Zahlart,
    MIN(J.VRENUM)                         AS Bon_Von,
    MAX(J.VRENUM)                         AS Bon_Bis,
    COUNT(*)                              AS Anzahl_Belege,
    SUM(J.BSUMME)                         AS Brutto_Gesamt,
    SUM(J.BSUMME_0)                       AS MwSt_0_Pct,
    SUM(J.BSUMME_2) + SUM(J.BSUMME_3)    AS MwSt_19_Pct,
    SUM(J.BSUMME_1)                       AS MwSt_7_Pct
FROM JOURNAL J
LEFT JOIN ZAHLUNGSARTEN ZA ON ZA.REC_ID = J.ZAHLART
WHERE J.QUELLE IN (3, 4)
  AND J.QUELLE_SUB = 2
  AND J.RDATUM BETWEEN %s AND %s
  AND J.STADIUM < 127
  AND J.ZAHLART <> 5
GROUP BY DATE(J.RDATUM), J.ZAHLART
ORDER BY J.RDATUM, J.ZAHLART ASC
"""

TAGESUMSATZ_SPALTEN = [
    'Datum', 'Zahlart', 'Bon_Von', 'Bon_Bis',
    'Anzahl_Belege', 'Brutto_Gesamt', 'MwSt_0_Pct', 'MwSt_19_Pct', 'MwSt_7_Pct',
]


def tagesumsatz(von: date, bis: date) -> list[dict]:
    """Tagesumsatz nach Zahlart für den angegebenen Zeitraum."""
    with get_cao_db() as cur:
        cur.execute(TAGESUMSATZ_SQL, (von, bis))
        return _rows_to_dicts(cur.fetchall())


def tagesumsatz_csv(von: date, bis: date) -> bytes:
    """Tagesumsatz als CSV-Download."""
    return _csv_response(tagesumsatz(von, bis), TAGESUMSATZ_SPALTEN,
                         f'tagesumsatz_{von}_{bis}.csv')


# ── 2. Monatsübersicht ─────────────────────────────────────────────────────────

MONATSUEBERSICHT_SQL = """
SELECT
    YEAR(J.RDATUM)                           AS Jahr,
    J.QUELLE                                 AS Art,
    SUM(IF(MONTH(J.RDATUM) =  1, J.NSUMME, 0)) AS Jan,
    SUM(IF(MONTH(J.RDATUM) =  2, J.NSUMME, 0)) AS Feb,
    SUM(IF(MONTH(J.RDATUM) =  3, J.NSUMME, 0)) AS Mrz,
    SUM(IF(MONTH(J.RDATUM) =  4, J.NSUMME, 0)) AS Apr,
    SUM(IF(MONTH(J.RDATUM) =  5, J.NSUMME, 0)) AS Mai,
    SUM(IF(MONTH(J.RDATUM) =  6, J.NSUMME, 0)) AS Jun,
    SUM(IF(MONTH(J.RDATUM) =  7, J.NSUMME, 0)) AS Jul,
    SUM(IF(MONTH(J.RDATUM) =  8, J.NSUMME, 0)) AS Aug,
    SUM(IF(MONTH(J.RDATUM) =  9, J.NSUMME, 0)) AS Sep,
    SUM(IF(MONTH(J.RDATUM) = 10, J.NSUMME, 0)) AS Okt,
    SUM(IF(MONTH(J.RDATUM) = 11, J.NSUMME, 0)) AS Nov,
    SUM(IF(MONTH(J.RDATUM) = 12, J.NSUMME, 0)) AS Dez,
    SUM(J.NSUMME)                              AS Summe
FROM JOURNAL J
WHERE YEAR(J.RDATUM) = %s
  AND J.STADIUM < 127
  AND J.QUELLE IN (3, 5)
GROUP BY YEAR(J.RDATUM), J.QUELLE
ORDER BY J.QUELLE
"""

MONATSUEBERSICHT_SPALTEN = [
    'Jahr', 'Art', 'Jan', 'Feb', 'Mrz', 'Apr', 'Mai', 'Jun',
    'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez', 'Summe',
]

# Monatsumsatz-Trend: eine Zeile pro Monat (für Chart.js)
MONATSTREND_SQL = """
SELECT
    YEAR(J.RDATUM)  AS Jahr,
    MONTH(J.RDATUM) AS Monat,
    SUM(J.NSUMME)   AS Netto_Summe
FROM JOURNAL J
WHERE YEAR(J.RDATUM) = %s
  AND J.QUELLE = 3
  AND J.STADIUM < 127
GROUP BY YEAR(J.RDATUM), MONTH(J.RDATUM)
ORDER BY MONTH(J.RDATUM)
"""


def monatsuebersicht(jahr: int) -> list[dict]:
    """Netto-Umsatz je Monat für VK (Quelle=3) und EK (Quelle=5)."""
    with get_cao_db() as cur:
        cur.execute(MONATSUEBERSICHT_SQL, (jahr,))
        return _rows_to_dicts(cur.fetchall())


def monatstrend(jahr: int) -> list[dict]:
    """Monatlicher VK-Nettoumsatz als Liste – für Chart.js."""
    with get_cao_db() as cur:
        cur.execute(MONATSTREND_SQL, (jahr,))
        return _rows_to_dicts(cur.fetchall())


def monatsuebersicht_csv(jahr: int) -> bytes:
    """Monatsübersicht als CSV-Download."""
    return _csv_response(monatsuebersicht(jahr), MONATSUEBERSICHT_SPALTEN,
                         f'monatsuebersicht_{jahr}.csv')


# ── 3. Kassenbuch ──────────────────────────────────────────────────────────────

KASSENBUCH_SQL = """
SELECT
    Z.DATUM,
    Z.QUELLE,
    Z.JOURNAL_ID,
    Z.BETRAG,
    Z.VERW_ZWECK,
    Z.BELEGNUM,
    Z.FIBU_KTO,
    Z.FIBU_GEGENKTO,
    Z.SKONTO_PROZ,
    Z.SKONTO_BETRAG,
    Z.ERSTELLT_AM,
    Z.ERSTELLT_NAME,
    J.QUELLE     AS JOURNAL_QUELLE,
    J.VRENUM     AS VRENUM
FROM ZAHLUNGEN Z
LEFT JOIN JOURNAL J ON J.REC_ID = Z.JOURNAL_ID
WHERE Z.FIBU_KTO = 1000
  AND Z.DATUM BETWEEN %s AND %s
ORDER BY Z.DATUM ASC, Z.BETRAG DESC
"""

KASSENBUCH_SPALTEN = [
    'DATUM', 'QUELLE', 'JOURNAL_ID', 'BETRAG', 'VERW_ZWECK',
    'BELEGNUM', 'FIBU_KTO', 'FIBU_GEGENKTO', 'SKONTO_PROZ', 'SKONTO_BETRAG',
    'ERSTELLT_AM', 'ERSTELLT_NAME', 'JOURNAL_QUELLE', 'VRENUM',
]


def kassenbuch(von: date, bis: date) -> list[dict]:
    """Kassenbucheinträge für den angegebenen Zeitraum (FIBU_KTO=1000)."""
    with get_cao_db() as cur:
        cur.execute(KASSENBUCH_SQL, (von, bis))
        return _rows_to_dicts(cur.fetchall())


def kassenbuch_csv(von: date, bis: date) -> bytes:
    """Kassenbuch als CSV-Download."""
    return _csv_response(kassenbuch(von, bis), KASSENBUCH_SPALTEN,
                         f'kassenbuch_{von}_{bis}.csv')


# ── 4. EC-Umsätze ──────────────────────────────────────────────────────────────

EC_UMSAETZE_SQL = """
SELECT
    DATE(J.RDATUM)       AS Datum,
    J.KBDATUM            AS Buchdatum,
    MIN(J.VRENUM)        AS RN_Von,
    MAX(J.VRENUM)        AS RN_Bis,
    COUNT(*)             AS Anzahl,
    SUM(CASE J.QUELLE
        WHEN 5 THEN IF(J.STADIUM NOT IN (127, 120, 121), J.BSUMME * -1, 0)
        ELSE        IF(J.STADIUM NOT IN (127, 120, 121), J.BSUMME,      0)
    END)                 AS Brutto_Summe
FROM JOURNAL J
LEFT JOIN ZAHLUNGEN Z
    ON Z.JOURNAL_ID = J.REC_ID AND Z.STORNO = 0
LEFT JOIN ZAHLUNGSARTEN ZA2
    ON ZA2.REC_ID = J.ZAHLART
WHERE J.RDATUM BETWEEN %s AND %s
  AND ZA2.NAME = 'EC-KARTE'
  AND J.QUELLE IN (3, 4, 5)
  AND ((J.QUELLE_SUB = 2)
       OR (J.QUELLE_SUB < 2
           AND Z.DATUM IS NOT NULL
           AND J.BEZAHLT_KASSE = 'Y'))
  AND J.STADIUM NOT IN (127, 120, 121)
  AND (Z.ZAHLART IN (1, 5, 6, -6) OR Z.ZAHLART IS NULL)
GROUP BY TO_DAYS(J.RDATUM), J.QUELLE_SUB, J.QUELLE,
         IFNULL(Z.ZAHLART, J.ZAHLART), J.WAEHRUNG
ORDER BY IFNULL(Z.DATUM, J.KBDATUM), J.ZAHLART, J.WAEHRUNG
"""

EC_UMSAETZE_SPALTEN = [
    'Datum', 'Buchdatum', 'RN_Von', 'RN_Bis', 'Anzahl', 'Brutto_Summe',
]


def ec_umsaetze(von: date, bis: date) -> list[dict]:
    """EC-Kartenumsätze für den angegebenen Zeitraum."""
    with get_cao_db() as cur:
        cur.execute(EC_UMSAETZE_SQL, (von, bis))
        return _rows_to_dicts(cur.fetchall())


def ec_umsaetze_csv(von: date, bis: date) -> bytes:
    """EC-Umsätze als CSV-Download."""
    return _csv_response(ec_umsaetze(von, bis), EC_UMSAETZE_SPALTEN,
                         f'ec_umsaetze_{von}_{bis}.csv')


# ── 5. Stunden-Heatmap (Umsatz je Wochentag × Stunde) ──────────────────────────
#
# Liefert pro (Wochentag, Stunde) den DURCHSCHNITTLICHEN Umsatz pro Tag im
# Zeitraum. Wir aggregieren erst je Tag, dann per AVG ueber alle Tage des
# selben Wochentags – sonst waere ein langer Zeitraum mit z.B. 8 Samstagen
# verzerrt gegenueber 7 Samstagen.
#
# Rueckgabe ist eine Matrix dict[wochentag(0..6)][stunde(0..23)] -> float
# plus die Eckdaten (min/max, Spannweite Stunden, Anzahl Tage je Wochentag).

UMSATZ_HEATMAP_SQL = """
SELECT
    DATE(J.RDATUM)        AS tag,
    WEEKDAY(J.RDATUM)     AS wtag,    -- 0=Mo … 6=So
    HOUR(J.RDATUM)        AS stunde,
    SUM(J.NSUMME)         AS umsatz
FROM JOURNAL J
WHERE J.QUELLE = 3
  AND J.STADIUM < 127
  AND DATE(J.RDATUM) BETWEEN %s AND %s
GROUP BY DATE(J.RDATUM), WEEKDAY(J.RDATUM), HOUR(J.RDATUM)
"""


def umsatz_heatmap(von: date, bis: date) -> dict:
    """Durchschnittlicher Bar-Umsatz je (Wochentag × Stunde) im Zeitraum.

    Aggregiert zunaechst je Tag, mittelt dann ueber Tage des selben
    Wochentags. So bekommt z.B. der Samstag den Wert "durchschnittlicher
    Samstags-Umsatz in dieser Stunde".
    """
    with get_cao_db() as cur:
        cur.execute(UMSATZ_HEATMAP_SQL, (von, bis))
        rows = list(cur.fetchall() or [])

    # Tagessummen je (wtag, tag, stunde)
    summen: dict[tuple[int, date, int], float] = {}
    tage_pro_wtag: dict[int, set] = {i: set() for i in range(7)}
    for r in rows:
        wt = int(r['wtag'])
        tag = r['tag']
        std = int(r['stunde']) if r['stunde'] is not None else 0
        umsatz = float(r['umsatz'] or 0)
        summen[(wt, tag, std)] = summen.get((wt, tag, std), 0.0) + umsatz
        tage_pro_wtag[wt].add(tag)

    # AVG je (wtag, stunde) ueber Anzahl Tage in tage_pro_wtag
    matrix: dict[int, dict[int, float]] = {i: {} for i in range(7)}
    for (wt, _tag, std), _umsatz in summen.items():
        matrix[wt].setdefault(std, 0.0)
    # leere Zeilen-Dict fuer alle 7 Wochentage
    for wt in range(7):
        anzahl_tage = len(tage_pro_wtag[wt]) or 1
        # Summe ueber alle Tage je Stunde
        std_summen: dict[int, float] = {}
        for (w, _tag, std), umsatz in summen.items():
            if w == wt:
                std_summen[std] = std_summen.get(std, 0.0) + umsatz
        for std, gesamt in std_summen.items():
            matrix[wt][std] = round(gesamt / anzahl_tage, 2)

    # Beobachtete Stunden-Spannweite + Max-Wert fuer Skalierung
    alle_stunden = sorted({s for w in matrix.values() for s in w.keys()})
    von_stunde = alle_stunden[0] if alle_stunden else 8
    bis_stunde = alle_stunden[-1] if alle_stunden else 19
    max_wert = max((v for w in matrix.values() for v in w.values()), default=0.0)

    return {
        'von':            von,
        'bis':            bis,
        'matrix':         matrix,
        'von_stunde':     von_stunde,
        'bis_stunde':     bis_stunde,
        'max_wert':       max_wert,
        'tage_pro_wtag':  {i: len(tage_pro_wtag[i]) for i in range(7)},
    }


def umsatz_heatmap_csv(von: date, bis: date) -> bytes:
    """Heatmap als CSV (eine Zeile je Wochentag, je Stunde eine Spalte)."""
    h = umsatz_heatmap(von, bis)
    von_s, bis_s = h['von_stunde'], h['bis_stunde']
    spalten = ['Wochentag'] + [f'{s:02d}:00' for s in range(von_s, bis_s + 1)]
    wtage = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    zeilen: list[dict] = []
    for wt in range(7):
        row: dict = {'Wochentag': wtage[wt]}
        for s in range(von_s, bis_s + 1):
            row[f'{s:02d}:00'] = h['matrix'][wt].get(s, 0.0)
        zeilen.append(row)
    return _csv_response(zeilen, spalten,
                         f'umsatz_heatmap_{von}_{bis}.csv')
