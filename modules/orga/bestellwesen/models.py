"""
Datenzugriff für Orga/Bestellwesen.

Quelle: CAO-Tabellen ``EKBESTELL`` + ``EKBESTELL_POS``, JOIN ``ADRESSEN``
für die Lieferanten-Anzeige. Read-only in Phase 1.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from common.db import get_db


# CAO-Mimik: STADIUM-Codes aus EKBESTELL/EKBESTELL_POS.
# 1 = storniert, 2 = offen, 3 = teilgeliefert, 4 = vollstaendig geliefert.
# Reverse-engineered aus Beobachtung — wenn neue Codes auftauchen,
# einfach in dieses Mapping ergaenzen.
STADIUM_LABEL = {
    0: 'unbekannt',
    1: 'storniert',
    2: 'offen',
    3: 'teilgeliefert',
    4: 'geliefert',
}


def _stadium_label(code: int | None) -> str:
    if code is None:
        return '–'
    return STADIUM_LABEL.get(int(code), f'?? - [{code}]')


def bestellungen_liste(
    *,
    suche: str = '',
    stadium: int | None = None,
    von_datum: date | None = None,
    bis_datum: date | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Liste aller EKBESTELL-Köpfe mit Lieferant + Anzahl Positionen.

    Args:
        suche: Substring-Filter auf BELEGNUM oder Lieferantenname.
        stadium: STADIUM-Filter (z.B. 2=offen). None = alle.
        von_datum / bis_datum: BELEGDATUM-Range (inklusive).
        limit: Maximalanzahl Treffer (Default 200).
    """
    where = ['1=1']
    params: list[Any] = []
    if suche:
        where.append('(b.BELEGNUM LIKE %s OR a.NAME1 LIKE %s)')
        params.extend([f'%{suche}%', f'%{suche}%'])
    if stadium is not None:
        where.append('b.STADIUM = %s')
        params.append(int(stadium))
    if von_datum:
        where.append('b.BELEGDATUM >= %s')
        params.append(von_datum)
    if bis_datum:
        where.append('b.BELEGDATUM <= %s')
        params.append(bis_datum)
    params.append(int(limit))

    sql = f"""
        SELECT
            b.REC_ID                            AS rec_id,
            b.BELEGNUM                          AS belegnum,
            b.BELEGDATUM                        AS belegdatum,
            b.ADDR_ID                           AS addr_id,
            COALESCE(a.NAME1, '–')              AS lief_name,
            b.STADIUM                           AS stadium,
            b.NSUMME                            AS nsumme,
            b.MSUMME                            AS msumme,
            b.BSUMME                            AS bsumme,
            (
                SELECT COUNT(*) FROM EKBESTELL_POS p
                WHERE p.EKBESTELL_ID = b.REC_ID
            )                                   AS pos_anzahl
        FROM EKBESTELL b
        LEFT JOIN ADRESSEN a ON a.REC_ID = b.ADDR_ID
        WHERE {' AND '.join(where)}
        ORDER BY b.BELEGDATUM DESC, b.REC_ID DESC
        LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for r in rows:
        r['stadium_label'] = _stadium_label(r.get('stadium'))
    return rows


def bestellung_detail(rec_id: int) -> dict[str, Any] | None:
    """Detail einer Bestellung: Header + Positionen.

    Liefert ``None``, falls die ``REC_ID`` nicht existiert.
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT b.*,
                   COALESCE(a.NAME1, '–') AS lief_name,
                   COALESCE(a.STRASSE, '') AS lief_strasse,
                   COALESCE(a.HAUSNR, '') AS lief_hausnr,
                   COALESCE(a.LAND, '') AS lief_land,
                   COALESCE(a.PLZ, '') AS lief_plz,
                   COALESCE(a.ORT, '') AS lief_ort
            FROM EKBESTELL b
            LEFT JOIN ADRESSEN a ON a.REC_ID = b.ADDR_ID
            WHERE b.REC_ID = %s
            """,
            (int(rec_id),),
        )
        kopf = cur.fetchone()
        if not kopf:
            return None
        kopf['stadium_label'] = _stadium_label(kopf.get('STADIUM'))

        cur.execute(
            """
            SELECT p.*
            FROM EKBESTELL_POS p
            WHERE p.EKBESTELL_ID = %s
            ORDER BY p.POSITION, p.REC_ID
            """,
            (int(rec_id),),
        )
        positionen = cur.fetchall()
        for p in positionen:
            p['stadium_label'] = _stadium_label(p.get('STADIUM'))
    return {'kopf': kopf, 'positionen': positionen}


def stadium_codes_in_use() -> list[dict[str, Any]]:
    """Welche STADIUM-Codes kommen tatsächlich in EKBESTELL und EKBESTELL_POS vor?

    Hilft, das STADIUM_LABEL-Mapping ggf. zu ergänzen, ohne raten zu müssen.
    """
    with get_db() as cur:
        cur.execute(
            "SELECT 'EKBESTELL' AS tabelle, STADIUM AS code, COUNT(*) AS anzahl "
            "FROM EKBESTELL GROUP BY STADIUM "
            "UNION ALL "
            "SELECT 'EKBESTELL_POS', STADIUM, COUNT(*) "
            "FROM EKBESTELL_POS GROUP BY STADIUM "
            "ORDER BY tabelle, code"
        )
        rows = cur.fetchall()
    for r in rows:
        r['label'] = _stadium_label(r['code'])
    return rows


def heile_alte_positions_stadium() -> dict[str, int]:
    """Einmal-Migration: Alle ``EKBESTELL_POS.STADIUM=0`` auf 2 setzen,
    sofern die zugehörige Bestellung den Status 2 (offen) hat.

    Ursache: Vor dem 2026-05-08-Commit hat unser CAO-Sync STADIUM=0 in
    die Positionen geschrieben, was CAO als "?? - [0]" anzeigt. Native
    CAO-Bestellungen haben STADIUM=2.

    Returns:
        Dict mit `geheilt` (Anzahl aktualisierter Positionen).
    """
    with get_db() as cur:
        cur.execute(
            """
            UPDATE EKBESTELL_POS p
            JOIN EKBESTELL b ON b.REC_ID = p.EKBESTELL_ID
               SET p.STADIUM = 2
             WHERE p.STADIUM = 0
               AND b.STADIUM = 2
            """
        )
        n = cur.rowcount
    return {'geheilt': int(n)}
