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
        cur.execute(
            """
            INSERT INTO EKEINGANG (
              MA_ID, ADDR_ID, ASP_ID, LIEF_ADDR_ID, BELEGNUM, BELEGDATUM,
              LIEFART, ZAHLART, GEGENKONTO,
              WAEHRUNG, KURS, STADIUM, GEWICHT,
              MWST_0, MWST_1, MWST_2, MWST_3, AT_MWST,
              NSUMME_0, NSUMME_1, NSUMME_2, NSUMME_3, NSUMME,
              MSUMME_0, MSUMME_1, MSUMME_2, MSUMME_3, MSUMME,
              BSUMME_0, BSUMME_1, BSUMME_2, BSUMME_3, BSUMME,
              ERSTELLT, ERST_NAME,
              KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3,
              KUN_ABTEILUNG, KUN_STRASSE, KUN_HAUSNR, KUN_ADRESSZUSATZ,
              KUN_LAND, KUN_PLZ, KUN_ORT, KUN_UST_NUM,
              KUN_ADDR_ID,
              LIEF_ANREDE, LIEF_NAME1, LIEF_NAME2, LIEF_NAME3,
              LIEF_ABTEILUNG, LIEF_STRASSE, LIEF_HAUSNR,
              LIEF_ADRESSZUSATZ, LIEF_LAND, LIEF_PLZ, LIEF_ORT,
              FIRMA_ID, INFO, KOPFTEXT, FUSSTEXT, PROJEKT,
              ZAHLART_NAME, ZAHLART_KURZ, ZAHLART_LANG,
              LIEFART_NAME, LIEFART_LANG,
              BEREINIGT
            ) VALUES (
              %s, %s, %s, %s, %s, %s,
              %s, %s, %s,
              '€', 1.0, 0, 0,
              %s, %s, %s, %s, %s,
              0, 0, 0, 0, 0,
              0, 0, 0, 0, 0,
              0, 0, 0, 0, 0,
              %s, %s,
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s, %s,
              -1,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s,
              %s, '', '', '', '',
              %s, %s, %s,
              %s, %s,
              'N'
            )
            """,
            (
                ma_id_int, kopf.get('ADDR_ID', -1),
                kopf.get('ASP_ID', -1) or -1,
                kopf.get('LIEF_ADDR_ID', -1) or -1,
                belegnum, heute,
                kopf.get('LIEFART', -1) or -1,
                kopf.get('ZAHLART', -1) or -1,
                kopf.get('GEGENKONTO', -1) or -1,
                kopf.get('MWST_0', 0) or 0,
                kopf.get('MWST_1', 0) or 0,
                kopf.get('MWST_2', 0) or 0,
                kopf.get('MWST_3', 0) or 0,
                kopf.get('AT_MWST', 0) or 0,
                heute, ma_name_safe,
                kopf.get('KUN_NUM', '') or '', kopf.get('KUN_ANREDE', '') or '',
                kopf.get('KUN_NAME1', '') or '', kopf.get('KUN_NAME2', '') or '',
                kopf.get('KUN_NAME3', '') or '',
                kopf.get('KUN_ABTEILUNG', '') or '',
                kopf.get('KUN_STRASSE', '') or '',
                kopf.get('KUN_HAUSNR', '') or '',
                kopf.get('KUN_ADRESSZUSATZ', '') or '',
                kopf.get('KUN_LAND', 'DE') or 'DE',
                kopf.get('KUN_PLZ', '') or '',
                kopf.get('KUN_ORT', '') or '',
                kopf.get('KUN_UST_NUM', '') or '',
                kopf.get('LIEF_ANREDE', '') or '',
                kopf.get('LIEF_NAME1', '') or '',
                kopf.get('LIEF_NAME2', '') or '',
                kopf.get('LIEF_NAME3', '') or '',
                kopf.get('LIEF_ABTEILUNG', '') or '',
                kopf.get('LIEF_STRASSE', '') or '',
                kopf.get('LIEF_HAUSNR', '') or '',
                kopf.get('LIEF_ADRESSZUSATZ', '') or '',
                kopf.get('LIEF_LAND', '') or '',
                kopf.get('LIEF_PLZ', '') or '',
                kopf.get('LIEF_ORT', '') or '',
                kopf.get('FIRMA_ID', 8) or 8,
                kopf.get('ZAHLART_NAME', '') or '',
                kopf.get('ZAHLART_KURZ', '') or '',
                kopf.get('ZAHLART_LANG', '') or '',
                kopf.get('LIEFART_NAME', '') or '',
                kopf.get('LIEFART_LANG', '') or '',
            ),
        )
        ekeingang_id = cur.lastrowid

        # 4) EKEINGANG_POS pro Bestellpos kopieren — Felder so weit wie
        # möglich aus EKBESTELL_POS übernehmen, MENGE auf 0, MENGE_SOLL
        # = Bestellmenge.
        for idx, p in enumerate(pos_liste, start=1):
            cur.execute(
                """
                INSERT INTO EKEINGANG_POS (
                  EKEINGANG_ID, EKBESTELL_POS_ID, ADDR_ID,
                  POSITION, VIEW_POS,
                  ARTIKELTYP, ARTIKEL_ID, ARTNUM, BARCODE, MATCHCODE,
                  WARENGRUPPE, WARENGRUPPENNAME,
                  BEZEICHNUNG, BEZEICHNUNG_LAND,
                  KURZBEZEICHNUNG, KURZBEZEICHNUNG_LAND,
                  ME_EINHEIT, ME_CODE, PR_EINHEIT, VPE,
                  GEWICHT, LAENGE, BREITE, HOEHE, GROESSE, DIMENSION,
                  STEUER_CODE, GEGENKTO, BRUTTO_FLAG,
                  MENGE_SOLL, MENGE, EPREIS, GPREIS,
                  ALTTEIL_PROZ, ALTTEIL_FLAG,
                  GEBUCHT_FLAG, BERECHNET, SN_FLAG,
                  SET_ID, TOP_POS_ID, LAGER_ID,
                  FREITEXT, FREITEXT_LAND, FARBE, MATERIAL,
                  ERSTELLT, ERST_NAME, STADIUM
                ) VALUES (
                  %s, %s, %s,
                  %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s,
                  %s, '',
                  %s, '',
                  %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, 0, %s, 0,
                  0.00, 'N',
                  'N', 'N', 'N',
                  %s, %s, -2,
                  '', '', '', '',
                  NOW(), %s, 2
                )
                """,
                (
                    ekeingang_id, p['REC_ID'], int(kopf.get('ADDR_ID') or -1),
                    p.get('POSITION', idx) or idx, str(p.get('POSITION', idx) or idx),
                    p.get('ARTIKELTYP', 'N') or 'N',
                    p.get('ARTIKEL_ID'), (p.get('ARTNUM') or '')[:100],
                    (p.get('BARCODE') or '')[:20], (p.get('MATCHCODE') or '')[:255],
                    p.get('WARENGRUPPE'),
                    (p.get('WARENGRUPPENNAME') or '')[:250],
                    (p.get('BEZEICHNUNG') or ''),
                    (p.get('KURZBEZEICHNUNG') or '')[:150],
                    (p.get('ME_EINHEIT') or '')[:50],
                    (p.get('ME_CODE') or '')[:5],
                    p.get('PR_EINHEIT', 1) or 1, p.get('VPE', 1) or 1,
                    p.get('GEWICHT', 0) or 0,
                    p.get('LAENGE', '') or '', p.get('BREITE', '') or '',
                    p.get('HOEHE', '') or '', p.get('GROESSE', '') or '',
                    p.get('DIMENSION', '') or '',
                    p.get('STEUER_CODE', 0) or 0,
                    p.get('GEGENKTO', '') or '',
                    p.get('BRUTTO_FLAG', 'N') or 'N',
                    p.get('MENGE', 0) or 0,        # MENGE_SOLL = Bestellmenge
                    p.get('EPREIS', 0) or 0,        # EPREIS = Liefer-EK pro Stueck
                    p.get('SET_ID', 0) or 0,
                    p.get('TOP_POS_ID', -1) or -1,
                    ma_name_safe,
                ),
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

        cur.execute(
            "SELECT * FROM EKEINGANG_POS "
            "WHERE EKEINGANG_ID = %s ORDER BY POSITION, REC_ID",
            (rec_id,),
        )
        pos = cur.fetchall()
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
