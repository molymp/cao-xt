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

from contextlib import contextmanager
from datetime import date
from typing import Any

from common.db import get_db
from common.cao_lock import cao_record_lock, LOCK_MOD_EKBESTELL


@contextmanager
def _ekbestell_lock_db(ek_rec_id: int):
    """``get_db()``-Cursor mit CAO-Record-Lock auf der Bestellung
    (``cao_<db>_MOD_2060_RECID_<ekbestell_rec_id>``) — wie CAO Faktura
    beim Bearbeiten/Stornieren einer EKBESTELL. Lock auf derselben
    Connection wie die Schreibvorgänge. Für rec_id-keyed Editoren ein
    minimal-invasiver 1-Zeilen-Swap der ``with``-Zeile."""
    with get_db() as cur:
        with cao_record_lock(cur, LOCK_MOD_EKBESTELL, int(ek_rec_id)):
            yield cur


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


BESTELL_SORT = {
    'belegnr':   'b.BELEGNUM',
    'datum':     'b.BELEGDATUM',
    'lieferant': "COALESCE(a.NAME1, '')",
    'netto':     'b.NSUMME',
    'brutto':    'b.BSUMME',
    'stadium':   'b.STADIUM',
}
BESTELL_DEFAULT_ORDER = 'b.BELEGDATUM DESC, b.REC_ID DESC'


def bestellungen_liste(
    *,
    suche: str = '',
    stadium: int | None = None,
    storno_aus: bool = True,
    von_datum: date | None = None,
    bis_datum: date | None = None,
    sort_sql: str = BESTELL_DEFAULT_ORDER,
    limit: int = 2000,
) -> dict[str, Any]:
    """EKBESTELL-Köpfe eines Zeitraums (BELEGDATUM), serverseitig
    gefiltert + sortiert. Returns
    ``{'rows': [...], 'total': int, 'gekuerzt': bool}``.

    ``storno_aus`` (Default True) blendet STADIUM=127 (storniert) aus.
    """
    where = ['1=1']
    params: list[Any] = []
    if suche:
        where.append('(b.BELEGNUM LIKE %s OR a.NAME1 LIKE %s)')
        params.extend([f'%{suche}%', f'%{suche}%'])
    if stadium is not None:
        where.append('b.STADIUM = %s')
        params.append(int(stadium))
    if storno_aus:
        where.append('b.STADIUM <> 127')
    if von_datum:
        where.append('b.BELEGDATUM >= %s')
        params.append(von_datum)
    if bis_datum:
        where.append('b.BELEGDATUM <= %s')
        params.append(bis_datum)
    where_sql = ' AND '.join(where)

    with get_db() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM EKBESTELL b "
            f"LEFT JOIN ADRESSEN a ON a.REC_ID = b.ADDR_ID "
            f"WHERE {where_sql}",
            params,
        )
        total = int((cur.fetchone() or {}).get('n') or 0)
        cur.execute(
            f"""
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
            WHERE {where_sql}
            ORDER BY {sort_sql}
            LIMIT %s
            """,
            params + [int(limit)],
        )
        rows = cur.fetchall()
    for r in rows:
        r['stadium_label'] = _stadium_label_kopf(r.get('stadium'))
    return {'rows': rows, 'total': total,
            'gekuerzt': total > int(limit)}


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
                   ei.LIEFERTERMIN AS liefertermin,
                   COALESCE(we.geliefert, 0) AS geliefert_menge
            FROM EKBESTELL_POS p
            LEFT JOIN EKBESTELL_INFO ei
                   ON ei.EKBESTPOS_ID = p.REC_ID
                  AND ei.ARTIKEL_ID   = p.ARTIKEL_ID
            LEFT JOIN (
                SELECT ep.EKBESTELL_POS_ID AS pos_id,
                       SUM(ep.MENGE)       AS geliefert
                  FROM EKEINGANG_POS ep
                  JOIN EKEINGANG     e ON e.REC_ID = ep.EKEINGANG_ID
                 WHERE ep.GEBUCHT_FLAG = 'Y'
                   AND e.STADIUM <> 127
                 GROUP BY ep.EKBESTELL_POS_ID
            ) we ON we.pos_id = p.REC_ID
            WHERE p.EKBESTELL_ID = %s
            ORDER BY p.POSITION, p.REC_ID
            """,
            (int(rec_id),),
        )
        positionen = cur.fetchall()

        # Lieferscheine pro Pos: kann mehrere geben (Teillieferungen,
        # nachgereichte Lieferungen). Wir holen pro Bestellpos die
        # Liste in einem Bulk-Query und mappen auf die Pos.
        pos_ids = [int(p['REC_ID']) for p in positionen]
        ls_map: dict[int, list[dict]] = {pid: [] for pid in pos_ids}
        if pos_ids:
            fmt = ','.join(['%s'] * len(pos_ids))
            cur.execute(
                f"""SELECT ep.EKBESTELL_POS_ID AS pos_id,
                          ep.MENGE             AS menge,
                          e.REC_ID             AS we_rec_id,
                          e.BELEGNUM           AS we_belegnum,
                          e.LIEFNUM            AS liefnum,
                          e.LIEFDATUM          AS liefdatum
                     FROM EKEINGANG_POS ep
                     JOIN EKEINGANG     e ON e.REC_ID = ep.EKEINGANG_ID
                    WHERE ep.EKBESTELL_POS_ID IN ({fmt})
                      AND ep.GEBUCHT_FLAG = 'Y'
                      AND e.STADIUM <> 127
                    ORDER BY e.LIEFDATUM, e.REC_ID""",
                pos_ids,
            )
            for r in cur.fetchall():
                ls_map[int(r['pos_id'])].append({
                    'we_rec_id':   int(r['we_rec_id']),
                    'we_belegnum': r['we_belegnum'] or '',
                    'liefnum':     r['liefnum'] or '',
                    'liefdatum':   r['liefdatum'],
                    'menge':       float(r['menge'] or 0),
                })

        for p in positionen:
            p['stadium_label'] = _stadium_label_pos(p.get('STADIUM'))
            soll = float(p.get('MENGE') or 0)
            geliefert = float(p.get('geliefert_menge') or 0)
            p['fehlt_menge'] = max(0, soll - geliefert) if soll > 0 else 0
            p['lieferscheine'] = ls_map.get(int(p['REC_ID']), [])
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

# Status-Codes, die per UI direkt manipuliert werden duerfen. Nur die
# manuellen Aktionen — alles andere (Teillieferung, voll geliefert WE,
# voll berechnet, Storno-Code 127) entsteht entweder durch Wareneingang/
# Einkauf-Buchungen oder durch die explizite Storno-Aktion.
ERLAUBTE_POS_STADIUM_CODES = (2, 8)  # offen / rest nicht lieferbar


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
    with _ekbestell_lock_db(rec_id) as cur:
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
        # Schreibvorgänge unter CAO-Record-Lock der zugehörigen
        # Bestellung (MODUL_ID 2060, EKBESTELL.REC_ID aus dem Pos-SELECT).
        with cao_record_lock(cur, LOCK_MOD_EKBESTELL,
                             int(pos['EKBESTELL_ID'])):
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
            "SELECT REC_ID, STADIUM, EKBESTELL_ID "
            "FROM EKBESTELL_POS WHERE REC_ID = %s",
            (pos_id,),
        )
        pos = cur.fetchone()
        if not pos:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        if int(pos['STADIUM']) == 127 and stadium != 127:
            raise PermissionError('Stornierte Position kann nicht reaktiviert werden')
        with cao_record_lock(cur, LOCK_MOD_EKBESTELL,
                             int(pos['EKBESTELL_ID'])):
            cur.execute(
                "UPDATE EKBESTELL_POS SET STADIUM = %s WHERE REC_ID = %s",
                (stadium, pos_id),
            )


def kopf_metadata_setzen(rec_id: int,
                         lief_ab: str | None = None,
                         termin: date | None = None,
                         info_rtf: str | None = None) -> None:
    """Setzt Header-Metadaten der Bestellung.

    Felder die übergeben werden, werden geschrieben; ``None`` =
    nicht anfassen. Strings werden auf ``''`` getrimmt (CAO-Konvention:
    keine NULLs in optionalen VARCHAR-Spalten).

    - ``lief_ab``  → EKBESTELL.LIEF_AB (Auftragsbestätigungsnummer)
    - ``termin``   → EKBESTELL.TERMIN  (Header-Liefertermin)
    - ``info_rtf`` → EKBESTELL.INFO    (Lieferinfo, RTF-formatiert)
    """
    rec_id = int(rec_id)
    sets: list[str] = []
    params: list[Any] = []
    if lief_ab is not None:
        sets.append('LIEF_AB = %s')
        params.append(lief_ab[:50])  # CAO-Feld typischerweise begrenzt
    if termin is not None:
        sets.append('TERMIN = %s')
        params.append(termin)
    if info_rtf is not None:
        sets.append('INFO = %s')
        params.append(info_rtf)
    if not sets:
        return
    with _ekbestell_lock_db(rec_id) as cur:
        cur.execute(
            "SELECT STADIUM FROM EKBESTELL WHERE REC_ID = %s",
            (rec_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Bestellung {rec_id} nicht gefunden')
        if int(row['STADIUM']) in _KOPF_BEARBEITBAR_STADIUM_NOT_IN:
            raise PermissionError('Bestellung gesperrt (abgeschlossen / storniert)')
        params.append(rec_id)
        cur.execute(
            f"UPDATE EKBESTELL SET {', '.join(sets)} WHERE REC_ID = %s",
            params,
        )


def position_lieferpreis_setzen(pos_id: int, lieferpreis: float | None) -> dict[str, float]:
    """Setzt LIEFPREIS einer Position; GLIEFPREIS = LIEFPREIS × MENGE.

    Args:
        pos_id: REC_ID der EKBESTELL_POS-Zeile.
        lieferpreis: Neuer Stück-Lieferpreis (decimal). ``None`` = nichts
            tun.

    Returns:
        Dict mit ``lieferpreis`` und ``gliefpreis`` (wie geschrieben).
    """
    if lieferpreis is None:
        return {}
    pos_id = int(pos_id)
    lpreis = float(lieferpreis)
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, MENGE, STADIUM, EKBESTELL_ID "
            "FROM EKBESTELL_POS WHERE REC_ID = %s",
            (pos_id,),
        )
        pos = cur.fetchone()
        if not pos:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        if int(pos['STADIUM']) in _POS_BEARBEITBAR_STADIUM_NOT_IN:
            raise PermissionError(f'Position gesperrt (STADIUM={pos["STADIUM"]})')
        gpreis = round(lpreis * float(pos['MENGE'] or 0), 2)
        # CAO-Mimik (Binary @0x0255b32c):
        # UPDATE EKBESTELL_POS SET LIEFPREIS=:LPREIS, GLIEFPREIS=:GPREIS WHERE REC_ID=:ID
        with cao_record_lock(cur, LOCK_MOD_EKBESTELL,
                             int(pos['EKBESTELL_ID'])):
            cur.execute(
                "UPDATE EKBESTELL_POS SET LIEFPREIS = %s, GLIEFPREIS = %s "
                "WHERE REC_ID = %s",
                (lpreis, gpreis, pos_id),
            )
    return {'lieferpreis': lpreis, 'gliefpreis': gpreis}


def bestellung_rest_nicht_lieferbar(rec_id: int) -> dict[str, int]:
    """Setzt alle Positionen mit STADIUM in (2, 3) auf 8 — schließt damit
    die Bestellung mit „Rest nicht lieferbar" ab.

    CAO-Mimik (Binary @0x02563554):
    ``UPDATE EKBESTELL_POS SET STADIUM=8 WHERE STADIUM in(2,3)
       and EKBESTELL_ID=...``
    """
    rec_id = int(rec_id)
    with _ekbestell_lock_db(rec_id) as cur:
        cur.execute(
            "SELECT STADIUM FROM EKBESTELL WHERE REC_ID = %s",
            (rec_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Bestellung {rec_id} nicht gefunden')
        if int(row['STADIUM']) in _KOPF_BEARBEITBAR_STADIUM_NOT_IN:
            raise PermissionError('Bestellung gesperrt')
        cur.execute(
            "UPDATE EKBESTELL_POS SET STADIUM = 8 "
            "WHERE STADIUM IN (2, 3) AND EKBESTELL_ID = %s",
            (rec_id,),
        )
        n = cur.rowcount
    return {'positionen_geaendert': n}


def bestellung_storno_pruefung(rec_id: int) -> dict:
    """Pre-Check fuer Bestellung-Storno: gibt es nicht-stornierte
    Wareneingaenge oder EK-Rechnungen die diese Bestellung referenzieren?

    Returns:
        ``{'ok': bool, 'wareneingaenge': [...], 'ek_rechnungen': [...]}``
        ``ok`` = True wenn keine Blocker, sonst False.
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        # WE die (a) ueber EKEINGANG_POS.EKBESTELL_POS_ID verlinkt sind und
        # (b) nicht storniert sind (STADIUM != 127)
        cur.execute(
            """SELECT DISTINCT we.REC_ID AS we_id, we.BELEGNUM, we.STADIUM,
                      we.BELEGDATUM
                 FROM EKEINGANG we
                 JOIN EKEINGANG_POS wep ON wep.EKEINGANG_ID = we.REC_ID
                 JOIN EKBESTELL_POS bp  ON bp.REC_ID         = wep.EKBESTELL_POS_ID
                WHERE bp.EKBESTELL_ID = %s
                  AND we.STADIUM != 127
                ORDER BY we.REC_ID""",
            (rec_id,),
        )
        wes = cur.fetchall()

        # EK-Rechnungen (QUELLE=5) mit Pos die ueber QUELLE_SRC eine
        # EKBESTELL_POS dieser Bestellung referenzieren — nicht-storniert
        cur.execute(
            """SELECT DISTINCT j.REC_ID AS ek_id, j.VRENUM, j.STADIUM,
                      j.RDATUM
                 FROM JOURNAL j
                 JOIN JOURNALPOS jp ON jp.JOURNAL_ID = j.REC_ID
                 JOIN EKBESTELL_POS bp ON bp.REC_ID = jp.QUELLE_SRC
                WHERE bp.EKBESTELL_ID = %s
                  AND j.QUELLE        = 5
                  AND j.STADIUM       NOT IN (125, 126, 127)
                ORDER BY j.REC_ID""",
            (rec_id,),
        )
        eks = cur.fetchall()
    return {
        'ok': not wes and not eks,
        'wareneingaenge': wes,
        'ek_rechnungen': eks,
    }


def bestellung_stornieren(rec_id: int) -> dict[str, int]:
    """Storniert eine komplette Bestellung.

    Setzt EKBESTELL.STADIUM=127 sowie alle EKBESTELL_POS.STADIUM=127.
    Folgt der CAO-Mimik aus der Binary @0x0256dd30 / @0x0256ddb0.

    Vor dem Storno wird geprueft, ob nicht-stornierte Wareneingaenge oder
    EK-Rechnungen die Bestellung referenzieren — die muessten zuerst
    storniert werden. PermissionError mit detailliertem Hinweis.

    Returns:
        Dict mit `kopf_geaendert`, `positionen_geaendert`.
    """
    rec_id = int(rec_id)
    pruef = bestellung_storno_pruefung(rec_id)
    if not pruef['ok']:
        teile = []
        if pruef['wareneingaenge']:
            namen = [w.get('BELEGNUM') or f"#{w['we_id']}"
                     for w in pruef['wareneingaenge']]
            teile.append(f"Wareneingang: {', '.join(namen)}")
        if pruef['ek_rechnungen']:
            namen = [e.get('VRENUM') or f"#{e['ek_id']}"
                     for e in pruef['ek_rechnungen']]
            teile.append(f"EK-Rechnung: {', '.join(namen)}")
        raise PermissionError(
            'Storno blockiert — bitte zuerst stornieren: ' + ' / '.join(teile)
        )

    with _ekbestell_lock_db(rec_id) as cur:
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

    Kein CAO-Record-Lock: dies ist ein einmaliger, satzübergreifender
    Daten-Heal über ALLE Bestellungen (kein einzelner EKBESTELL.REC_ID,
    kein interaktiver Bearbeitungspfad). Ein Per-Record-Lock ist hier
    konzeptionell nicht anwendbar; bewusst ausgelassen.
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
