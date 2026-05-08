"""
Datenzugriff für Orga/Bestellwesen.

Quelle: CAO-Tabellen ``EKBESTELL`` + ``EKBESTELL_POS`` + ``EKBESTELL_INFO``,
JOIN ``ADRESSEN`` für die Lieferanten-Anzeige.

Phase 1: read-only (Übersicht + Detail).
Phase 2: editierbar — Liefertermin (kopf + pro Position), Pos-Status,
Bestellung stornieren. Schreibvorgänge folgen dem in der CAO-Binary
beobachteten SQL-Muster, kein _LOG-Snapshot (CAO loggt EKBESTELL nicht).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from common.db import get_db


# CAO-Mimik: STADIUM-Codes aus EKBESTELL und EKBESTELL_POS.
# Quelle: cao_faktura.exe (1.5.1.36) — UTF-16-Strings bei
#   0x00563b88 (EKBESTELL Kopf)  und  0x00562d68 (EKBESTELL_POS).
# Wir brauchen zwei getrennte Mappings, weil 9 in EKBESTELL "abgeschlossen"
# heisst, in EKBESTELL_POS aber "voll berechnet".

STADIUM_LABEL_KOPF = {
    0:   'in Bearbeitung',
    1:   'in Bearbeitung',
    2:   'offen',
    3:   'Teillieferung',
    4:   'Ersetzt',
    8:   'rest nicht lieferbar',
    9:   'abgeschlossen',
    93:  'Teillieferung WE',
    95:  'voll geliefert WE',
    99:  'abgerechnet',
    127: '*** STORNO ***',
}

STADIUM_LABEL_POS = {
    0:   'unbekannt',          # XT-Altdaten vor 2026-05-08
    2:   'offen',
    3:   'Teillieferung',
    4:   'Ersetzt',
    8:   'rest nicht lieferbar',
    9:   'voll berechnet',
    93:  'Teillieferung WE',
    95:  'voll geliefert WE',
    127: 'storniert',
}

# Backwarts-Kompat: Filter-Auswahl in der UI nutzt das Header-Mapping.
STADIUM_LABEL = STADIUM_LABEL_KOPF


def _stadium_label_kopf(code: int | None) -> str:
    if code is None:
        return '–'
    return STADIUM_LABEL_KOPF.get(int(code), f'?? - [{code}]')


def _stadium_label_pos(code: int | None) -> str:
    if code is None:
        return '–'
    return STADIUM_LABEL_POS.get(int(code), f'?? - [{code}]')


# Alias fuer Diagnose-Endpunkt (zeigt fuer beide Tabellen das jeweils
# passende Label, faellt auf Header zurueck).
def _stadium_label(code: int | None) -> str:
    return _stadium_label_kopf(code)


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
        r['stadium_label'] = _stadium_label_kopf(r.get('stadium'))
    return rows


def bestellung_detail(rec_id: int) -> dict[str, Any] | None:
    """Detail einer Bestellung: Header + Positionen.

    Liefert ``None``, falls die ``REC_ID`` nicht existiert.

    Pro Position kommt zusätzlich der Liefertermin aus ``EKBESTELL_INFO``
    mit (CAO speichert den Pos-Liefertermin dort, nicht in EKBESTELL_POS).
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
        kopf['stadium_label'] = _stadium_label_kopf(kopf.get('STADIUM'))

        cur.execute(
            """
            SELECT p.*,
                   ei.LIEFERTERMIN AS liefertermin
            FROM EKBESTELL_POS p
            LEFT JOIN EKBESTELL_INFO ei
                   ON ei.EKBESTPOS_ID = p.REC_ID
                  AND ei.ARTIKEL_ID   = p.ARTIKEL_ID
            WHERE p.EKBESTELL_ID = %s
            ORDER BY p.POSITION, p.REC_ID
            """,
            (int(rec_id),),
        )
        positionen = cur.fetchall()
        for p in positionen:
            p['stadium_label'] = _stadium_label_pos(p.get('STADIUM'))
    return {'kopf': kopf, 'positionen': positionen}


# ── Stufe 2: Schreibvorgänge ────────────────────────────────────────────────
#
# CAO loggt EKBESTELL-Änderungen nicht (kein EKBESTELL_LOG in der Binary
# auffindbar), daher schreiben wir direkt — kein HASHSUM-Snapshot nötig.
# Wir folgen den exakten SQL-Mustern aus cao_faktura.exe.

# CAO ignoriert beim Bulk-Liefertermin-Update Positionen die schon
# „erledigt" sind (rest nicht lieferbar / voll berechnet / storniert).
# Aus der Binary @0x0255b6e0:
#   AND EP.STADIUM NOT IN(8,9,127) AND EB.STADIUM NOT IN(9,127)
_POS_BEARBEITBAR_STADIUM_NOT_IN = (8, 9, 127)
_KOPF_BEARBEITBAR_STADIUM_NOT_IN = (9, 127)

# Status-Codes, die per UI gesetzt werden duerfen.
ERLAUBTE_POS_STADIUM_CODES = (2, 3, 4, 8, 9, 93, 95, 127)


def kopf_liefertermin_setzen(rec_id: int, datum: date | None) -> int:
    """Setzt den Liefertermin auf alle bearbeitbaren Positionen einer Bestellung.

    Schreibt in ``EKBESTELL_INFO``. Falls für eine Position noch kein
    EKBESTELL_INFO-Eintrag existiert, wird einer angelegt.

    Args:
        rec_id: REC_ID der Bestellung (EKBESTELL).
        datum: Neuer Liefertermin oder ``None`` zum Löschen.

    Returns:
        Anzahl der aktualisierten Positionen.
    """
    rec_id = int(rec_id)
    pos_skip = ','.join(str(c) for c in _POS_BEARBEITBAR_STADIUM_NOT_IN)
    kopf_skip = ','.join(str(c) for c in _KOPF_BEARBEITBAR_STADIUM_NOT_IN)
    n = 0
    with get_db() as cur:
        # 1) Kopfstatus prüfen — abgeschlossene/stornierte Bestellungen
        # nicht anfassen.
        cur.execute(
            "SELECT STADIUM FROM EKBESTELL WHERE REC_ID = %s",
            (rec_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Bestellung {rec_id} nicht gefunden')
        if int(row['STADIUM']) in _KOPF_BEARBEITBAR_STADIUM_NOT_IN:
            raise PermissionError(
                f'Bestellung {rec_id} hat STADIUM={row["STADIUM"]} '
                f'und ist gesperrt (abgeschlossen oder storniert).'
            )
        # 2) Existierende EKBESTELL_INFO-Eintraege updaten.
        cur.execute(
            f"""
            UPDATE EKBESTELL_INFO ei
            INNER JOIN EKBESTELL_POS p ON p.REC_ID = ei.EKBESTPOS_ID
               SET ei.LIEFERTERMIN = %s
             WHERE p.EKBESTELL_ID = %s
               AND p.STADIUM NOT IN ({pos_skip})
            """,
            (datum, rec_id),
        )
        n += cur.rowcount
        # 3) Fehlende EKBESTELL_INFO-Eintraege anlegen — fuer Positionen
        # ohne bestehenden Eintrag.
        cur.execute(
            f"""
            SELECT p.REC_ID AS pos_id, p.ARTIKEL_ID AS art_id
              FROM EKBESTELL_POS p
              LEFT JOIN EKBESTELL_INFO ei
                     ON ei.EKBESTPOS_ID = p.REC_ID
                    AND ei.ARTIKEL_ID   = p.ARTIKEL_ID
             WHERE p.EKBESTELL_ID = %s
               AND p.STADIUM NOT IN ({pos_skip})
               AND ei.LIEFERTERMIN IS NULL
            """,
            (rec_id,),
        )
        fehlend = cur.fetchall()
        for r in fehlend:
            cur.execute(
                "INSERT INTO EKBESTELL_INFO (ARTIKEL_ID, EKBESTPOS_ID, LIEFERTERMIN) "
                "VALUES (%s, %s, %s)",
                (r['art_id'], r['pos_id'], datum),
            )
            n += cur.rowcount
    return n


def position_liefertermin_setzen(pos_id: int, datum: date | None) -> None:
    """Setzt den Liefertermin einer einzelnen Position (EKBESTELL_INFO).

    Legt den Eintrag an, falls er noch nicht existiert.
    """
    pos_id = int(pos_id)
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, ARTIKEL_ID, STADIUM, EKBESTELL_ID "
            "FROM EKBESTELL_POS WHERE REC_ID = %s",
            (pos_id,),
        )
        pos = cur.fetchone()
        if not pos:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        if int(pos['STADIUM']) in _POS_BEARBEITBAR_STADIUM_NOT_IN:
            raise PermissionError(
                f'Position {pos_id} (STADIUM={pos["STADIUM"]}) ist gesperrt'
            )
        cur.execute(
            "SELECT LIEFERTERMIN FROM EKBESTELL_INFO "
            "WHERE EKBESTPOS_ID = %s AND ARTIKEL_ID = %s",
            (pos_id, pos['ARTIKEL_ID']),
        )
        if cur.fetchone():
            cur.execute(
                "UPDATE EKBESTELL_INFO SET LIEFERTERMIN = %s "
                "WHERE EKBESTPOS_ID = %s AND ARTIKEL_ID = %s",
                (datum, pos_id, pos['ARTIKEL_ID']),
            )
        else:
            cur.execute(
                "INSERT INTO EKBESTELL_INFO (ARTIKEL_ID, EKBESTPOS_ID, LIEFERTERMIN) "
                "VALUES (%s, %s, %s)",
                (pos['ARTIKEL_ID'], pos_id, datum),
            )


def position_status_setzen(pos_id: int, stadium: int) -> None:
    """Setzt das STADIUM einer einzelnen Position (EKBESTELL_POS)."""
    pos_id = int(pos_id)
    stadium = int(stadium)
    if stadium not in ERLAUBTE_POS_STADIUM_CODES:
        raise ValueError(f'STADIUM={stadium} ist nicht erlaubt')
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, STADIUM FROM EKBESTELL_POS WHERE REC_ID = %s",
            (pos_id,),
        )
        pos = cur.fetchone()
        if not pos:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        if int(pos['STADIUM']) == 127 and stadium != 127:
            raise PermissionError('Stornierte Position kann nicht reaktiviert werden')
        cur.execute(
            "UPDATE EKBESTELL_POS SET STADIUM = %s WHERE REC_ID = %s",
            (stadium, pos_id),
        )


def bestellung_stornieren(rec_id: int) -> dict[str, int]:
    """Storniert eine komplette Bestellung.

    Setzt EKBESTELL.STADIUM=127 sowie alle EKBESTELL_POS.STADIUM=127.
    Folgt der CAO-Mimik aus der Binary @0x0256dd30 / @0x0256ddb0.

    Returns:
        Dict mit `kopf_geaendert`, `positionen_geaendert`.
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, STADIUM, BELEGNUM FROM EKBESTELL WHERE REC_ID = %s",
            (rec_id,),
        )
        b = cur.fetchone()
        if not b:
            raise LookupError(f'Bestellung {rec_id} nicht gefunden')
        if int(b['STADIUM']) == 127:
            return {'kopf_geaendert': 0, 'positionen_geaendert': 0}
        cur.execute(
            "UPDATE EKBESTELL_POS SET STADIUM = 127 WHERE EKBESTELL_ID = %s",
            (rec_id,),
        )
        pos_n = cur.rowcount
        cur.execute(
            "UPDATE EKBESTELL SET STADIUM = 127 WHERE REC_ID = %s",
            (rec_id,),
        )
        kopf_n = cur.rowcount
    return {'kopf_geaendert': kopf_n, 'positionen_geaendert': pos_n}


def stadium_codes_in_use() -> list[dict[str, Any]]:
    """Welche STADIUM-Codes kommen tatsächlich in EKBESTELL und EKBESTELL_POS vor?

    Liefert pro STADIUM-Code aus jeder Tabelle Anzahl + Beispiel-Belegnummer,
    damit unbekannte Codes (z.B. 9, 127) direkt in CAO nachgeschlagen werden
    können.
    """
    out: list[dict[str, Any]] = []
    with get_db() as cur:
        # Header: EKBESTELL
        cur.execute(
            """
            SELECT b.STADIUM   AS code,
                   COUNT(*)    AS anzahl,
                   MIN(b.BELEGNUM) AS bsp_min_belegnum,
                   MAX(b.BELEGNUM) AS bsp_max_belegnum
              FROM EKBESTELL b
             GROUP BY b.STADIUM
             ORDER BY b.STADIUM
            """
        )
        for r in cur.fetchall():
            out.append({
                'tabelle':           'EKBESTELL',
                'code':              r['code'],
                'anzahl':            r['anzahl'],
                'label':             _stadium_label_kopf(r['code']),
                'bsp_min_belegnum':  r['bsp_min_belegnum'],
                'bsp_max_belegnum':  r['bsp_max_belegnum'],
            })
        # Positionen: EKBESTELL_POS
        cur.execute(
            """
            SELECT p.STADIUM   AS code,
                   COUNT(*)    AS anzahl,
                   MIN(p.BELEGNUM) AS bsp_min_belegnum,
                   MAX(p.BELEGNUM) AS bsp_max_belegnum
              FROM EKBESTELL_POS p
             GROUP BY p.STADIUM
             ORDER BY p.STADIUM
            """
        )
        for r in cur.fetchall():
            out.append({
                'tabelle':           'EKBESTELL_POS',
                'code':              r['code'],
                'anzahl':            r['anzahl'],
                'label':             _stadium_label_pos(r['code']),
                'bsp_min_belegnum':  r['bsp_min_belegnum'],
                'bsp_max_belegnum':  r['bsp_max_belegnum'],
            })
    return out


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
