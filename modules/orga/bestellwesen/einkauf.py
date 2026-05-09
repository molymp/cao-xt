"""
Orga / Bestellwesen / Einkauf (= EK-Rechnung) — Phase C

CAO-Mimik: offene Einkaufsvorgänge leben direkt in JOURNAL/JOURNALPOS,
nicht in einer separaten XT-Tabelle:

  In Bearbeitung   QUELLE=15  STADIUM=0  VRENUM='EDI-NNNNNN' HASHSUM='$$'
  Verbucht         QUELLE=5   STADIUM=2  VRENUM='NNNNNN'     HASHSUM=…
  Voll bezahlt     QUELLE=5   STADIUM=9  (entsteht durch Zahlungs-Buchung)

Ein Einkauf kann durch Übernahme aus Wareneingängen (m:n) und/oder
direkt aus Bestellungen entstehen, plus freie Positionen (Pfand, Lief-
kosten). Die Verknüpfung läuft über JOURNALPOS.QUELLE_WE (= WE-Pos)
und JOURNALPOS.QUELLE_SRC (= Bestellpos).

Die volle SQL-Mimik ist im Backlog dokumentiert
(memory/project_einkauf_buchen_phasec.md), incl. Buchen-Trace.

Phase C.1 (dieses Modul, erster Wurf):
- ``einkauf_liste`` Übersicht aller in-Bearbeitung + verbuchter Einkäufe
- ``einkauf_detail`` Header + Pos für die Detail-Seite
- ``einkauf_anlegen`` legt einen leeren Einkaufs-Beleg an
  (INSERT JOURNAL mit QUELLE=15, STADIUM=0)
- ``einkauf_storno`` löscht oder markiert den Beleg

Phase C.2/3/4 folgen separat: Lieferant setzen, Pos hinzufügen/entfernen,
Buchen mit Preisabweichung-Modal.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from common.db import get_db, get_db_transaction


# ── STADIUM-Codes für JOURNAL.QUELLE in (5, 15) ─────────────────────
#
# Quelle: Reverse-engineered aus cao_faktura.exe UTF-16-LE-ENUM-Strings
# (siehe reference_cao_journal_codes.md). CAO-Faktura unterscheidet
# JOURNAL.STADIUM zwischen Verkaufs- (QUELLE=3) und Einkaufs-
# Rechnungen (QUELLE=5) nur bei Code 11.
#
# Live-DB-Verteilung passt zur Decodierung:
#   2: 32   ✓ 'offen' (unbezahlt)
#   7: 2    ✓ Teilzahlung
#   8: 783  ✓ bezahlt mit Skonto
#   9: 6764 ✓ bezahlt
#   11: 8   ✓ Angewiesen (Überweisung läuft)
#   125: 95 ✓ Storniert (Pos-Marker)
#   126: 95 ✓ Stornorechnung
STADIUM_LABEL = {
    0:   'in Bearbeitung',
    2:   'offen',
    3:   '1× gemahnt',
    4:   '2× gemahnt',
    5:   '3× gemahnt',
    6:   'INKASSO',
    7:   'Teilzahlung',
    8:   'bezahlt mit Skonto',
    9:   'bezahlt',
    11:  'Angewiesen',
    125: 'Storniert',
    126: 'Stornorechnung',
    127: '*** STORNO ***',
}


def _stadium_label(code: int | None) -> str:
    if code is None:
        return '–'
    return STADIUM_LABEL.get(int(code), f'?? - [{code}]')


def _next_edi_belegnum(cur) -> str:
    """EDI-Format-Belegnummer für offene Einkäufe (QUELLE=15).

    CAO nutzt das Format ``EDI-NNNNNN`` (6-stellig padded). Da CAO den
    Counter wohl nicht in REGISTRY verwaltet (zumindest haben wir keinen
    Eintrag dafür gefunden), nutzen wir ``MAX(VRENUM)+1`` mit einem
    SELECT-FOR-UPDATE-Lock: in einer Transaktion holen wir den
    aktuellen Maximum-Wert, parsen das Suffix, inkrementieren und
    schreiben den neuen Wert. Race-frei nur in einer Transaktion.

    Wir suchen bewusst nur nach VRENUMs, die mit 'EDI-' beginnen — der
    Counter für 'EK-RECH' (= verbuchte Rechnungen) läuft separat.
    """
    cur.execute(
        """SELECT VRENUM FROM JOURNAL
            WHERE QUELLE = 15 AND VRENUM LIKE 'EDI-%'
            ORDER BY CAST(SUBSTRING(VRENUM, 5) AS UNSIGNED) DESC
            LIMIT 1
            FOR UPDATE"""
    )
    row = cur.fetchone()
    if row and row.get('VRENUM'):
        try:
            n = int(row['VRENUM'].split('-', 1)[1])
        except (ValueError, IndexError):
            n = 0
    else:
        n = 0
    return f'EDI-{n + 1:06d}'


def einkauf_liste(*, suche: str = '', stadium: int | None = None,
                  limit: int = 200) -> list[dict[str, Any]]:
    """Liste aller Einkäufe (QUELLE in (5, 15) — also in-Bearbeitung
    und verbuchte EK-Rechnungen)."""
    where = ['j.QUELLE IN (5, 15)']
    params: list[Any] = []
    if suche:
        where.append('(j.VRENUM LIKE %s OR a.NAME1 LIKE %s)')
        params.extend([f'%{suche}%', f'%{suche}%'])
    if stadium is not None:
        where.append('j.STADIUM = %s')
        params.append(int(stadium))
    params.append(int(limit))

    sql = f"""
        SELECT
            j.REC_ID                            AS rec_id,
            j.QUELLE                            AS quelle,
            j.VRENUM                            AS vrenum,
            j.RDATUM                            AS rdatum,
            j.STADIUM                           AS stadium,
            j.ADDR_ID                           AS addr_id,
            COALESCE(a.NAME1, j.KUN_NAME1, '–') AS lief_name,
            j.NSUMME                            AS nsumme,
            j.MSUMME                            AS msumme,
            j.BSUMME                            AS bsumme,
            (
                SELECT COUNT(*) FROM JOURNALPOS p
                 WHERE p.JOURNAL_ID = j.REC_ID AND p.TOP_POS_ID = -1
            )                                   AS pos_anzahl
        FROM JOURNAL j
        LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
        WHERE {' AND '.join(where)}
        ORDER BY j.RDATUM DESC, j.REC_ID DESC
        LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for r in rows:
        r['stadium_label'] = _stadium_label(r.get('stadium'))
        r['ist_offen'] = (int(r.get('stadium') or 0) == 0)
    return rows


def einkauf_detail(rec_id: int) -> dict[str, Any] | None:
    """Detail-Daten: JOURNAL-Header + JOURNALPOS-Liste."""
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            """SELECT j.*,
                      COALESCE(a.NAME1, j.KUN_NAME1, '–') AS lief_name,
                      COALESCE(a.STRASSE, j.KUN_STRASSE, '') AS lief_strasse,
                      COALESCE(a.HAUSNR, j.KUN_HAUSNR, '') AS lief_hausnr,
                      COALESCE(a.LAND, j.KUN_LAND, '') AS lief_land,
                      COALESCE(a.PLZ, j.KUN_PLZ, '') AS lief_plz,
                      COALESCE(a.ORT, j.KUN_ORT, '') AS lief_ort
                 FROM JOURNAL j
                 LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
                WHERE j.REC_ID = %s
                  AND j.QUELLE IN (5, 15)""",
            (rec_id,),
        )
        kopf = cur.fetchone()
        if not kopf:
            return None
        kopf['stadium_label'] = _stadium_label(kopf.get('STADIUM'))
        kopf['ist_offen'] = (int(kopf.get('STADIUM') or 0) == 0)

        cur.execute(
            """SELECT p.*
                 FROM JOURNALPOS p
                WHERE p.JOURNAL_ID = %s AND p.TOP_POS_ID = -1
                ORDER BY p.POSITION, p.REC_ID""",
            (rec_id,),
        )
        positionen = cur.fetchall()
    return {'kopf': kopf, 'positionen': positionen}


def einkauf_anlegen(ma_id: int | None,
                    ma_name: str | None,
                    addr_id: int | None = None) -> dict[str, Any]:
    """Legt einen Einkaufs-Beleg an (JOURNAL.QUELLE=15, STADIUM=0,
    EDI-NNNNNN-Belegnummer).

    Wenn ``addr_id`` gesetzt ist, wird der Lieferant inkl. KUN_*-Adress-
    block und ggf. Zahlart aus den Stammdaten gleich beim INSERT
    geschrieben — sonst leerer Header (Lieferant kann spaeter via
    ``einkauf_lieferant_setzen`` zugewiesen werden).

    Returns: ``{rec_id, vrenum}``.
    """
    ma_name_safe = (ma_name or 'CAO-XT')[:100]
    heute = date.today()
    with get_db_transaction() as cur:
        # FIRMA_ID aus FIRMA-Tabelle (CAO-Standard: jüngste REC_ID)
        cur.execute("SELECT REC_ID FROM FIRMA ORDER BY REC_ID DESC LIMIT 1")
        fr = cur.fetchone()
        firma_id = int(fr['REC_ID']) if fr else 1

        # Lieferanten-Stammdaten holen (falls addr_id uebergeben)
        adr: dict[str, Any] = {}
        if addr_id and int(addr_id) > 0:
            cur.execute(
                """SELECT REC_ID, ANREDE, NAME1, NAME2, NAME3, KUNNUM1,
                          STRASSE, HAUSNR, LAND, PLZ, ORT, ADRESSZUSATZ,
                          UST_NUM, ABTEILUNG, LIEF_ZAHLART
                     FROM ADRESSEN WHERE REC_ID = %s""",
                (int(addr_id),),
            )
            adr = cur.fetchone() or {}
            if not adr:
                raise LookupError(f'Adresse {addr_id} nicht gefunden')
        addr_int = int(adr.get('REC_ID') or -1)

        # ZAHLART: bevorzugt Lief-Stammwert, sonst -1
        zahlart = adr.get('LIEF_ZAHLART')
        try:
            zahlart_id = int(zahlart) if zahlart is not None and int(zahlart) > 0 else -1
        except (TypeError, ValueError):
            zahlart_id = -1

        belegnum = _next_edi_belegnum(cur)
        cur.execute(
            """INSERT INTO JOURNAL
                 (QUELLE, QUELLE_SUB, ADDR_ID, ASP_ID, PROJEKT_ID, SPRACH_ID,
                  ATRNUM, VRENUM, VLSNUM, FOLGENR, KM_STAND, KFZ_ID,
                  VERTRETER_ID, GLOBRABATT,
                  ADATUM, RDATUM, LDATUM, TERMIN,
                  PR_EBENE, LIEFART, ZAHLART,
                  KOST_NETTO, WERT_NETTO, LOHN, WARE, TKOST,
                  MWST_0, MWST_1, MWST_2, MWST_3, AT_MWST,
                  NSUMME_0, NSUMME_1, NSUMME_2, NSUMME_3, NSUMME,
                  MSUMME_0, MSUMME_1, MSUMME_2, MSUMME_3, MSUMME,
                  BSUMME_0, BSUMME_1, BSUMME_2, BSUMME_3, BSUMME,
                  ATSUMME, ATMSUMME,
                  WAEHRUNG, GEGENKONTO,
                  SOLL_NTAGE, SOLL_SKONTO, SOLL_STAGE, SOLL_RATEN,
                  SOLL_RATBETR, SOLL_RATINTERVALL,
                  STADIUM, ERSTELLT, ERST_NAME, GEAEND, GEAEND_NAME,
                  KUN_NUM, KUN_ANREDE, KUN_NAME1, KUN_NAME2, KUN_NAME3,
                  KUN_ABTEILUNG, KUN_STRASSE, KUN_LAND, KUN_PLZ, KUN_ORT,
                  USR1, USR2, PROJEKT, ORGNUM, BEST_NAME,
                  BRUTTO_FLAG, MWST_FREI_FLAG, HASHSUM,
                  FIRMA_ID, Z_ID,
                  ZAHLART_NAME, ZAHLART_KURZ,
                  LIEFART_NAME,
                  KUN_UST_NUM, KUN_HAUSNR, KUN_ADRESSZUSATZ,
                  ER_DATUM, DEL_FLAG, MA_ID)
               VALUES
                 (15, 0, %s, -1, -1, 2,
                  '', %s, '', -1, -1, -1,
                  -1, 0,
                  '1899-12-30', %s, '1899-12-30', '1899-12-30',
                  0, -1, %s,
                  0, 0, 0, 0, 0,
                  0, 19, 7, 7.8, 10,
                  0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0,
                  0, 0,
                  '€', -1,
                  0, 0, 0, 1,
                  0, 0,
                  0, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  '', '', '', '', '',
                  'N', 'N', '$$',
                  %s, -1,
                  '', '',
                  '',
                  %s, %s, %s,
                  NOW(), 'N', %s)""",
            (
                addr_int,
                belegnum,
                datetime.now(),
                zahlart_id,
                heute, ma_name_safe, heute, ma_name_safe,
                (adr.get('KUNNUM1') or '')[:50],
                (adr.get('ANREDE') or '')[:50],
                (adr.get('NAME1') or '')[:100],
                (adr.get('NAME2') or '')[:100],
                (adr.get('NAME3') or '')[:100],
                (adr.get('ABTEILUNG') or '')[:100],
                (adr.get('STRASSE') or '')[:100],
                (adr.get('LAND') or '')[:5],
                (adr.get('PLZ') or '')[:10],
                (adr.get('ORT') or '')[:100],
                firma_id,
                (adr.get('UST_NUM') or '')[:30],
                (adr.get('HAUSNR') or '')[:20],
                (adr.get('ADRESSZUSATZ') or '')[:100],
                int(ma_id) if ma_id is not None else -1,
            ),
        )
        rec_id = cur.lastrowid
    return {'rec_id': int(rec_id), 'vrenum': belegnum}


def einkauf_storno(rec_id: int) -> dict[str, int]:
    """Storno: nur möglich solange QUELLE=15 (in Bearbeitung). Nach dem
    Buchen (QUELLE=5) muss in CAO-Faktura storniert werden.

    Wir machen einen harten DELETE — der Beleg ist noch nicht in CAOs
    Buchhaltungs-Pipeline. JOURNALPOS-Einträge werden mit-gelöscht.
    """
    rec_id = int(rec_id)
    with get_db_transaction() as cur:
        cur.execute(
            "SELECT QUELLE, STADIUM FROM JOURNAL WHERE REC_ID = %s",
            (rec_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Einkauf {rec_id} nicht gefunden')
        if int(row['QUELLE']) != 15 or int(row['STADIUM']) != 0:
            raise PermissionError(
                f"Einkauf STADIUM={row['STADIUM']} QUELLE={row['QUELLE']} — "
                f"nur in Bearbeitung (QUELLE=15, STADIUM=0) loeschbar; "
                f"verbuchte Belege bitte in CAO-Faktura stornieren"
            )
        cur.execute("DELETE FROM JOURNALPOS WHERE JOURNAL_ID = %s", (rec_id,))
        cur.execute("DELETE FROM JOURNAL WHERE REC_ID = %s", (rec_id,))
    return {'ok': 1}
