"""
Datenzugriff für den Orga-Wareneingang.

Phase A (read+write ohne Buchen):
- ``wareneingang_anlegen()``: aus einer EKBESTELL einen EKEINGANG-Beleg
  erzeugen, mit EKEINGANG_POS pro offener Bestellpos
- ``wareneingang_liste()``: Übersicht
- ``wareneingang_detail()``: Header + Pos
- Pos-Mengen + Lieferpreise editierbar
- Barcode-Scan (Stück + Gebinde via ARTIKEL_VPE)

Phase B (Buchen, EKBESTELL_POS.STADIUM=93/95) folgt separat.
Phase C (JOURNAL/QUELLE=15 + Bestand) ebenfalls.

CAO-Mimik aus cao_faktura.exe:
- ``INSERT INTO EKEINGANG_POS (EKEINGANG_ID, ARTIKELTYP, ARTIKEL_ID, …,
  MENGE_SOLL, ERSTELLT, ERST_NAME)`` (@0x0189c440)
- ``UPDATE EKEINGANG SET STADIUM=:ST WHERE REC_ID=:ID`` (@0x01f8df1c)
- Storno: ``UPDATE EKEINGANG SET STADIUM=127, BELEGNUM=concat(BELEGNUM,
  '- STORNO -') WHERE REC_ID=:ID`` (@0x01f8e6a4)
"""
from __future__ import annotations

from datetime import date
from typing import Any

from common.db import get_db, get_db_transaction
from common.einkauf import _next_registry_nummer  # type: ignore


# STADIUM-Codes EKEINGANG.
# Quelle: cao_faktura.exe @0x00563df8 (UTF-16-Strings, bestaetigt durch
# Live-Test).
#   0   = offen (in Bearbeitung, noch nicht gebucht)
#   2   = unberechnet (gebucht, aber EK-Rechnung steht aus)
#   3   = teilw. berechnet (manche Pos haben EK-Rechnung)
#   4   = unberechnet abgeschlossen
#   9   = voll berechnet (gebucht + alle Pos berechnet)
#   127 = storniert
STADIUM_LABEL_KOPF = {
    0:   'offen',
    2:   'unberechnet',
    3:   'teilw. berechnet',
    4:   'unberechnet abgeschlossen',
    9:   'voll berechnet',
    127: 'storniert',
}


def _label(code: int | None) -> str:
    if code is None:
        return '–'
    return STADIUM_LABEL_KOPF.get(int(code), f'?? - [{code}]')


# ── Anlegen aus EKBESTELL ────────────────────────────────────────────


def wareneingang_anlegen(bestell_rec_id: int,
                         ma_id: int | None,
                         ma_name: str | None) -> dict[str, Any]:
    """Erzeugt einen EKEINGANG-Beleg aus einer Bestellung.

    Pos werden aus EKBESTELL_POS kopiert (nur die noch nicht erledigten,
    STADIUM NOT IN (8,9,127)). Pro Pos wird MENGE_SOLL = Bestellmenge,
    MENGE = 0, GEBUCHT_FLAG='N', BERECHNET='N' geschrieben.

    Returns:
        dict mit ``rec_id``, ``belegnum``, ``positionen``.
    """
    bestell_rec_id = int(bestell_rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        # 1) Bestellung + Pos lesen
        cur.execute(
            """
            SELECT b.*, COALESCE(a.NAME1, '') AS lief_name
              FROM EKBESTELL b
         LEFT JOIN ADRESSEN a ON a.REC_ID = b.ADDR_ID
             WHERE b.REC_ID = %s
            """,
            (bestell_rec_id,),
        )
        kopf = cur.fetchone()
        if not kopf:
            raise LookupError(f'Bestellung {bestell_rec_id} nicht gefunden')
        if int(kopf['STADIUM']) in (9, 127):
            raise PermissionError('Bestellung ist abgeschlossen oder storniert')

        cur.execute(
            """
            SELECT * FROM EKBESTELL_POS
             WHERE EKBESTELL_ID = %s
               AND STADIUM NOT IN (8, 9, 127)
             ORDER BY POSITION, REC_ID
            """,
            (bestell_rec_id,),
        )
        pos_liste = cur.fetchall()
        if not pos_liste:
            raise ValueError('Keine offenen Positionen — Wareneingang nicht nötig')

        # 2) BELEGNUM aus REGISTRY (Counter heisst in CAO 'WARENEINGANG')
        belegnum = _next_registry_nummer(cur, 'WARENEINGANG')

        heute = date.today()
        ma_id_int = int(ma_id) if ma_id is not None else -1

        # 3) EKEINGANG-Header anlegen — übernimmt alle relevanten Felder aus
        # der Bestellung (Lieferant, Adressen, Steuersätze, Texte). Mengen-
        # Summen lassen wir vorerst auf 0 — werden beim Buchen neu berechnet.
        # Defensiv: nur die Felder schreiben, die EKEINGANG sicher hat.
        # Wir holen die Spalten-Liste live aus INFORMATION_SCHEMA und
        # bauen das INSERT-Statement dynamisch — so überlebt der Code
        # CAO-Versionen mit leicht abweichendem Schema.
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG'"
        )
        ekeingang_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

        # Wunsch-Werte (nur die in ekeingang_cols vorhandenen werden geschrieben)
        wunsch: dict[str, Any] = {
            'MA_ID':            ma_id_int,
            'ADDR_ID':          kopf.get('ADDR_ID', -1) or -1,
            'BELEGNUM':         belegnum,
            'BELEGDATUM':       heute,
            'LIEFART':          kopf.get('LIEFART', -1) or -1,
            'ZAHLART':          kopf.get('ZAHLART', -1) or -1,
            'GEGENKONTO':       kopf.get('GEGENKONTO', -1) or -1,
            'WAEHRUNG':         '€',
            'KURS':             1.0,
            'STADIUM':          0,
            'GEWICHT':          0,
            'MWST_0':           kopf.get('MWST_0', 0) or 0,
            'MWST_1':           kopf.get('MWST_1', 0) or 0,
            'MWST_2':           kopf.get('MWST_2', 0) or 0,
            'MWST_3':           kopf.get('MWST_3', 0) or 0,
            'AT_MWST':          kopf.get('AT_MWST', 0) or 0,
            'NSUMME':           0, 'NSUMME_0': 0, 'NSUMME_1': 0,
            'NSUMME_2':         0, 'NSUMME_3': 0,
            'MSUMME':           0, 'MSUMME_0': 0, 'MSUMME_1': 0,
            'MSUMME_2':         0, 'MSUMME_3': 0,
            'BSUMME':           0, 'BSUMME_0': 0, 'BSUMME_1': 0,
            'BSUMME_2':         0, 'BSUMME_3': 0,
            'ERSTELLT':         heute,
            'ERST_NAME':        ma_name_safe,
            'KUN_NUM':          kopf.get('KUN_NUM', '') or '',
            'KUN_ANREDE':       kopf.get('KUN_ANREDE', '') or '',
            'KUN_NAME1':        kopf.get('KUN_NAME1', '') or '',
            'KUN_NAME2':        kopf.get('KUN_NAME2', '') or '',
            'KUN_NAME3':        kopf.get('KUN_NAME3', '') or '',
            'KUN_ABTEILUNG':    kopf.get('KUN_ABTEILUNG', '') or '',
            'KUN_STRASSE':      kopf.get('KUN_STRASSE', '') or '',
            'KUN_HAUSNR':       kopf.get('KUN_HAUSNR', '') or '',
            'KUN_ADRESSZUSATZ': kopf.get('KUN_ADRESSZUSATZ', '') or '',
            'KUN_LAND':         kopf.get('KUN_LAND', 'DE') or 'DE',
            'KUN_PLZ':          kopf.get('KUN_PLZ', '') or '',
            'KUN_ORT':          kopf.get('KUN_ORT', '') or '',
            'KUN_UST_NUM':      kopf.get('KUN_UST_NUM', '') or '',
            'LIEF_ANREDE':      kopf.get('LIEF_ANREDE', '') or '',
            'LIEF_NAME1':       kopf.get('LIEF_NAME1', '') or '',
            'LIEF_NAME2':       kopf.get('LIEF_NAME2', '') or '',
            'LIEF_NAME3':       kopf.get('LIEF_NAME3', '') or '',
            'LIEF_ABTEILUNG':   kopf.get('LIEF_ABTEILUNG', '') or '',
            'LIEF_STRASSE':     kopf.get('LIEF_STRASSE', '') or '',
            'LIEF_HAUSNR':      kopf.get('LIEF_HAUSNR', '') or '',
            'LIEF_ADRESSZUSATZ': kopf.get('LIEF_ADRESSZUSATZ', '') or '',
            'LIEF_LAND':        kopf.get('LIEF_LAND', '') or '',
            'LIEF_PLZ':         kopf.get('LIEF_PLZ', '') or '',
            'LIEF_ORT':         kopf.get('LIEF_ORT', '') or '',
            'FIRMA_ID':         kopf.get('FIRMA_ID', 8) or 8,
            'INFO':             '',
            'KOPFTEXT':         '',
            'FUSSTEXT':         '',
            'PROJEKT':          '',
            'ZAHLART_NAME':     kopf.get('ZAHLART_NAME', '') or '',
            'ZAHLART_KURZ':     kopf.get('ZAHLART_KURZ', '') or '',
            'ZAHLART_LANG':     kopf.get('ZAHLART_LANG', '') or '',
            'LIEFART_NAME':     kopf.get('LIEFART_NAME', '') or '',
            'LIEFART_LANG':     kopf.get('LIEFART_LANG', '') or '',
            'BEREINIGT':        'N',
        }
        # Filter auf existierende Spalten — Reihenfolge ist deterministisch
        cols = [c for c in wunsch if c in ekeingang_cols]
        vals = [wunsch[c] for c in cols]
        platzhalter = ', '.join(['%s'] * len(cols))
        cur.execute(
            f"INSERT INTO EKEINGANG ({', '.join(cols)}) VALUES ({platzhalter})",
            vals,
        )
        ekeingang_id = cur.lastrowid

        # EKEINGANG_POS-Spalten ebenfalls dynamisch via INFORMATION_SCHEMA
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG_POS'"
        )
        ekepos_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

        # 4) EKEINGANG_POS pro Bestellpos kopieren — Felder soweit wie
        # möglich aus EKBESTELL_POS übernehmen, MENGE auf 0, MENGE_SOLL
        # = Bestellmenge.
        for idx, p in enumerate(pos_liste, start=1):
            wunsch_pos: dict[str, Any] = {
                'EKEINGANG_ID':       ekeingang_id,
                'EKBESTELL_POS_ID':   p['REC_ID'],
                'ADDR_ID':            int(kopf.get('ADDR_ID') or -1),
                'POSITION':           p.get('POSITION', idx) or idx,
                'VIEW_POS':           str(p.get('POSITION', idx) or idx),
                'ARTIKELTYP':         p.get('ARTIKELTYP', 'N') or 'N',
                'ARTIKEL_ID':         p.get('ARTIKEL_ID'),
                'ARTNUM':             (p.get('ARTNUM') or '')[:100],
                'BARCODE':            (p.get('BARCODE') or '')[:20],
                'MATCHCODE':          (p.get('MATCHCODE') or '')[:255],
                'WARENGRUPPE':        p.get('WARENGRUPPE'),
                'WARENGRUPPENNAME':   (p.get('WARENGRUPPENNAME') or '')[:250],
                'BEZEICHNUNG':        (p.get('BEZEICHNUNG') or ''),
                'BEZEICHNUNG_LAND':   '',
                'KURZBEZEICHNUNG':    (p.get('KURZBEZEICHNUNG') or '')[:150],
                'KURZBEZEICHNUNG_LAND': '',
                'ME_EINHEIT':         (p.get('ME_EINHEIT') or '')[:50],
                'ME_CODE':            (p.get('ME_CODE') or '')[:5],
                'PR_EINHEIT':         p.get('PR_EINHEIT', 1) or 1,
                'VPE':                p.get('VPE', 1) or 1,
                'GEWICHT':            p.get('GEWICHT', 0) or 0,
                'LAENGE':             p.get('LAENGE', '') or '',
                'BREITE':             p.get('BREITE', '') or '',
                'HOEHE':              p.get('HOEHE', '') or '',
                'GROESSE':            p.get('GROESSE', '') or '',
                'DIMENSION':          p.get('DIMENSION', '') or '',
                'STEUER_CODE':        p.get('STEUER_CODE', 0) or 0,
                'GEGENKTO':           p.get('GEGENKTO', '') or '',
                'BRUTTO_FLAG':        p.get('BRUTTO_FLAG', 'N') or 'N',
                'MENGE_SOLL':         p.get('MENGE', 0) or 0,
                'MENGE':              0,
                'EPREIS':             p.get('EPREIS', 0) or 0,
                'GPREIS':             0,
                'ALTTEIL_PROZ':       0,
                'ALTTEIL_FLAG':       'N',
                'GEBUCHT_FLAG':       'N',
                'BERECHNET':          'N',
                'SN_FLAG':            'N',
                'SET_ID':             p.get('SET_ID', 0) or 0,
                'TOP_POS_ID':         p.get('TOP_POS_ID', -1) or -1,
                'LAGER_ID':           -2,
                'FREITEXT':           '',
                'FREITEXT_LAND':      '',
                'FARBE':              '',
                'MATERIAL':           '',
                'ERST_NAME':          ma_name_safe,
                'STADIUM':            2,
            }
            cols = [c for c in wunsch_pos if c in ekepos_cols]
            vals = [wunsch_pos[c] for c in cols]
            # ERSTELLT mit NOW() — wir hängen das ans SQL als literal an
            erstellt_sql = ''
            if 'ERSTELLT' in ekepos_cols:
                cols.append('ERSTELLT')
                vals.append(None)  # Platzhalter, wir bauen das anders
            # Bequemer: ERSTELLT separat behandeln über NOW()
            if 'ERSTELLT' in cols:
                cols.remove('ERSTELLT')
                vals.pop()
            platzhalter = ', '.join(['%s'] * len(cols))
            extra_cols = ''
            extra_vals = ''
            if 'ERSTELLT' in ekepos_cols:
                extra_cols = ', ERSTELLT'
                extra_vals = ', NOW()'
            cur.execute(
                f"INSERT INTO EKEINGANG_POS ({', '.join(cols)}{extra_cols}) "
                f"VALUES ({platzhalter}{extra_vals})",
                vals,
            )

    return {
        'ok': True,
        'rec_id': ekeingang_id,
        'belegnum': belegnum,
        'positionen': len(pos_liste),
    }


# ── Übersicht / Detail ───────────────────────────────────────────────


def wareneingang_liste(*, suche: str = '', stadium: int | None = None,
                       limit: int = 200) -> list[dict[str, Any]]:
    """Liste aller EKEINGANG-Belege (read-only)."""
    where = ['1=1']
    params: list[Any] = []
    if suche:
        where.append('(e.BELEGNUM LIKE %s OR a.NAME1 LIKE %s)')
        params.extend([f'%{suche}%', f'%{suche}%'])
    if stadium is not None:
        where.append('e.STADIUM = %s')
        params.append(int(stadium))
    params.append(int(limit))

    # Bestell-Belegnummer wird ueber die Pos-Verknuepfung ermittelt:
    # EKEINGANG_POS.EKBESTELL_POS_ID → EKBESTELL_POS.EKBESTELL_ID →
    # EKBESTELL.BELEGNUM. Wenn ein Wareneingang Pos aus mehreren
    # Bestellungen enthaelt, zeigen wir die mit der niedrigsten REC_ID.
    sql = f"""
        SELECT
            e.REC_ID                            AS rec_id,
            e.BELEGNUM                          AS belegnum,
            e.BELEGDATUM                        AS belegdatum,
            e.STADIUM                           AS stadium,
            e.ADDR_ID                           AS addr_id,
            COALESCE(a.NAME1, '–')              AS lief_name,
            (
                SELECT COUNT(*) FROM EKEINGANG_POS p
                WHERE p.EKEINGANG_ID = e.REC_ID
            )                                   AS pos_anzahl,
            (
                SELECT b.BELEGNUM
                  FROM EKEINGANG_POS p
                  JOIN EKBESTELL_POS bp ON bp.REC_ID = p.EKBESTELL_POS_ID
                  JOIN EKBESTELL b      ON b.REC_ID  = bp.EKBESTELL_ID
                 WHERE p.EKEINGANG_ID = e.REC_ID
                 ORDER BY b.REC_ID
                 LIMIT 1
            )                                   AS bestell_belegnum
        FROM EKEINGANG e
        LEFT JOIN ADRESSEN a ON a.REC_ID = e.ADDR_ID
        WHERE {' AND '.join(where)}
        ORDER BY e.BELEGDATUM DESC, e.REC_ID DESC
        LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for r in rows:
        r['stadium_label'] = _label(r.get('stadium'))
    return rows


def wareneingang_detail(rec_id: int) -> dict[str, Any] | None:
    """Detail-Daten: Header + Positionen."""
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            """
            SELECT e.*,
                   COALESCE(a.NAME1, '–') AS lief_name,
                   COALESCE(a.STRASSE, '') AS lief_strasse,
                   COALESCE(a.HAUSNR, '') AS lief_hausnr,
                   COALESCE(a.LAND, '') AS lief_land,
                   COALESCE(a.PLZ, '') AS lief_plz,
                   COALESCE(a.ORT, '') AS lief_ort,
                   (
                       SELECT b.REC_ID
                         FROM EKEINGANG_POS p
                         JOIN EKBESTELL_POS bp ON bp.REC_ID = p.EKBESTELL_POS_ID
                         JOIN EKBESTELL b      ON b.REC_ID  = bp.EKBESTELL_ID
                        WHERE p.EKEINGANG_ID = e.REC_ID
                        ORDER BY b.REC_ID LIMIT 1
                   ) AS bestell_rec_id,
                   (
                       SELECT b.BELEGNUM
                         FROM EKEINGANG_POS p
                         JOIN EKBESTELL_POS bp ON bp.REC_ID = p.EKBESTELL_POS_ID
                         JOIN EKBESTELL b      ON b.REC_ID  = bp.EKBESTELL_ID
                        WHERE p.EKEINGANG_ID = e.REC_ID
                        ORDER BY b.REC_ID LIMIT 1
                   ) AS bestell_belegnum
              FROM EKEINGANG e
         LEFT JOIN ADRESSEN a ON a.REC_ID = e.ADDR_ID
             WHERE e.REC_ID = %s
            """,
            (rec_id,),
        )
        kopf = cur.fetchone()
        if not kopf:
            return None
        kopf['stadium_label'] = _label(kopf.get('STADIUM'))

        # Pos-Detail: bringt zusätzlich
        #   * lief_artnum     – Lieferanten-Artikelnummer aus EKBESTELL_POS.LIEFARTNUM
        #   * bestell_rec_id / bestell_belegnum – Verknüpfung zur Bestellung (falls weitergeführt)
        #   * rech_belegnum   – BELEGNUM der EK-Rechnung (JOURNAL.QUELLE=5),
        #                       falls die Pos schon berechnet wurde
        # Pos-Detail OHNE die korrelierende rech_belegnum-Subquery — die
        # holen wir separat per LEFT JOIN GROUP BY (1 Query statt N).
        cur.execute(
            """
            SELECT p.*,
                   bp.LIEFARTNUM         AS lief_artnum,
                   bp.MENGE              AS bestell_menge,
                   bp.EKBESTELL_ID       AS bestell_rec_id,
                   b.BELEGNUM            AS bestell_belegnum
              FROM EKEINGANG_POS p
              LEFT JOIN EKBESTELL_POS bp ON bp.REC_ID = p.EKBESTELL_POS_ID
              LEFT JOIN EKBESTELL     b  ON b.REC_ID  = bp.EKBESTELL_ID
             WHERE p.EKEINGANG_ID = %s
             ORDER BY p.POSITION, p.REC_ID
            """,
            (rec_id,),
        )
        pos = cur.fetchall()

        # EK-Rechnungs-Belegnummern für alle Pos in einer einzigen Query
        if pos:
            pos_ids = [int(p['REC_ID']) for p in pos]
            fmt = ','.join(['%s'] * len(pos_ids))
            cur.execute(
                f"""
                SELECT jp.QUELLE_WE AS pos_id,
                       MIN(j.VRENUM) AS vrenum
                  FROM JOURNALPOS jp
                  JOIN JOURNAL    j ON j.REC_ID = jp.JOURNAL_ID
                 WHERE jp.QUELLE = 5
                   AND j.STADIUM <> 127
                   AND jp.QUELLE_WE IN ({fmt})
                 GROUP BY jp.QUELLE_WE
                """,
                pos_ids,
            )
            rech_map = {int(r['pos_id']): r['vrenum'] for r in cur.fetchall()}
        else:
            rech_map = {}

        # Mappings zusammenführen + Fallback für MENGE_SOLL
        for r in pos:
            r['rech_belegnum'] = rech_map.get(int(r['REC_ID']))
            soll = r.get('MENGE_SOLL') or 0
            if not soll:
                soll = r.get('bestell_menge') or 0
            r['bestellt_anzeige'] = soll
    return {'kopf': kopf, 'positionen': pos}


# ── Mengen-Eingabe / Lieferpreis ─────────────────────────────────────


def _ist_bearbeitbar(cur, rec_id: int) -> dict[str, Any]:
    """Prüft, ob der Wareneingang noch editierbar ist.

    Nur STADIUM=0 (offen, in Bearbeitung) erlaubt Mengen-/Preis-Edits.
    Sobald gebucht oder storniert (2,3,4,9,127) ist die Pos read-only.
    """
    cur.execute("SELECT REC_ID, STADIUM FROM EKEINGANG WHERE REC_ID = %s", (rec_id,))
    row = cur.fetchone()
    if not row:
        raise LookupError(f'Wareneingang {rec_id} nicht gefunden')
    if int(row['STADIUM']) != 0:
        raise PermissionError(
            f'Wareneingang STADIUM={row["STADIUM"]} — nur "offen" (0) ist editierbar'
        )
    return row


def pos_menge_setzen(eingang_id: int, pos_id: int, menge: float) -> dict[str, Any]:
    """Setzt EKEINGANG_POS.MENGE und aktualisiert GPREIS = EPREIS × MENGE."""
    eingang_id = int(eingang_id)
    pos_id = int(pos_id)
    if menge < 0:
        raise ValueError('Menge muss >= 0 sein')
    with get_db() as cur:
        _ist_bearbeitbar(cur, eingang_id)
        cur.execute(
            "SELECT EPREIS FROM EKEINGANG_POS "
            "WHERE REC_ID = %s AND EKEINGANG_ID = %s",
            (pos_id, eingang_id),
        )
        p = cur.fetchone()
        if not p:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        gpreis = round(float(p['EPREIS'] or 0) * float(menge), 2)
        cur.execute(
            "UPDATE EKEINGANG_POS SET MENGE = %s, GPREIS = %s WHERE REC_ID = %s",
            (menge, gpreis, pos_id),
        )
    return {'menge': float(menge), 'gpreis': gpreis}


def pos_epreis_setzen(eingang_id: int, pos_id: int,
                      epreis: float) -> dict[str, Any]:
    """Setzt EKEINGANG_POS.EPREIS (Liefer-EK pro Stueck) und GPREIS."""
    eingang_id = int(eingang_id)
    pos_id = int(pos_id)
    if epreis < 0:
        raise ValueError('EK muss >= 0 sein')
    with get_db() as cur:
        _ist_bearbeitbar(cur, eingang_id)
        cur.execute(
            "SELECT MENGE FROM EKEINGANG_POS "
            "WHERE REC_ID = %s AND EKEINGANG_ID = %s",
            (pos_id, eingang_id),
        )
        p = cur.fetchone()
        if not p:
            raise LookupError(f'Position {pos_id} nicht gefunden')
        gpreis = round(float(epreis) * float(p['MENGE'] or 0), 2)
        cur.execute(
            "UPDATE EKEINGANG_POS SET EPREIS = %s, GPREIS = %s WHERE REC_ID = %s",
            (epreis, gpreis, pos_id),
        )
    return {'epreis': float(epreis), 'gpreis': gpreis}


# ── Barcode-Scan ──────────────────────────────────────────────────────


def _ean_lookup(cur, eingang_id: int, ean: str) -> tuple[int | None, int, str]:
    """Sucht in den drei moeglichen Quellen nach dem EAN und liefert
    (artikel_id, faktor, ean_typ) oder (None, 1, '') wenn nicht gefunden.

    Reihenfolge:
    1. CAO ARTIKEL.BARCODE / BARCODE2 / BARCODE3 → Faktor 1, Typ 'stueck'
    2. XT_EINKAUF_LIEF_ARTIKEL.BARCODE_STUECK → ueber Lief-Mapping zur
       CAO-Artikel-ID, Faktor 1, Typ 'lief_stueck'
    3. XT_EINKAUF_LIEF_ARTIKEL.BARCODE_KT → wie 2, aber Faktor = VPE_EK,
       Typ 'gebinde'

    Bei den XT-Lookups wird bevorzugt der Lieferant des Wareneingangs
    bzw. der zugeordnete CAO-ADDR_ID gematcht (sonst Vieldeutigkeit).
    """
    # 1) CAO ARTIKEL.BARCODE / BARCODE2 / BARCODE3
    cur.execute(
        "SELECT REC_ID FROM ARTIKEL "
        "WHERE BARCODE = %s OR BARCODE2 = %s OR BARCODE3 = %s "
        "LIMIT 1",
        (ean, ean, ean),
    )
    row = cur.fetchone()
    if row:
        return int(row['REC_ID']), 1, 'stueck'

    # Lieferant des Wareneingangs (CAO-ADDR_ID) zur Disambiguierung
    cur.execute("SELECT ADDR_ID FROM EKEINGANG WHERE REC_ID = %s", (eingang_id,))
    we_row = cur.fetchone()
    cao_lief_addr = int(we_row['ADDR_ID']) if we_row and we_row.get('ADDR_ID') else None

    # 2 + 3) XT-Tabelle defensiv abfragen — die Tabelle existiert ggf.
    # nicht in jeder Installation. Try/except + Fallback.
    try:
        cur.execute(
            """
            SELECT xla.ARTIKEL_NR_LIEF, xla.VPE_EK,
                   CASE WHEN xla.BARCODE_STUECK = %s THEN 'stueck'
                        WHEN xla.BARCODE_KT     = %s THEN 'gebinde' END AS treffer,
                   xl.CAO_LIEF_ID
              FROM XT_EINKAUF_LIEF_ARTIKEL xla
              JOIN XT_EINKAUF_LIEFERANT     xl ON xl.REC_ID = xla.LIEF_REC_ID
             WHERE xla.BARCODE_STUECK = %s OR xla.BARCODE_KT = %s
             ORDER BY (xl.CAO_LIEF_ID = %s) DESC
             LIMIT 1
            """,
            (ean, ean, ean, ean, cao_lief_addr or -1),
        )
        lief_row = cur.fetchone()
    except Exception:
        lief_row = None

    if not lief_row or not lief_row.get('ARTIKEL_NR_LIEF'):
        return None, 1, ''

    art_nr_lief = lief_row['ARTIKEL_NR_LIEF']
    treffer_typ = lief_row['treffer']
    faktor = int(lief_row.get('VPE_EK') or 1) if treffer_typ == 'gebinde' else 1
    cao_adr = lief_row.get('CAO_LIEF_ID') or cao_lief_addr

    # ARTIKEL_PREIS.BESTNUM = Lieferanten-Artikelnummer (PREIS_TYP=5)
    if cao_adr:
        cur.execute(
            "SELECT ARTIKEL_ID FROM ARTIKEL_PREIS "
            " WHERE BESTNUM = %s AND ADRESS_ID = %s AND PREIS_TYP = 5 "
            " LIMIT 1",
            (art_nr_lief, int(cao_adr)),
        )
        ap_row = cur.fetchone()
        if ap_row and ap_row.get('ARTIKEL_ID'):
            ean_typ = 'gebinde' if treffer_typ == 'gebinde' else 'lief_stueck'
            return int(ap_row['ARTIKEL_ID']), faktor, ean_typ

    return None, 1, ''


def scan_ean(eingang_id: int, ean: str) -> dict[str, Any]:
    """Sucht zu einem gescannten EAN die passende Position im Wareneingang.

    Returns:
        dict mit ``gefunden`` (bool), ``pos_id``, ``artikel_id``,
        ``artikel_name``, ``faktor``, ``menge_neu``. Falls nicht gefunden:
        nur ``gefunden=False`` + Hinweis.
    """
    eingang_id = int(eingang_id)
    ean = (ean or '').strip()
    if not ean:
        return {'gefunden': False, 'fehler': 'Leerer EAN'}

    with get_db() as cur:
        _ist_bearbeitbar(cur, eingang_id)
        artikel_id, faktor, ean_typ = _ean_lookup(cur, eingang_id, ean)

        if artikel_id is None:
            return {'gefunden': False,
                    'fehler': f'EAN {ean} keinem Artikel zugeordnet'}

        # Position im Wareneingang finden
        cur.execute(
            """
            SELECT REC_ID, ARTIKEL_ID, BEZEICHNUNG, MENGE, MENGE_SOLL
              FROM EKEINGANG_POS
             WHERE EKEINGANG_ID = %s AND ARTIKEL_ID = %s
             LIMIT 1
            """,
            (eingang_id, artikel_id),
        )
        pos = cur.fetchone()
        if not pos:
            return {'gefunden': False,
                    'fehler': f'Artikel {artikel_id} nicht in diesem Wareneingang'}

        # MENGE += faktor
        neue_menge = float(pos['MENGE'] or 0) + faktor
        ergebnis = pos_menge_setzen(eingang_id, int(pos['REC_ID']), neue_menge)

    return {
        'gefunden':       True,
        'pos_id':         int(pos['REC_ID']),
        'artikel_id':     artikel_id,
        'artikel_name':   pos['BEZEICHNUNG'],
        'ean_typ':        ean_typ,
        'faktor':         faktor,
        'menge_alt':      float(pos['MENGE'] or 0),
        'menge_neu':      ergebnis['menge'],
        'menge_soll':     float(pos['MENGE_SOLL'] or 0),
    }


def offene_bestell_positionen(eingang_id: int) -> list[dict[str, Any]]:
    """Liste aller offenen Bestellpositionen für den Lieferanten dieses
    Wareneingangs.

    Zeigt nur Pos, die noch nicht voll im WE oder voll berechnet sind.
    Mengen-Berechnung folgt CAO-Mimik @0x0249ed44 (EKBESTELL_OP-Pattern):
    - berechnet_ek = SUM(JOURNALPOS.MENGE WHERE QUELLE=5)  (EK-Rechnung)
    - we_gebucht  = SUM(EKEINGANG_POS.MENGE WHERE GEBUCHT_FLAG='Y')
    - op_menge_we = bestellmenge - we_gebucht
    - menge_offen = op_menge_we - sum(EKEINGANG_POS.MENGE in offenen WE)
    """
    eingang_id = int(eingang_id)
    with get_db() as cur:
        cur.execute(
            "SELECT ADDR_ID FROM EKEINGANG WHERE REC_ID = %s",
            (eingang_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Wareneingang {eingang_id} nicht gefunden')
        addr_id = int(row['ADDR_ID'] or -1)
        if addr_id <= 0:
            return []

        # 1) Hauptquery: Bestellpositionen ohne Aggregate (schnell)
        cur.execute(
            """
            SELECT bp.REC_ID                AS pos_id,
                   b.REC_ID                 AS bestell_id,
                   b.BELEGNUM               AS bestell_nr,
                   b.BELEGDATUM             AS datum,
                   b.LIEF_AB                AS lief_ab,
                   bp.POSITION              AS position,
                   bp.ARTIKEL_ID            AS artikel_id,
                   bp.ARTNUM                AS artnum,
                   bp.BEZEICHNUNG           AS bezeichnung,
                   bp.KURZBEZEICHNUNG       AS kurzbezeichnung,
                   bp.MENGE                 AS bestellmenge,
                   bp.ME_EINHEIT            AS me_einheit,
                   bp.PR_EINHEIT            AS pe,
                   bp.LIEFARTNUM            AS lief_artnum,
                   bp.STADIUM               AS pos_stadium
              FROM EKBESTELL_POS bp
              JOIN EKBESTELL     b  ON b.REC_ID = bp.EKBESTELL_ID
             WHERE b.ADDR_ID  = %s
               AND b.STADIUM  IN (2, 3, 4, 8)
               AND bp.STADIUM IN (2, 3, 4, 8)
               AND COALESCE(bp.MENGE, 0) > 0
             ORDER BY b.BELEGDATUM, b.BELEGNUM, bp.POSITION
            """,
            (addr_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return []

        pos_ids = [int(r['pos_id']) for r in rows]
        # 2) EK-Rechnungs-Mengen pro Pos (eine Query, GROUP BY)
        fmt = ','.join(['%s'] * len(pos_ids))
        cur.execute(
            f"""
            SELECT jp.QUELLE_SRC AS pos_id, SUM(jp.MENGE) AS s
              FROM JOURNALPOS jp
              JOIN JOURNAL    j ON j.REC_ID = jp.JOURNAL_ID
             WHERE jp.QUELLE_SRC IN ({fmt})
               AND jp.QUELLE = 5
               AND j.STADIUM <> 127
             GROUP BY jp.QUELLE_SRC
            """,
            pos_ids,
        )
        berechnet_ek_map = {int(r['pos_id']): float(r['s'] or 0)
                            for r in cur.fetchall()}

        # 3) WE-Mengen (gebucht + offen erfasst) pro Pos — eine Query
        cur.execute(
            f"""
            SELECT ekp.EKBESTELL_POS_ID AS pos_id,
                   SUM(CASE WHEN ekp.GEBUCHT_FLAG = 'Y' AND e.STADIUM <> 127
                            THEN ekp.MENGE ELSE 0 END) AS gebucht,
                   SUM(CASE WHEN ekp.GEBUCHT_FLAG = 'N' AND e.STADIUM = 0
                            THEN ekp.MENGE ELSE 0 END) AS offen_erfasst
              FROM EKEINGANG_POS ekp
              JOIN EKEINGANG     e ON e.REC_ID = ekp.EKEINGANG_ID
             WHERE ekp.EKBESTELL_POS_ID IN ({fmt})
             GROUP BY ekp.EKBESTELL_POS_ID
            """,
            pos_ids,
        )
        we_map = {int(r['pos_id']): (float(r['gebucht'] or 0),
                                     float(r['offen_erfasst'] or 0))
                  for r in cur.fetchall()}

    # Mengen ableiten + filtern
    out: list[dict[str, Any]] = []
    for r in rows:
        pid = int(r['pos_id'])
        bestellmenge   = float(r['bestellmenge'] or 0)
        berechnet_ek   = berechnet_ek_map.get(pid, 0)
        we_gebucht, we_offen_erfasst = we_map.get(pid, (0, 0))
        op_menge_ek = bestellmenge - berechnet_ek
        op_menge_we = bestellmenge - we_gebucht
        menge_offen = op_menge_we - we_offen_erfasst
        if menge_offen <= 0:
            continue
        r['berechnet_ek']      = berechnet_ek
        r['we_gebucht']        = we_gebucht
        r['we_offen_erfasst']  = we_offen_erfasst
        r['op_menge_ek']       = op_menge_ek
        r['op_menge_we']       = op_menge_we
        r['menge_offen']       = menge_offen
        out.append(r)
    return out


def pos_aus_bestellpos_anhaengen(eingang_id: int,
                                 bestell_pos_id: int,
                                 menge: float | None = None,
                                 ma_name: str | None = None) -> dict[str, Any]:
    """Hängt eine Bestellposition als neue Pos an einen offenen Wareneingang an.

    Args:
        eingang_id: REC_ID des EKEINGANG.
        bestell_pos_id: REC_ID der EKBESTELL_POS.
        menge: vorgewählte Liefermenge. ``None`` = 0 (User trägt manuell ein).
    """
    eingang_id = int(eingang_id)
    bestell_pos_id = int(bestell_pos_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        # Wareneingang muss editierbar sein
        cur.execute(
            "SELECT ADDR_ID, STADIUM FROM EKEINGANG WHERE REC_ID = %s",
            (eingang_id,),
        )
        we = cur.fetchone()
        if not we:
            raise LookupError(f'Wareneingang {eingang_id} nicht gefunden')
        if int(we['STADIUM']) != 0:
            raise PermissionError('Wareneingang ist nicht mehr offen')

        # Bestellpos lesen
        cur.execute(
            """
            SELECT bp.*, b.ADDR_ID AS bestell_addr_id, b.STADIUM AS bestell_stadium
              FROM EKBESTELL_POS bp
              JOIN EKBESTELL     b ON b.REC_ID = bp.EKBESTELL_ID
             WHERE bp.REC_ID = %s
            """,
            (bestell_pos_id,),
        )
        bp = cur.fetchone()
        if not bp:
            raise LookupError(f'Bestellpos {bestell_pos_id} nicht gefunden')
        if int(bp['bestell_addr_id']) != int(we['ADDR_ID']):
            raise PermissionError('Lieferant der Bestellung passt nicht zum Wareneingang')
        if bp['STADIUM'] not in (2, 3, 4, 8):
            raise PermissionError('Bestellposition ist nicht mehr offen')

        # Naechste POSITION finden
        cur.execute(
            "SELECT COALESCE(MAX(POSITION), 0) + 1 AS np "
            "FROM EKEINGANG_POS WHERE EKEINGANG_ID = %s",
            (eingang_id,),
        )
        pos_nr = int(cur.fetchone()['np'])

        # Schema von EKEINGANG_POS holen
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG_POS'"
        )
        ekepos_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

        wunsch_pos: dict[str, Any] = {
            'EKEINGANG_ID':       eingang_id,
            'EKBESTELL_POS_ID':   bestell_pos_id,
            'ADDR_ID':            int(we['ADDR_ID']),
            'POSITION':           pos_nr,
            'VIEW_POS':           str(pos_nr),
            'ARTIKELTYP':         bp.get('ARTIKELTYP', 'N') or 'N',
            'ARTIKEL_ID':         bp.get('ARTIKEL_ID'),
            'ARTNUM':             (bp.get('ARTNUM') or '')[:100],
            'BARCODE':            (bp.get('BARCODE') or '')[:20],
            'MATCHCODE':          (bp.get('MATCHCODE') or '')[:255],
            'WARENGRUPPE':        bp.get('WARENGRUPPE'),
            'WARENGRUPPENNAME':   (bp.get('WARENGRUPPENNAME') or '')[:250],
            'BEZEICHNUNG':        (bp.get('BEZEICHNUNG') or ''),
            'BEZEICHNUNG_LAND':   '',
            'KURZBEZEICHNUNG':    (bp.get('KURZBEZEICHNUNG') or '')[:150],
            'KURZBEZEICHNUNG_LAND': '',
            'ME_EINHEIT':         (bp.get('ME_EINHEIT') or '')[:50],
            'ME_CODE':            (bp.get('ME_CODE') or '')[:5],
            'PR_EINHEIT':         bp.get('PR_EINHEIT', 1) or 1,
            'VPE':                bp.get('VPE', 1) or 1,
            'GEWICHT':            bp.get('GEWICHT', 0) or 0,
            'STEUER_CODE':        bp.get('STEUER_CODE', 0) or 0,
            'GEGENKTO':           bp.get('GEGENKTO', '') or '',
            'BRUTTO_FLAG':        bp.get('BRUTTO_FLAG', 'N') or 'N',
            'MENGE_SOLL':         bp.get('MENGE', 0) or 0,
            'MENGE':              float(menge) if menge is not None else 0,
            'EPREIS':             bp.get('EPREIS', 0) or 0,
            'GPREIS':             0,
            'ALTTEIL_PROZ':       0,
            'ALTTEIL_FLAG':       'N',
            'GEBUCHT_FLAG':       'N',
            'BERECHNET':          'N',
            'SN_FLAG':            'N',
            'SET_ID':             bp.get('SET_ID', 0) or 0,
            'TOP_POS_ID':         bp.get('TOP_POS_ID', -1) or -1,
            'LAGER_ID':           -2,
            'FREITEXT':           '',
            'FREITEXT_LAND':      '',
            'FARBE':              '',
            'MATERIAL':           '',
            'ERST_NAME':          ma_name_safe,
            'STADIUM':            2,
        }
        cols = [c for c in wunsch_pos if c in ekepos_cols]
        vals = [wunsch_pos[c] for c in cols]
        platzhalter = ', '.join(['%s'] * len(cols))
        extra_cols = ''
        extra_vals = ''
        if 'ERSTELLT' in ekepos_cols:
            extra_cols = ', ERSTELLT'
            extra_vals = ', NOW()'
        cur.execute(
            f"INSERT INTO EKEINGANG_POS ({', '.join(cols)}{extra_cols}) "
            f"VALUES ({platzhalter}{extra_vals})",
            vals,
        )
        new_id = cur.lastrowid

    return {'pos_id': int(new_id), 'position': pos_nr}


def pos_entfernen(eingang_id: int, pos_id: int) -> dict[str, Any]:
    """Entfernt eine einzelne Wareneingangs-Position (siehe Bulk-Variante)."""
    return pos_entfernen_bulk(eingang_id, [pos_id])


def pos_entfernen_bulk(eingang_id: int, pos_ids: list[int]) -> dict[str, Any]:
    """Entfernt mehrere Positionen aus einem offenen Wareneingang in
    einer einzigen DELETE-Anweisung.

    Sperr-Logik wie ``pos_entfernen``: WE muss STADIUM=0 sein, Pos
    duerfen nicht GEBUCHT_FLAG='Y' haben — solche werden uebersprungen.
    """
    eingang_id = int(eingang_id)
    pos_ids = [int(p) for p in pos_ids if p]
    if not pos_ids:
        return {'entfernt': 0}
    with get_db() as cur:
        _ist_bearbeitbar(cur, eingang_id)
        # Filter: nur Pos die zu diesem WE gehoeren UND nicht gebucht sind
        fmt = ','.join(['%s'] * len(pos_ids))
        cur.execute(
            f"DELETE FROM EKEINGANG_POS "
            f" WHERE EKEINGANG_ID = %s "
            f"   AND COALESCE(GEBUCHT_FLAG, 'N') <> 'Y' "
            f"   AND REC_ID IN ({fmt})",
            [eingang_id] + pos_ids,
        )
        n = cur.rowcount
    return {'entfernt': int(n)}


def lieferant_suche(suchtext: str, limit: int = 30) -> list[dict[str, Any]]:
    """Sucht Lieferanten in ADRESSEN (Filter: muss in ADRESSEN_LIEF stehen)."""
    pat = f"%{(suchtext or '').strip()}%"
    if len(pat) < 4:  # nur 1 Zeichen ohne Wildcards → zu unscharf
        return []
    with get_db() as cur:
        cur.execute(
            """
            SELECT a.REC_ID                            AS addr_id,
                   COALESCE(NULLIF(TRIM(a.NAME1),''), '–') AS name,
                   COALESCE(NULLIF(TRIM(a.NAME2),''), '')  AS name2,
                   COALESCE(a.ORT, '')                 AS ort,
                   COALESCE(a.PLZ, '')                 AS plz,
                   COALESCE(a.KUNNUM1, '')             AS kunnum
              FROM ADRESSEN a
              JOIN ADRESSEN_LIEF al ON al.ADDR_ID = a.REC_ID
             WHERE a.NAME1   LIKE %s
                OR a.NAME2   LIKE %s
                OR a.KUNNUM1 LIKE %s
                OR a.ORT     LIKE %s
             ORDER BY a.NAME1
             LIMIT %s
            """,
            (pat, pat, pat, pat, int(limit)),
        )
        return cur.fetchall()


def artikel_suche(suchtext: str, limit: int = 30) -> list[dict[str, Any]]:
    """Suche in ARTIKEL: ARTNUM / BARCODE(2,3) / KURZNAME / MATCHCODE."""
    pat = f"%{(suchtext or '').strip()}%"
    if len(pat) < 4:
        return []
    with get_db() as cur:
        cur.execute(
            """
            SELECT a.REC_ID    AS artikel_id,
                   a.ARTNUM    AS artnum,
                   a.BARCODE   AS barcode,
                   a.KURZNAME  AS kurzname,
                   a.MATCHCODE AS matchcode,
                   a.EK_PREIS  AS ek_preis,
                   a.STEUER_CODE,
                   a.ARTIKELTYP,
                   a.PR_EINHEIT,
                   me.BEZEICHNUNG AS me_einheit,
                   me.ME_CODE     AS me_code,
                   wg.NAME        AS wgr_name,
                   a.WARENGRUPPE
              FROM ARTIKEL a
              LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
              LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
             WHERE (a.ARTNUM    LIKE %s
                 OR a.BARCODE   LIKE %s
                 OR a.BARCODE2  LIKE %s
                 OR a.BARCODE3  LIKE %s
                 OR a.KURZNAME  LIKE %s
                 OR a.MATCHCODE LIKE %s)
               AND a.ARTIKELTYP NOT IN ('L', 'K', 'S')
             ORDER BY a.KURZNAME
             LIMIT %s
            """,
            (pat, pat, pat, pat, pat, pat, int(limit)),
        )
        return cur.fetchall()


def wareneingang_anlegen_leer(addr_id: int,
                              ma_id: int | None,
                              ma_name: str | None) -> dict[str, Any]:
    """Erstellt einen leeren Wareneingang ohne Bestell-Bezug.

    Args:
        addr_id: ADRESSEN.REC_ID des Lieferanten
        ma_id, ma_name: erstellender Mitarbeiter

    Returns:
        dict mit ``rec_id`` und ``belegnum``.
    """
    addr_id = int(addr_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]
    ma_id_int = int(ma_id) if ma_id is not None else -1

    with get_db_transaction() as cur:
        # Adresse lesen
        cur.execute(
            "SELECT REC_ID, NAME1, NAME2, NAME3, STRASSE, HAUSNR, "
            "       LAND, PLZ, ORT, KUNNUM1, KRD_NUM "
            "  FROM ADRESSEN WHERE REC_ID = %s",
            (addr_id,),
        )
        adr = cur.fetchone()
        if not adr:
            raise LookupError(f'Lieferant-Adresse {addr_id} nicht gefunden')

        # Belegnummer
        belegnum = _next_registry_nummer(cur, 'WARENEINGANG')
        heute = date.today()

        # Spalten von EKEINGANG ermitteln (defensiv)
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG'"
        )
        cols_in_db = {r['COLUMN_NAME'] for r in cur.fetchall()}

        wunsch: dict[str, Any] = {
            'MA_ID':            ma_id_int,
            'ADDR_ID':          addr_id,
            'BELEGNUM':         belegnum,
            'BELEGDATUM':       heute,
            'WAEHRUNG':         '€',
            'KURS':             1.0,
            'STADIUM':          0,
            'GEWICHT':          0,
            'NSUMME':           0, 'NSUMME_0': 0, 'NSUMME_1': 0,
            'NSUMME_2':         0, 'NSUMME_3': 0,
            'MSUMME':           0, 'MSUMME_0': 0, 'MSUMME_1': 0,
            'MSUMME_2':         0, 'MSUMME_3': 0,
            'BSUMME':           0, 'BSUMME_0': 0, 'BSUMME_1': 0,
            'BSUMME_2':         0, 'BSUMME_3': 0,
            'GEGENKONTO':       int(adr.get('KRD_NUM') or -1),
            'ERSTELLT':         heute,
            'ERST_NAME':        ma_name_safe,
            'KUN_NUM':          adr.get('KUNNUM1', '') or '',
            'KUN_NAME1':        adr.get('NAME1', '') or '',
            'KUN_NAME2':        adr.get('NAME2', '') or '',
            'KUN_NAME3':        adr.get('NAME3', '') or '',
            'KUN_STRASSE':      adr.get('STRASSE', '') or '',
            'KUN_HAUSNR':       adr.get('HAUSNR', '') or '',
            'KUN_LAND':         adr.get('LAND', 'DE') or 'DE',
            'KUN_PLZ':          adr.get('PLZ', '') or '',
            'KUN_ORT':          adr.get('ORT', '') or '',
            'LIEF_NAME1':       adr.get('NAME1', '') or '',
            'LIEF_NAME2':       adr.get('NAME2', '') or '',
            'LIEF_NAME3':       adr.get('NAME3', '') or '',
            'LIEF_STRASSE':     adr.get('STRASSE', '') or '',
            'LIEF_HAUSNR':      adr.get('HAUSNR', '') or '',
            'LIEF_LAND':        adr.get('LAND', '') or '',
            'LIEF_PLZ':         adr.get('PLZ', '') or '',
            'LIEF_ORT':         adr.get('ORT', '') or '',
            'FIRMA_ID':         8,
            'INFO':             '',
            'KOPFTEXT':         '',
            'FUSSTEXT':         '',
            'PROJEKT':          '',
            'BEREINIGT':        'N',
        }
        cols = [c for c in wunsch if c in cols_in_db]
        vals = [wunsch[c] for c in cols]
        cur.execute(
            f"INSERT INTO EKEINGANG ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(cols))})",
            vals,
        )
        rec_id = cur.lastrowid

    return {'ok': True, 'rec_id': rec_id, 'belegnum': belegnum}


def pos_artikel_anhaengen(eingang_id: int,
                          artikel_id: int,
                          menge: float = 0,
                          ma_name: str | None = None) -> dict[str, Any]:
    """Hängt einen Artikel direkt (ohne Bestell-Bezug) an einen offenen Wareneingang."""
    eingang_id = int(eingang_id)
    artikel_id = int(artikel_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        cur.execute("SELECT ADDR_ID, STADIUM FROM EKEINGANG WHERE REC_ID = %s",
                    (eingang_id,))
        we = cur.fetchone()
        if not we:
            raise LookupError(f'Wareneingang {eingang_id} nicht gefunden')
        if int(we['STADIUM']) != 0:
            raise PermissionError('Wareneingang ist nicht mehr offen')

        # Artikel lesen
        cur.execute(
            """
            SELECT a.REC_ID, a.ARTNUM, a.BARCODE, a.MATCHCODE, a.KURZNAME,
                   a.LANGNAME, a.ARTIKELTYP, a.WARENGRUPPE, a.GEWICHT,
                   a.PR_EINHEIT, a.EK_PREIS, a.STEUER_CODE,
                   me.BEZEICHNUNG AS me_einheit, me.ME_CODE AS me_code,
                   wg.NAME        AS wgr_name
              FROM ARTIKEL a
              LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
              LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
             WHERE a.REC_ID = %s
            """,
            (artikel_id,),
        )
        art = cur.fetchone()
        if not art:
            raise LookupError(f'Artikel {artikel_id} nicht gefunden')

        # naechste Position
        cur.execute(
            "SELECT COALESCE(MAX(POSITION), 0) + 1 AS np "
            "FROM EKEINGANG_POS WHERE EKEINGANG_ID = %s",
            (eingang_id,),
        )
        pos_nr = int(cur.fetchone()['np'])

        # Schema
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG_POS'"
        )
        ekepos_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

        wunsch_pos: dict[str, Any] = {
            'EKEINGANG_ID':       eingang_id,
            'ADDR_ID':            int(we['ADDR_ID']),
            'POSITION':           pos_nr,
            'VIEW_POS':           str(pos_nr),
            'ARTIKELTYP':         art.get('ARTIKELTYP', 'N') or 'N',
            'ARTIKEL_ID':         art.get('REC_ID'),
            'ARTNUM':             (art.get('ARTNUM') or '')[:100],
            'BARCODE':            (art.get('BARCODE') or '')[:20],
            'MATCHCODE':          (art.get('MATCHCODE') or '')[:255],
            'WARENGRUPPE':        art.get('WARENGRUPPE'),
            'WARENGRUPPENNAME':   (art.get('wgr_name') or '')[:250],
            'BEZEICHNUNG':        (art.get('LANGNAME') or art.get('KURZNAME') or ''),
            'BEZEICHNUNG_LAND':   '',
            'KURZBEZEICHNUNG':    (art.get('KURZNAME') or '')[:150],
            'KURZBEZEICHNUNG_LAND': '',
            'ME_EINHEIT':         (art.get('me_einheit') or '')[:50],
            'ME_CODE':            (art.get('me_code') or '')[:5],
            'PR_EINHEIT':         art.get('PR_EINHEIT', 1) or 1,
            'VPE':                1,
            'GEWICHT':            art.get('GEWICHT', 0) or 0,
            'STEUER_CODE':        art.get('STEUER_CODE', 0) or 0,
            'GEGENKTO':           '',
            'BRUTTO_FLAG':        'N',
            'MENGE_SOLL':         0,            # ohne Bestell-Bezug
            'MENGE':              float(menge or 0),
            'EPREIS':             art.get('EK_PREIS', 0) or 0,
            'GPREIS':             round(float(menge or 0) * float(art.get('EK_PREIS') or 0), 2),
            'ALTTEIL_PROZ':       0,
            'ALTTEIL_FLAG':       'N',
            'GEBUCHT_FLAG':       'N',
            'BERECHNET':          'N',
            'SN_FLAG':            'N',
            'SET_ID':             0,
            'TOP_POS_ID':         -1,
            'LAGER_ID':           -2,
            'FREITEXT':           '',
            'FREITEXT_LAND':      '',
            'FARBE':              '',
            'MATERIAL':           '',
            'ERST_NAME':          ma_name_safe,
            'STADIUM':            2,
        }
        cols = [c for c in wunsch_pos if c in ekepos_cols]
        vals = [wunsch_pos[c] for c in cols]
        platzhalter = ', '.join(['%s'] * len(cols))
        extra_cols = ''
        extra_vals = ''
        if 'ERSTELLT' in ekepos_cols:
            extra_cols = ', ERSTELLT'
            extra_vals = ', NOW()'
        cur.execute(
            f"INSERT INTO EKEINGANG_POS ({', '.join(cols)}{extra_cols}) "
            f"VALUES ({platzhalter}{extra_vals})",
            vals,
        )
        new_id = cur.lastrowid

    return {'pos_id': int(new_id), 'position': pos_nr,
            'artikel_name': art.get('LANGNAME') or art.get('KURZNAME')}


def pos_artikel_anhaengen_bulk(eingang_id: int,
                               artikel_ids: list[int],
                               ma_name: str | None = None) -> dict[str, Any]:
    """Hängt mehrere Artikel in einem einzigen Datenbank-Vorgang an.

    Wesentlich schneller als N x ``pos_artikel_anhaengen`` weil
    EKEINGANG-/Artikel-/Schema-Lookups nur einmal stattfinden.
    """
    eingang_id = int(eingang_id)
    artikel_ids = [int(a) for a in artikel_ids if a]
    if not artikel_ids:
        return {'angehaengt': 0}
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        cur.execute("SELECT ADDR_ID, STADIUM FROM EKEINGANG WHERE REC_ID = %s",
                    (eingang_id,))
        we = cur.fetchone()
        if not we:
            raise LookupError(f'Wareneingang {eingang_id} nicht gefunden')
        if int(we['STADIUM']) != 0:
            raise PermissionError('Wareneingang ist nicht mehr offen')

        # Alle Artikel auf einen Schwung lesen — Reihenfolge erhalten via
        # Mapping artikel_id → row.
        fmt = ','.join(['%s'] * len(artikel_ids))
        cur.execute(
            f"""
            SELECT a.REC_ID, a.ARTNUM, a.BARCODE, a.MATCHCODE, a.KURZNAME,
                   a.LANGNAME, a.ARTIKELTYP, a.WARENGRUPPE, a.GEWICHT,
                   a.PR_EINHEIT, a.EK_PREIS, a.STEUER_CODE,
                   me.BEZEICHNUNG AS me_einheit, me.ME_CODE AS me_code,
                   wg.NAME        AS wgr_name
              FROM ARTIKEL a
              LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
              LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
             WHERE a.REC_ID IN ({fmt})
            """,
            artikel_ids,
        )
        art_map = {int(r['REC_ID']): r for r in cur.fetchall()}

        cur.execute(
            "SELECT COALESCE(MAX(POSITION), 0) + 1 AS np "
            "FROM EKEINGANG_POS WHERE EKEINGANG_ID = %s",
            (eingang_id,),
        )
        pos_nr = int(cur.fetchone()['np'])

        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'EKEINGANG_POS'"
        )
        ekepos_cols = {r['COLUMN_NAME'] for r in cur.fetchall()}

        angehaengt = 0
        for aid in artikel_ids:   # Reihenfolge wie im Request
            art = art_map.get(aid)
            if not art:
                continue
            wunsch_pos: dict[str, Any] = {
                'EKEINGANG_ID':       eingang_id,
                'ADDR_ID':            int(we['ADDR_ID']),
                'POSITION':           pos_nr,
                'VIEW_POS':           str(pos_nr),
                'ARTIKELTYP':         art.get('ARTIKELTYP', 'N') or 'N',
                'ARTIKEL_ID':         art.get('REC_ID'),
                'ARTNUM':             (art.get('ARTNUM') or '')[:100],
                'BARCODE':            (art.get('BARCODE') or '')[:20],
                'MATCHCODE':          (art.get('MATCHCODE') or '')[:255],
                'WARENGRUPPE':        art.get('WARENGRUPPE'),
                'WARENGRUPPENNAME':   (art.get('wgr_name') or '')[:250],
                'BEZEICHNUNG':        (art.get('LANGNAME') or art.get('KURZNAME') or ''),
                'BEZEICHNUNG_LAND':   '',
                'KURZBEZEICHNUNG':    (art.get('KURZNAME') or '')[:150],
                'KURZBEZEICHNUNG_LAND': '',
                'ME_EINHEIT':         (art.get('me_einheit') or '')[:50],
                'ME_CODE':            (art.get('me_code') or '')[:5],
                'PR_EINHEIT':         art.get('PR_EINHEIT', 1) or 1,
                'VPE':                1,
                'GEWICHT':            art.get('GEWICHT', 0) or 0,
                'STEUER_CODE':        art.get('STEUER_CODE', 0) or 0,
                'GEGENKTO':           '',
                'BRUTTO_FLAG':        'N',
                'MENGE_SOLL':         0,
                'MENGE':              0,
                'EPREIS':             art.get('EK_PREIS', 0) or 0,
                'GPREIS':             0,
                'ALTTEIL_PROZ':       0,
                'ALTTEIL_FLAG':       'N',
                'GEBUCHT_FLAG':       'N',
                'BERECHNET':          'N',
                'SN_FLAG':            'N',
                'SET_ID':             0,
                'TOP_POS_ID':         -1,
                'LAGER_ID':           -2,
                'FREITEXT':           '',
                'FREITEXT_LAND':      '',
                'FARBE':              '',
                'MATERIAL':           '',
                'ERST_NAME':          ma_name_safe,
                'STADIUM':            2,
            }
            cols = [c for c in wunsch_pos if c in ekepos_cols]
            vals = [wunsch_pos[c] for c in cols]
            platzhalter = ', '.join(['%s'] * len(cols))
            extra_cols = ''
            extra_vals = ''
            if 'ERSTELLT' in ekepos_cols:
                extra_cols = ', ERSTELLT'
                extra_vals = ', NOW()'
            cur.execute(
                f"INSERT INTO EKEINGANG_POS ({', '.join(cols)}{extra_cols}) "
                f"VALUES ({platzhalter}{extra_vals})",
                vals,
            )
            pos_nr += 1
            angehaengt += 1

    return {'angehaengt': angehaengt}


def storno(rec_id: int) -> dict[str, int]:
    """Storniert einen offenen Wareneingang (CAO-Mimik @0x01f8e6a4):
    EKEINGANG.STADIUM=127 + BELEGNUM mit '- STORNO -' suffix.

    Nur STADIUM=0 (offen) ist stornierbar. Bereits gebuchte/berechnete
    (2/3/4/9) muessen via CAO storniert werden.
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute("SELECT STADIUM FROM EKEINGANG WHERE REC_ID = %s", (rec_id,))
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Wareneingang {rec_id} nicht gefunden')
        st = int(row['STADIUM'])
        if st == 127:
            return {'ok': 0}
        if st != 0:
            raise PermissionError(
                f'Wareneingang STADIUM={st} (nicht 0/offen) — '
                f'Storno bitte in CAO Faktura'
            )
        cur.execute(
            "UPDATE EKEINGANG "
            "   SET STADIUM = 127, "
            "       BELEGNUM = CONCAT(BELEGNUM, '- STORNO -') "
            " WHERE REC_ID = %s",
            (rec_id,),
        )
    return {'ok': 1}
