"""DATEV-Buchungsabfragen – direkte Portierung der PHP/MySQL-Teilabfragen.

Jede Funktion liefert einen SQL-SELECT-String (ohne führendes UNION).
build_full_query() setzt alle Teile mit UNION zusammen.
execute_query() führt die Abfrage aus und gibt eine Liste von Dicts zurück.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pymysql

from .config import Kontenplan

DATEV_COLUMNS = [
    'Waehrungskennung', 'SollHabenKennzeichen', 'Umsatz', 'BUSchluessel',
    'Gegenkonto', 'Belegfeld1', 'Belegfeld2', 'Datum', 'Konto',
    'Kostfeld1', 'Kostfeld2', 'Kostmenge', 'Skonto', 'Buchungstext',
    'Festschreibung',
]


# ---------------------------------------------------------------------------
# Teil 1 – Eingehende Lieferantenrechnungen (Wareneingang an Verbindlichkeit)
#           Alle Adressen außer Kundengruppe 998 (Versorger)
# ---------------------------------------------------------------------------

def _teil_1a(year: int, month: int, k: Kontenplan) -> str:
    """1a – Lieferantenrechnungen 0% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j1.BSUMME_0 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j1.BSUMME_0), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.WE0} AS Gegenkonto,
    j1.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j1.RDATUM, '%d%m') AS Datum,
    j1.GEGENKONTO AS Konto,
    j1.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j1.KUN_NAME1, ' 0%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j1
    LEFT OUTER JOIN ADRESSEN A ON j1.ADDR_ID = A.REC_ID
WHERE YEAR(j1.RDATUM) = {year}
    AND MONTH(j1.RDATUM) = {month}
    AND j1.QUELLE IN (5)
    AND j1.QUELLE_SUB != 2
    AND j1.BSUMME_0 != 0
    AND j1.STADIUM < 127
    AND A.KUNDENGRUPPE <> 998"""


def _teil_1b(year: int, month: int, k: Kontenplan) -> str:
    """1b – Lieferantenrechnungen 19% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j2.BSUMME_1 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j2.BSUMME_1), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.WE19} AS Gegenkonto,
    j2.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j2.RDATUM, '%d%m') AS Datum,
    j2.GEGENKONTO AS Konto,
    j2.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j2.KUN_NAME1, ' 19%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j2
    LEFT OUTER JOIN ADRESSEN A ON j2.ADDR_ID = A.REC_ID
WHERE YEAR(j2.RDATUM) = {year}
    AND MONTH(j2.RDATUM) = {month}
    AND j2.QUELLE IN (5)
    AND j2.QUELLE_SUB != 2
    AND j2.BSUMME_1 != 0
    AND j2.STADIUM < 127
    AND A.KUNDENGRUPPE <> 998"""


def _teil_1c(year: int, month: int, k: Kontenplan) -> str:
    """1c – Lieferantenrechnungen 7% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j3.BSUMME_2 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j3.BSUMME_2), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.WE7} AS Gegenkonto,
    j3.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j3.RDATUM, '%d%m') AS Datum,
    j3.GEGENKONTO AS Konto,
    j3.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j3.KUN_NAME1, ' 7%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j3
    LEFT OUTER JOIN ADRESSEN A ON j3.ADDR_ID = A.REC_ID
WHERE YEAR(j3.RDATUM) = {year}
    AND MONTH(j3.RDATUM) = {month}
    AND j3.QUELLE IN (5)
    AND j3.QUELLE_SUB != 2
    AND j3.BSUMME_2 != 0
    AND j3.STADIUM < 127
    AND A.KUNDENGRUPPE <> 998"""


def _teil_1d(year: int, month: int, k: Kontenplan) -> str:
    """1d – Lieferantenrechnungen 9% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j4.BSUMME_3 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j4.BSUMME_3), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.WE107} AS Gegenkonto,
    j4.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j4.RDATUM, '%d%m') AS Datum,
    j4.GEGENKONTO AS Konto,
    j4.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j4.KUN_NAME1, ' 9%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j4
    LEFT OUTER JOIN ADRESSEN A ON j4.ADDR_ID = A.REC_ID
WHERE YEAR(j4.RDATUM) = {year}
    AND MONTH(j4.RDATUM) = {month}
    AND j4.QUELLE IN (5)
    AND j4.QUELLE_SUB != 2
    AND j4.BSUMME_3 != 0
    AND j4.STADIUM < 127
    AND A.KUNDENGRUPPE <> 998"""


def _teil_1e(year: int, month: int, k: Kontenplan) -> str:
    """1e – Versorger-Rechnungen (Kundengruppe 998), zeilenweise mit Automatikkonto."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(jp20.GPREIS < 0, 'S', 'H') AS SollHabenKennzeichen,
    CASE
        WHEN jp20.BRUTTO_FLAG = 'Y'
        THEN
            CASE jp20.STEUER_CODE
                WHEN '0' THEN REPLACE(ABS(jp20.GPREIS), '.', ',')
                WHEN '1' THEN REPLACE(ABS(jp20.GPREIS), '.', ',')
                WHEN '2' THEN REPLACE(ABS(jp20.GPREIS), '.', ',')
            END
        ELSE
            CASE jp20.STEUER_CODE
                WHEN '0' THEN REPLACE(ABS(ROUND(jp20.GPREIS, 2)),       '.', ',')
                WHEN '1' THEN REPLACE(ABS(ROUND(jp20.GPREIS * 1.19, 2)), '.', ',')
                WHEN '2' THEN REPLACE(ABS(ROUND(jp20.GPREIS * 1.07, 2)), '.', ',')
            END
    END AS Umsatz,
    '' AS BUSchluessel,
    CASE jp20.STEUER_CODE
        WHEN '0' THEN CONCAT('10', jp20.GEGENKTO)
        WHEN '1' THEN CONCAT('90', jp20.GEGENKTO)
        WHEN '2' THEN CONCAT('80', jp20.GEGENKTO)
    END AS Gegenkonto,
    j20.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j20.RDATUM, '%d%m') AS Datum,
    j20.GEGENKONTO AS Konto,
    j20.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    LEFT(CONCAT(LEFT(A20.NAME1, 19), '* ', j20.VRENUM, ' ', COALESCE(jp20.BEZEICHNUNG, '')), 60) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNALPOS jp20
    LEFT OUTER JOIN JOURNAL j20 ON j20.REC_ID = jp20.JOURNAL_ID
    LEFT OUTER JOIN ADRESSEN A20 ON j20.ADDR_ID = A20.REC_ID
WHERE YEAR(j20.RDATUM) = {year}
    AND MONTH(j20.RDATUM) = {month}
    AND j20.QUELLE IN (5)
    AND j20.QUELLE_SUB != 2
    AND j20.BSUMME_1 != 0
    AND j20.STADIUM < 127
    AND jp20.ARTIKELTYP != 'T'
    AND A20.KUNDENGRUPPE = 998"""


# ---------------------------------------------------------------------------
# Teil 2 – Lieferantenrechnungen bezahlen (Verbindlichkeiten an Bank)
# ---------------------------------------------------------------------------

def _teil_2(year: int, month: int, k: Kontenplan) -> str:
    """2 – Zahlung von Lieferantenrechnungen."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(z1.BETRAG > 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(z1.BETRAG), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    z1.FIBU_GEGENKTO AS Gegenkonto,
    z1.BELEGNUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(z1.DATUM, '%d%m') AS Datum,
    z1.FIBU_KTO AS Konto,
    z1.FIBU_GEGENKTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    IF(z1.SKONTO_BETRAG != 0, REPLACE(REPLACE(z1.SKONTO_BETRAG, '.', ','), '-', ''), '') AS Skonto,
    z1.VERW_ZWECK AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM ZAHLUNGEN z1
WHERE YEAR(z1.DATUM) = {year}
    AND MONTH(z1.DATUM) = {month}
    AND z1.QUELLE IN (5)"""


# ---------------------------------------------------------------------------
# Teil 3 – Ausgehende Kundenrechnungen (Forderung an Umsatzerlöse)
# ---------------------------------------------------------------------------

def _teil_3a(year: int, month: int, k: Kontenplan) -> str:
    """3a – Kundenrechnungen 0% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j5.BSUMME_0 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j5.BSUMME_0), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    j5.GEGENKONTO AS Gegenkonto,
    j5.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j5.RDATUM, '%d%m') AS Datum,
    {k.WA0} AS Konto,
    j5.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j5.KUN_NAME1, ' 0%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j5
WHERE YEAR(j5.RDATUM) = {year}
    AND MONTH(j5.RDATUM) = {month}
    AND j5.QUELLE IN (3)
    AND j5.QUELLE_SUB != 2
    AND j5.BSUMME_0 != 0
    AND j5.STADIUM < 127"""


def _teil_3b(year: int, month: int, k: Kontenplan) -> str:
    """3b – Kundenrechnungen 19% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j6.BSUMME_1 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j6.BSUMME_1), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    j6.GEGENKONTO AS Gegenkonto,
    j6.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j6.RDATUM, '%d%m') AS Datum,
    {k.WA19} AS Konto,
    j6.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j6.KUN_NAME1, ' 19%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j6
WHERE YEAR(j6.RDATUM) = {year}
    AND MONTH(j6.RDATUM) = {month}
    AND j6.QUELLE IN (3)
    AND j6.QUELLE_SUB != 2
    AND j6.BSUMME_1 != 0
    AND j6.STADIUM < 127"""


def _teil_3c(year: int, month: int, k: Kontenplan) -> str:
    """3c – Kundenrechnungen 7% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(j7.BSUMME_2 < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(j7.BSUMME_2), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    j7.GEGENKONTO AS Gegenkonto,
    j7.VRENUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j7.RDATUM, '%d%m') AS Datum,
    {k.WA7} AS Konto,
    j7.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(j7.KUN_NAME1, ' 7%') AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j7
WHERE YEAR(j7.RDATUM) = {year}
    AND MONTH(j7.RDATUM) = {month}
    AND j7.QUELLE IN (3)
    AND j7.QUELLE_SUB != 2
    AND j7.BSUMME_2 != 0
    AND j7.STADIUM < 127"""


# ---------------------------------------------------------------------------
# Teil 4 – Kunde bezahlt Rechnung (Bank an Forderungen)
# ---------------------------------------------------------------------------

def _teil_4(year: int, month: int, k: Kontenplan) -> str:
    """4 – Eingang von Kundenzahlungen."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(z2.BETRAG < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(z2.BETRAG), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    z2.FIBU_KTO AS Gegenkonto,
    z2.BELEGNUM AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(z2.DATUM, '%d%m') AS Datum,
    z2.FIBU_GEGENKTO AS Konto,
    z2.FIBU_GEGENKTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    IF(z2.SKONTO_BETRAG != 0, REPLACE(REPLACE(z2.SKONTO_BETRAG, '.', ','), '-', ''), '') AS Skonto,
    z2.VERW_ZWECK AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM ZAHLUNGEN z2
WHERE YEAR(z2.DATUM) = {year}
    AND MONTH(z2.DATUM) = {month}
    AND z2.QUELLE IN (3)"""


# ---------------------------------------------------------------------------
# Teil 5 – Barverkäufe kumuliert pro Tag (Kasse an Umsatzerlöse)
# ---------------------------------------------------------------------------

def _teil_5a(year: int, month: int, k: Kontenplan) -> str:
    """5a – Tageseinnahmen bar 0% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j8.BSUMME_0) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j8.BSUMME_0)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Kasse} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j8.RDATUM, '%d%m'), '-', {k.WA0}, '-', MIN(j8.VRENUM), '-', MAX(j8.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j8.RDATUM, '%d%m') AS Datum,
    {k.WA0} AS Konto,
    '' AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j8.RDATUM, '%d%m'), '-', CAST({k.WA0} AS CHAR), '-', MIN(j8.VRENUM), '-', MAX(j8.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j8
WHERE YEAR(j8.RDATUM) = {year}
    AND MONTH(j8.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j8.ZAHLART = 1
GROUP BY DAY(RDATUM)"""


def _teil_5b(year: int, month: int, k: Kontenplan) -> str:
    """5b – Tageseinnahmen bar 19% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j9.BSUMME_1) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j9.BSUMME_1)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Kasse} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j9.RDATUM, '%d%m'), '-', {k.WA19}, '-', MIN(j9.VRENUM), '-', MAX(j9.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j9.RDATUM, '%d%m') AS Datum,
    {k.WA19} AS Konto,
    '' AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j9.RDATUM, '%d%m'), '-', CAST({k.WA19} AS CHAR), '-', MIN(j9.VRENUM), '-', MAX(j9.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j9
WHERE YEAR(j9.RDATUM) = {year}
    AND MONTH(j9.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j9.ZAHLART = 1
GROUP BY DAY(RDATUM)"""


def _teil_5c(year: int, month: int, k: Kontenplan) -> str:
    """5c – Tageseinnahmen bar 7% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j10.BSUMME_2) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j10.BSUMME_2)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Kasse} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j10.RDATUM, '%d%m'), '-', {k.WA7}, '-', MIN(j10.VRENUM), '-', MAX(j10.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j10.RDATUM, '%d%m') AS Datum,
    {k.WA7} AS Konto,
    '' AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j10.RDATUM, '%d%m'), '-', CAST({k.WA7} AS CHAR), '-', MIN(j10.VRENUM), '-', MAX(j10.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j10
WHERE YEAR(j10.RDATUM) = {year}
    AND MONTH(j10.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j10.ZAHLART = 1
GROUP BY DAY(RDATUM)"""


# ---------------------------------------------------------------------------
# Teil 6 – Kasseneinnahmen zur Bank gebracht (Geldtransit an Kasse)
# ---------------------------------------------------------------------------

def _teil_6(year: int, month: int, k: Kontenplan) -> str:
    """6 – Kassenumlage / Geldtransit."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(z3.BETRAG > 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(z3.BETRAG), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Geldtransit} AS Gegenkonto,
    CONCAT('Banktransit_', DATE_FORMAT(z3.DATUM, '%d%m'), '_', z3.REC_ID) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(z3.DATUM, '%d%m') AS Datum,
    z3.FIBU_KTO AS Konto,
    z3.FIBU_GEGENKTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(REPLACE(REPLACE(z3.VERW_ZWECK, CHAR(13), ''), CHAR(10), ''), ' ', DATE_FORMAT(z3.DATUM, '%d%m')) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM ZAHLUNGEN z3
WHERE YEAR(z3.DATUM) = {year}
    AND MONTH(z3.DATUM) = {month}
    AND z3.QUELLE IN (99)"""


# ---------------------------------------------------------------------------
# Teil 7 – EC-Kartenzahlungen kumuliert pro Tag (ECTransit an Umsatzerlöse)
# ---------------------------------------------------------------------------

def _teil_7a(year: int, month: int, k: Kontenplan) -> str:
    """7a – Tageseinnahmen EC-Karte 0% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j11.BSUMME_0) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j11.BSUMME_0)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.ECTransit} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j11.RDATUM, '%d%m'), '-', {k.WA0}, '-', MIN(j11.VRENUM), '-', MAX(j11.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j11.RDATUM, '%d%m') AS Datum,
    {k.WA0} AS Konto,
    j11.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j11.RDATUM, '%d%m'), '-', CAST({k.WA0} AS CHAR), '-', MIN(j11.VRENUM), '-', MAX(j11.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j11
WHERE YEAR(j11.RDATUM) = {year}
    AND MONTH(j11.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j11.ZAHLART = 6
    AND j11.BSUMME_0 != 0
GROUP BY DAY(RDATUM)"""


def _teil_7b(year: int, month: int, k: Kontenplan) -> str:
    """7b – Tageseinnahmen EC-Karte 19% USt."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j12.BSUMME_1) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j12.BSUMME_1)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.ECTransit} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j12.RDATUM, '%d%m'), '-', {k.WA19}, '-', MIN(j12.VRENUM), '-', MAX(j12.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j12.RDATUM, '%d%m') AS Datum,
    {k.WA19} AS Konto,
    j12.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j12.RDATUM, '%d%m'), '-', CAST({k.WA19} AS CHAR), '-', MIN(j12.VRENUM), '-', MAX(j12.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j12
WHERE YEAR(j12.RDATUM) = {year}
    AND MONTH(j12.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j12.ZAHLART = 6
    AND j12.BSUMME_1 != 0
GROUP BY DAY(RDATUM)"""


def _teil_7c(year: int, month: int, k: Kontenplan) -> str:
    """7c – Tageseinnahmen EC-Karte 7%+9% USt. (kombiniert)."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(SUM(j13.BSUMME_2) + SUM(j13.BSUMME_3) < 0, 'S', 'H') AS SollHabenKennzeichen,
    REPLACE(ABS(SUM(j13.BSUMME_2) + SUM(j13.BSUMME_3)), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.ECTransit} AS Gegenkonto,
    CONCAT(DATE_FORMAT(j13.RDATUM, '%d%m'), '-', {k.WA7}, '-', MIN(j13.VRENUM), '-', MAX(j13.VRENUM)) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(j13.RDATUM, '%d%m') AS Datum,
    {k.WA7} AS Konto,
    j13.GEGENKONTO AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT(DATE_FORMAT(j13.RDATUM, '%d%m'), '-', CAST({k.WA7} AS CHAR), '-', MIN(j13.VRENUM), '-', MAX(j13.VRENUM)) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM JOURNAL j13
WHERE YEAR(j13.RDATUM) = {year}
    AND MONTH(j13.RDATUM) = {month}
    AND QUELLE_SUB = 2
    AND QUELLE = 3
    AND j13.ZAHLART = 6
    AND (j13.BSUMME_2 != 0 OR j13.BSUMME_3 != 0)
GROUP BY DAY(RDATUM)"""


# ---------------------------------------------------------------------------
# Teil 8 – Wertstellung Tageseinnahmen auf Bankkonto (Bank an Geldtransit)
# ---------------------------------------------------------------------------

def _teil_8(year: int, month: int, k: Kontenplan) -> str:
    """8 – Bankwertstellung der Bareinzahlungen."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(z3.BETRAG > 0, 'H', 'S') AS SollHabenKennzeichen,
    REPLACE(ABS(z3.BETRAG), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Bank} AS Gegenkonto,
    CONCAT('Banktransit ', DATE_FORMAT(z3.VALUTA, '%d%m'), ' ', z3.BELEG) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(z3.VALUTA, '%d%m') AS Datum,
    {k.Geldtransit} AS Konto,
    '' AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT('Banktransit EUR ', z3.BETRAG, ' valuta ', DATE_FORMAT(z3.VALUTA, '%d.%m.'), ' ', z3.BELEG) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM XT_KTOAUS z3
WHERE YEAR(z3.VALUTA) = {year}
    AND MONTH(z3.VALUTA) = {month}
    AND z3.AUFTRAGSART = 'Einzahlungen'
    AND z3.ZP_ZE = ''
    AND z3.VERWENDUNGSZWECK = ''
    AND z3.KTO_IBAN = ''
    AND z3.BLZ_BIC = ''"""


# ---------------------------------------------------------------------------
# Teil 9 – Wertstellung EC-Zahlungen auf Bankkonto (Bank an ECTransit)
# ---------------------------------------------------------------------------

def _teil_9(year: int, month: int, k: Kontenplan) -> str:
    """9 – Bankwertstellung der EC-/TELECASH-Zahlungen."""
    return f"""
SELECT 'EUR' AS Waehrungskennung,
    IF(z3.BETRAG > 0, 'H', 'S') AS SollHabenKennzeichen,
    REPLACE(ABS(z3.BETRAG), '.', ',') AS Umsatz,
    '' AS BUSchluessel,
    {k.Bank} AS Gegenkonto,
    CONCAT('EC-Zahlungen ', DATE_FORMAT(z3.VALUTA, '%d%m'), ' ', z3.BELEG) AS Belegfeld1,
    '' AS Belegfeld2,
    DATE_FORMAT(z3.VALUTA, '%d%m') AS Datum,
    {k.ECTransit} AS Konto,
    '' AS Kostfeld1,
    '' AS Kostfeld2,
    '' AS Kostmenge,
    '' AS Skonto,
    CONCAT('EC-Zahlungen ', SUBSTR(z3.VERWENDUNGSZWECK, LOCATE('TELECASH ', z3.VERWENDUNGSZWECK) + 11, 4),
           ' EUR ', z3.BETRAG, ' valuta ', DATE_FORMAT(z3.VALUTA, '%d.%m.'), ' ', z3.BELEG) AS Buchungstext,
    {k.Festschreibungskennzeichen} AS Festschreibung
FROM XT_KTOAUS z3
WHERE YEAR(z3.VALUTA) = {year}
    AND MONTH(z3.VALUTA) = {month}
    AND z3.ZP_ZE = 'HABACHER DORFLADE'
    AND z3.VERWENDUNGSZWECK LIKE '%TELECASH%'"""


# ---------------------------------------------------------------------------
# Gesamtabfrage
# ---------------------------------------------------------------------------

_QUERY_PARTS = [
    _teil_1a, _teil_1b, _teil_1c, _teil_1d, _teil_1e,
    _teil_2,
    _teil_3a, _teil_3b, _teil_3c,
    _teil_4,
    _teil_5a, _teil_5b, _teil_5c,
    _teil_6,
    _teil_8, _teil_9,
    _teil_7a, _teil_7b, _teil_7c,
]


def build_full_query(year: int, month: int, kontenplan: Kontenplan | None = None) -> str:
    """Baut die vollständige UNION-Abfrage aller 19 Buchungsteile."""
    k = kontenplan or Kontenplan()
    parts = [fn(year, month, k) for fn in _QUERY_PARTS]
    return '\nUNION\n'.join(parts)


def execute_query(connection: 'pymysql.Connection', year: int, month: int,
                  kontenplan: Kontenplan | None = None) -> list[dict]:
    """Führt die Gesamtabfrage aus und gibt alle Buchungszeilen als Liste von Dicts zurück."""
    sql = build_full_query(year, month, kontenplan)
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return list(cursor.fetchall())
