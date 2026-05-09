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


# ── Pos-Operationen (Phase C.2) ─────────────────────────────────────


def _einkauf_kontext(cur, rec_id: int) -> dict[str, Any]:
    """Liest JOURNAL-Stammwerte fuer Pos-Operationen + prueft, dass der
    Beleg noch in Bearbeitung ist (QUELLE=15, STADIUM=0)."""
    cur.execute(
        """SELECT REC_ID, QUELLE, STADIUM, ADDR_ID, VRENUM,
                  BRUTTO_FLAG, MWST_FREI_FLAG,
                  MWST_0, MWST_1, MWST_2, MWST_3
             FROM JOURNAL
            WHERE REC_ID = %s""",
        (int(rec_id),),
    )
    row = cur.fetchone()
    if not row:
        raise LookupError(f'Einkauf {rec_id} nicht gefunden')
    if int(row['QUELLE']) != 15 or int(row['STADIUM']) != 0:
        raise PermissionError(
            'Einkauf ist nicht mehr in Bearbeitung — keine Pos-Aenderungen moeglich'
        )
    return row


def _summen_aktualisieren(cur, rec_id: int) -> None:
    """JOURNAL-Header-Summen aus den JOURNALPOS-Eintraegen neu berechnen.

    Behandelt BRUTTO_FLAG ('N' = GPREIS ist netto, 'Y' = GPREIS ist
    brutto) und teilt nach STEUER_CODE 0..3 auf. Berechnet WARE/LOHN/
    TKOST nach ARTIKELTYP gemaess CAO-SQL aus dem Trace.
    """
    cur.execute(
        """SELECT J.BRUTTO_FLAG, J.MWST_0, J.MWST_1, J.MWST_2, J.MWST_3,
                  COALESCE(SUM(JP.GEWICHT * JP.MENGE), 0)              AS GEWICHT,
                  COALESCE(SUM(IF(JP.STEUER_CODE=0, JP.GPREIS, 0)), 0) AS Z0,
                  COALESCE(SUM(IF(JP.STEUER_CODE=1, JP.GPREIS, 0)), 0) AS Z1,
                  COALESCE(SUM(IF(JP.STEUER_CODE=2, JP.GPREIS, 0)), 0) AS Z2,
                  COALESCE(SUM(IF(JP.STEUER_CODE=3, JP.GPREIS, 0)), 0) AS Z3,
                  COALESCE(SUM(IF(JP.ARTIKELTYP IN ('N','S','V','F','P','B') AND JP.TOP_POS_ID=-1,
                                  JP.GPREIS, 0)), 0)                  AS WARE_RAW,
                  COALESCE(SUM(IF(JP.ARTIKELTYP='L' AND JP.TOP_POS_ID=-1,
                                  JP.GPREIS, 0)), 0)                  AS LOHN_RAW,
                  COALESCE(SUM(IF(JP.ARTIKELTYP='K' AND JP.TOP_POS_ID=-1,
                                  JP.GPREIS, 0)), 0)                  AS TKOST_RAW
             FROM JOURNAL J
             LEFT JOIN JOURNALPOS JP
                ON JP.JOURNAL_ID = J.REC_ID AND JP.TOP_POS_ID = -1
            WHERE J.REC_ID = %s""",
        (int(rec_id),),
    )
    s = cur.fetchone() or {}
    bf = (s.get('BRUTTO_FLAG') == 'Y')
    saetze = [float(s.get(f'MWST_{i}') or 0) / 100.0 for i in range(4)]
    z = [float(s.get(f'Z{i}') or 0) for i in range(4)]
    n = [0.0] * 4
    m = [0.0] * 4
    b = [0.0] * 4
    for i in range(4):
        if bf:
            faktor = 1.0 + saetze[i]
            n[i] = round(z[i] / faktor, 2) if faktor > 0 else round(z[i], 2)
            b[i] = round(z[i], 2)
            m[i] = round(b[i] - n[i], 2)
        else:
            n[i] = round(z[i], 2)
            m[i] = round(z[i] * saetze[i], 2)
            b[i] = round(n[i] + m[i], 2)

    def _split_brutto_netto(brutto_raw):
        # Hilfs-Berechnung: gewichteter Netto-Anteil (analog WARE/LOHN/TKOST in CAO)
        if not brutto_raw:
            return 0.0
        if not bf:
            return round(brutto_raw, 2)
        # Bei BRUTTO_FLAG=Y: gemittelter MwSt-Satz aus den Pos-STEUER_CODES
        # ist nicht trivial — pragmatisch: Gesamt-Verhältnis Netto/Brutto
        gesamt_b = sum(b)
        gesamt_n = sum(n)
        if gesamt_b <= 0:
            return round(brutto_raw, 2)
        return round(brutto_raw * (gesamt_n / gesamt_b), 2)

    ware  = _split_brutto_netto(float(s.get('WARE_RAW')  or 0))
    lohn  = _split_brutto_netto(float(s.get('LOHN_RAW')  or 0))
    tkost = _split_brutto_netto(float(s.get('TKOST_RAW') or 0))

    cur.execute(
        """UPDATE JOURNAL SET
             WERT_NETTO=%s, WARE=%s, LOHN=%s, TKOST=%s, GEWICHT=%s,
             NSUMME=%s, NSUMME_0=%s, NSUMME_1=%s, NSUMME_2=%s, NSUMME_3=%s,
             MSUMME=%s, MSUMME_0=%s, MSUMME_1=%s, MSUMME_2=%s, MSUMME_3=%s,
             BSUMME=%s, BSUMME_0=%s, BSUMME_1=%s, BSUMME_2=%s, BSUMME_3=%s,
             GEAEND=CURDATE()
           WHERE REC_ID=%s""",
        (
            round(sum(n), 2), ware, lohn, tkost, float(s.get('GEWICHT') or 0),
            round(sum(n), 2), n[0], n[1], n[2], n[3],
            round(sum(m), 2), m[0], m[1], m[2], m[3],
            round(sum(b), 2), b[0], b[1], b[2], b[3],
            int(rec_id),
        ),
    )


def _next_pos_nr(cur, rec_id: int) -> int:
    cur.execute(
        """SELECT COALESCE(MAX(POSITION), 0) + 1 AS np
             FROM JOURNALPOS WHERE JOURNAL_ID = %s AND TOP_POS_ID = -1""",
        (int(rec_id),),
    )
    return int(cur.fetchone()['np'])


def _artikel_lesen(cur, artikel_id: int) -> dict[str, Any]:
    cur.execute(
        """SELECT a.REC_ID, a.ARTNUM, a.BARCODE, a.MATCHCODE, a.KURZNAME,
                  a.LANGNAME, a.ARTIKELTYP, a.WARENGRUPPE,
                  a.PR_EINHEIT, a.VPE, a.GEWICHT, a.STEUER_CODE,
                  a.EK_PREIS, a.AUFW_KTO,
                  COALESCE(me.BEZEICHNUNG,'') AS me_einheit,
                  COALESCE(me.ME_CODE,'') AS me_code,
                  COALESCE(wg.NAME,'') AS wgr_name
             FROM ARTIKEL a
             LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
             LEFT JOIN WARENGRUPPEN  wg ON wg.ID     = a.WARENGRUPPE
            WHERE a.REC_ID = %s""",
        (int(artikel_id),),
    )
    row = cur.fetchone()
    if not row:
        raise LookupError(f'Artikel {artikel_id} nicht gefunden')
    return row


def _lief_preis_lesen(cur, artikel_id: int, addr_id: int) -> dict[str, Any] | None:
    if addr_id <= 0:
        return None
    cur.execute(
        """SELECT PREIS, VPE, BESTNUM
             FROM ARTIKEL_PREIS
            WHERE ARTIKEL_ID = %s AND ADRESS_ID = %s AND PREIS_TYP = 5""",
        (int(artikel_id), int(addr_id)),
    )
    return cur.fetchone()


def pos_artikel_anhaengen(eingang_rec_id: int, artikel_id: int,
                          *, menge: float = 1, eingabe_preis: float | None = None,
                          ma_name: str | None = None) -> dict[str, Any]:
    """Haengt eine freie Pos (Artikel direkt) an einen Einkauf an.

    EPREIS = ``eingabe_preis`` falls gesetzt, sonst aus
    ARTIKEL_PREIS (PREIS_TYP=5, Lief), sonst aus ARTIKEL.EK_PREIS.
    GPREIS = MENGE * EPREIS.
    QUELLE_SRC=NULL, QUELLE_WE=NULL, EKEINGANG='N' (frei, kein WE/Bestell-Bezug).
    """
    eingang_rec_id = int(eingang_rec_id)
    artikel_id = int(artikel_id)
    menge = float(menge or 0)
    if menge <= 0:
        raise ValueError('Menge muss > 0 sein')
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        kontext = _einkauf_kontext(cur, eingang_rec_id)
        addr_id = int(kontext['ADDR_ID'] or -1)
        artikel = _artikel_lesen(cur, artikel_id)
        ap = _lief_preis_lesen(cur, artikel_id, addr_id)

        if eingabe_preis is not None:
            epreis = float(eingabe_preis)
        elif ap and ap.get('PREIS') is not None:
            epreis = float(ap['PREIS'])
        else:
            epreis = float(artikel.get('EK_PREIS') or 0)

        ek_preis = float(artikel.get('EK_PREIS') or 0)
        gpreis = round(menge * epreis, 2)
        pos_nr = _next_pos_nr(cur, eingang_rec_id)

        cur.execute(
            """INSERT INTO JOURNALPOS SET
                 JOURNAL_ID=%s, VRENUM=%s, QUELLE=15, QUELLE_SUB=0,
                 QUELLE_SRC=0, QUELLE_WE=0, TOP_POS_ID=-1,
                 EKEINGANG='N',
                 ADDR_ID=%s,
                 ARTIKELTYP=%s, ARTIKEL_ID=%s,
                 ARTNUM=%s, BARCODE=%s, MATCHCODE=%s,
                 BEZEICHNUNG=%s, BEZEICHNUNG_LAND='',
                 KURZBEZEICHNUNG=%s, KURZBEZEICHNUNG_LAND='',
                 FREITEXT='', FREITEXT_LAND='',
                 ME_EINHEIT=%s, ME_CODE=%s,
                 PR_EINHEIT=%s, VPE=%s,
                 MENGE=%s, MENGE_SOLL=0,
                 EPREIS=%s, EK_PREIS=%s, GPREIS=%s,
                 RABATT=0, RABATT2=0, RABATT3=0,
                 E_RABATT_BETRAG=0, G_RABATT_BETRAG=0,
                 GEWICHT=%s,
                 STEUER_CODE=%s,
                 ALTTEIL_PROZ=0, ALTTEIL_FLAG='N', ALTTEIL_STCODE=0,
                 GEGENKTO=%s,
                 BRUTTO_FLAG=%s,
                 WARENGRUPPE=%s, WARENGRUPPENNAME=%s,
                 SN_FLAG='N', SET_ID=-1, LAGER_ID=-2,
                 POSITION=%s, VIEW_POS=%s,
                 ERSTELLT=NOW(), ERST_NAME=%s""",
            (
                eingang_rec_id, kontext.get('VRENUM') or '',
                addr_id,
                (artikel.get('ARTIKELTYP') or 'N')[:1], artikel_id,
                (artikel.get('ARTNUM') or '')[:50],
                (artikel.get('BARCODE') or '')[:30],
                (artikel.get('MATCHCODE') or '')[:50],
                (artikel.get('LANGNAME') or artikel.get('KURZNAME') or '')[:200],
                (artikel.get('KURZNAME') or '')[:50],
                (artikel.get('me_einheit') or '')[:20],
                (artikel.get('me_code') or '')[:5],
                float(artikel.get('PR_EINHEIT') or 1),
                float(artikel.get('VPE') or 0),
                menge,
                epreis, ek_preis, gpreis,
                float(artikel.get('GEWICHT') or 0),
                int(artikel.get('STEUER_CODE') or 0),
                int(artikel.get('AUFW_KTO') or 0),
                kontext.get('BRUTTO_FLAG') or 'N',
                int(artikel.get('WARENGRUPPE') or 0),
                (artikel.get('wgr_name') or '')[:100],
                pos_nr, str(pos_nr),
                ma_name_safe,
            ),
        )
        new_pos_id = int(cur.lastrowid)
        _summen_aktualisieren(cur, eingang_rec_id)
    return {'pos_id': new_pos_id, 'position': pos_nr}


def pos_entfernen(eingang_rec_id: int, pos_id: int) -> dict[str, Any]:
    """Entfernt eine Pos aus einem Einkauf in Bearbeitung."""
    eingang_rec_id = int(eingang_rec_id)
    pos_id = int(pos_id)
    with get_db_transaction() as cur:
        _einkauf_kontext(cur, eingang_rec_id)
        cur.execute(
            """SELECT REC_ID FROM JOURNALPOS
                WHERE REC_ID = %s AND JOURNAL_ID = %s""",
            (pos_id, eingang_rec_id),
        )
        if not cur.fetchone():
            raise LookupError(f'Pos {pos_id} nicht gefunden')
        cur.execute(
            "DELETE FROM JOURNALPOS WHERE REC_ID = %s AND JOURNAL_ID = %s",
            (pos_id, eingang_rec_id),
        )
        _summen_aktualisieren(cur, eingang_rec_id)
    return {'ok': 1}


def pos_menge_setzen(eingang_rec_id: int, pos_id: int,
                     menge: float) -> dict[str, Any]:
    """Setzt MENGE auf einer Pos und rechnet GPREIS = MENGE × EPREIS neu."""
    eingang_rec_id = int(eingang_rec_id)
    pos_id = int(pos_id)
    menge = float(menge or 0)
    if menge < 0:
        raise ValueError('Menge muss >= 0 sein')
    with get_db_transaction() as cur:
        _einkauf_kontext(cur, eingang_rec_id)
        cur.execute(
            """SELECT EPREIS FROM JOURNALPOS
                WHERE REC_ID = %s AND JOURNAL_ID = %s""",
            (pos_id, eingang_rec_id),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Pos {pos_id} nicht gefunden')
        epreis = float(row.get('EPREIS') or 0)
        gpreis = round(menge * epreis, 2)
        cur.execute(
            """UPDATE JOURNALPOS SET MENGE=%s, GPREIS=%s
                WHERE REC_ID = %s""",
            (menge, gpreis, pos_id),
        )
        _summen_aktualisieren(cur, eingang_rec_id)
    return {'menge': menge, 'gpreis': gpreis}


def pos_epreis_setzen(eingang_rec_id: int, pos_id: int,
                      epreis: float) -> dict[str, Any]:
    """Setzt EPREIS und rechnet GPREIS = MENGE × EPREIS neu."""
    eingang_rec_id = int(eingang_rec_id)
    pos_id = int(pos_id)
    epreis = float(epreis or 0)
    if epreis < 0:
        raise ValueError('EK muss >= 0 sein')
    with get_db_transaction() as cur:
        _einkauf_kontext(cur, eingang_rec_id)
        cur.execute(
            """SELECT MENGE FROM JOURNALPOS
                WHERE REC_ID = %s AND JOURNAL_ID = %s""",
            (pos_id, eingang_rec_id),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(f'Pos {pos_id} nicht gefunden')
        menge = float(row.get('MENGE') or 0)
        gpreis = round(menge * epreis, 2)
        cur.execute(
            """UPDATE JOURNALPOS SET EPREIS=%s, GPREIS=%s
                WHERE REC_ID = %s""",
            (epreis, gpreis, pos_id),
        )
        _summen_aktualisieren(cur, eingang_rec_id)
    return {'epreis': epreis, 'gpreis': gpreis}


# ── Listen offener Vorgänge (für Hinzufügen-Picker, C.2.2) ──────────


def offene_we_des_lieferanten(eingang_rec_id: int) -> list[dict[str, Any]]:
    """Listet alle offenen Wareneingaenge des Lieferanten dieses Einkaufs.

    'Offen' im Sinne des Einkauf-Workflows = STADIUM in (2,3,4) (= gebucht
    aber noch nicht voll berechnet). STADIUM=0 (= noch nicht gebuchter WE)
    blenden wir aus, weil der noch nicht final ist. STADIUM=9 (= voll
    berechnet) und 127 (= storniert) ebenfalls.

    Pro WE wird Anzahl gebuchte-aber-noch-nicht-berechnete Pos geliefert,
    plus ob der WE bereits in einem anderen Einkauf erfasst wird (=
    Konflikt-Hinweis).
    """
    with get_db() as cur:
        cur.execute(
            """SELECT QUELLE, STADIUM, ADDR_ID FROM JOURNAL WHERE REC_ID = %s""",
            (int(eingang_rec_id),),
        )
        head = cur.fetchone()
        if not head:
            raise LookupError(f'Einkauf {eingang_rec_id} nicht gefunden')
        addr_id = int(head.get('ADDR_ID') or -1)
        if addr_id <= 0:
            return []
        cur.execute(
            """SELECT e.REC_ID         AS we_rec_id,
                      e.BELEGNUM       AS belegnum,
                      e.BELEGDATUM     AS belegdatum,
                      e.LIEFNUM        AS liefnum,
                      e.LIEFDATUM      AS liefdatum,
                      e.STADIUM        AS stadium,
                      (
                          SELECT COUNT(*) FROM EKEINGANG_POS p
                           WHERE p.EKEINGANG_ID = e.REC_ID
                             AND p.GEBUCHT_FLAG = 'Y'
                             AND p.BERECHNET = 'N'
                      ) AS pos_offen
                 FROM EKEINGANG e
                WHERE e.ADDR_ID = %s
                  AND e.STADIUM IN (2, 3, 4)
                ORDER BY e.LIEFDATUM, e.BELEGDATUM, e.REC_ID""",
            (addr_id,),
        )
        return cur.fetchall()


def offene_bestellpos_des_lieferanten(eingang_rec_id: int) -> list[dict[str, Any]]:
    """Listet noch offene Bestellpositionen des Lieferanten — Pos mit
    Restmenge > 0 (Bestellmenge minus bereits gelieferte Menge ueber
    alle gebuchten Wareneingaenge). Nur Bestellungen mit STADIUM in
    (2,3,93,95) (offen / Teil-WE / voll-WE) und Pos in den gleichen
    Codes plus Filter ARTIKELTYP IN ('N','B').
    """
    with get_db() as cur:
        cur.execute(
            """SELECT ADDR_ID, BRUTTO_FLAG FROM JOURNAL WHERE REC_ID = %s""",
            (int(eingang_rec_id),),
        )
        head = cur.fetchone()
        if not head:
            raise LookupError(f'Einkauf {eingang_rec_id} nicht gefunden')
        addr_id = int(head.get('ADDR_ID') or -1)
        if addr_id <= 0:
            return []
        cur.execute(
            """SELECT bp.REC_ID                       AS pos_id,
                      bp.EKBESTELL_ID                 AS bestell_id,
                      b.BELEGNUM                      AS bestell_nr,
                      b.BELEGDATUM                    AS bestell_datum,
                      b.LIEF_AB                       AS lief_ab,
                      bp.POSITION                     AS position,
                      bp.ARTIKEL_ID                   AS artikel_id,
                      bp.ARTNUM                       AS artnum,
                      bp.BEZEICHNUNG                  AS bezeichnung,
                      bp.MENGE                        AS bestellmenge,
                      bp.ME_EINHEIT                   AS me,
                      bp.PR_EINHEIT                   AS pe,
                      bp.VPE                          AS vpe,
                      bp.EPREIS                       AS bestell_eprice,
                      COALESCE((
                          SELECT SUM(ep.MENGE) FROM EKEINGANG_POS ep
                           JOIN EKEINGANG e ON e.REC_ID = ep.EKEINGANG_ID
                          WHERE ep.EKBESTELL_POS_ID = bp.REC_ID
                            AND ep.GEBUCHT_FLAG = 'Y'
                            AND e.STADIUM <> 127
                      ), 0)                           AS geliefert,
                      COALESCE((
                          SELECT SUM(jp.MENGE) FROM JOURNALPOS jp
                           JOIN JOURNAL j ON j.REC_ID = jp.JOURNAL_ID
                          WHERE jp.QUELLE_SRC = bp.REC_ID
                            AND jp.QUELLE = 15
                            AND j.STADIUM = 0
                      ), 0)                           AS in_offenem_einkauf
                 FROM EKBESTELL_POS bp
                 JOIN EKBESTELL b ON b.REC_ID = bp.EKBESTELL_ID
                WHERE bp.ADDR_ID = %s
                  AND bp.ARTIKELTYP IN ('N', 'B')
                  AND bp.STADIUM IN (2, 3, 93, 95)
                  AND b.STADIUM IN (2, 3, 93, 95)
                ORDER BY b.BELEGDATUM, b.BELEGNUM, bp.POSITION""",
            (addr_id,),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        soll  = float(r['bestellmenge'] or 0)
        gel   = float(r['geliefert'] or 0)
        bereits_im_einkauf = float(r['in_offenem_einkauf'] or 0)
        offen = max(0, soll - gel - bereits_im_einkauf)
        if offen <= 0.0001:
            continue
        r['menge_offen'] = offen
        out.append(r)
    return out


def pos_aus_we_anhaengen(eingang_rec_id: int, ekeingang_id: int,
                         *, ma_name: str | None = None) -> dict[str, Any]:
    """Uebernimmt alle gebuchten-aber-nicht-berechneten Pos eines
    Wareneingangs als JOURNALPOS-Eintraege in den Einkauf.

    EPREIS aus ARTIKEL_PREIS (PREIS_TYP=5, Lieferant), Fallback
    ARTIKEL.EK_PREIS, sonst 0. CAO-Mimik laut SQL-Trace.

    Doppelte Pos (gleicher EKEINGANG_POS schon im Einkauf) werden
    uebersprungen.

    Returns: ``{angehaengt, uebersprungen}``.
    """
    eingang_rec_id = int(eingang_rec_id)
    ekeingang_id = int(ekeingang_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        kontext = _einkauf_kontext(cur, eingang_rec_id)
        addr_id = int(kontext.get('ADDR_ID') or -1)

        # WE-Header pruefen + Lieferant muss zum Einkauf passen
        cur.execute(
            "SELECT ADDR_ID, STADIUM FROM EKEINGANG WHERE REC_ID = %s",
            (ekeingang_id,),
        )
        we = cur.fetchone()
        if not we:
            raise LookupError(f'Wareneingang {ekeingang_id} nicht gefunden')
        if int(we['ADDR_ID'] or -1) != addr_id:
            raise PermissionError('Lieferant des WE passt nicht zum Einkauf')
        if int(we['STADIUM']) not in (2, 3, 4):
            raise PermissionError(
                f'WE STADIUM={we["STADIUM"]} — nicht uebernehmbar (nur 2/3/4)'
            )

        # Schon im Einkauf? (welche EKEINGANG_POS sind schon drin)
        cur.execute(
            """SELECT QUELLE_WE FROM JOURNALPOS
                WHERE JOURNAL_ID = %s AND EKEINGANG = 'Y'""",
            (eingang_rec_id,),
        )
        schon_drin = {int(r['QUELLE_WE']) for r in cur.fetchall()
                      if r.get('QUELLE_WE')}

        # WE-Pos lesen (analog CAO-Trace: GEBUCHT_FLAG='Y' AND BERECHNET='N')
        cur.execute(
            """SELECT REC_ID         AS we_pos_id,
                      EKBESTELL_POS_ID, ADDR_ID, ARTIKELTYP, ARTIKEL_ID,
                      BARCODE, ARTNUM, MATCHCODE,
                      BEZEICHNUNG, BEZEICHNUNG_LAND,
                      KURZBEZEICHNUNG, KURZBEZEICHNUNG_LAND,
                      FREITEXT, FREITEXT_LAND,
                      ME_EINHEIT, ME_CODE, PR_EINHEIT, VPE,
                      MENGE, SN_FLAG, SET_ID, WARENGRUPPE
                 FROM EKEINGANG_POS
                WHERE EKEINGANG_ID = %s
                  AND GEBUCHT_FLAG = 'Y'
                  AND BERECHNET   = 'N'
                ORDER BY POSITION, REC_ID""",
            (ekeingang_id,),
        )
        we_pos = cur.fetchall()
        if not we_pos:
            return {'angehaengt': 0, 'uebersprungen': 0}

        pos_nr = _next_pos_nr(cur, eingang_rec_id)
        ang = 0
        skip = 0
        for wp in we_pos:
            we_pos_id = int(wp['we_pos_id'])
            if we_pos_id in schon_drin:
                skip += 1
                continue
            artikel_id = int(wp.get('ARTIKEL_ID') or 0)
            if artikel_id <= 0:
                # Pos ohne Artikel-Bezug überspringen (Pfand/Freitext)
                skip += 1
                continue
            artikel = _artikel_lesen(cur, artikel_id)
            ap = _lief_preis_lesen(cur, artikel_id, addr_id)
            if ap and ap.get('PREIS') is not None:
                epreis = float(ap['PREIS'])
            else:
                epreis = float(artikel.get('EK_PREIS') or 0)
            ek_preis = float(artikel.get('EK_PREIS') or 0)
            menge = float(wp.get('MENGE') or 0)
            gpreis = round(menge * epreis, 2)

            cur.execute(
                """INSERT INTO JOURNALPOS SET
                     JOURNAL_ID=%s, VRENUM=%s, QUELLE=15, QUELLE_SUB=0,
                     QUELLE_SRC=%s, QUELLE_WE=%s, TOP_POS_ID=-1,
                     EKEINGANG='Y',
                     ADDR_ID=%s,
                     ARTIKELTYP=%s, ARTIKEL_ID=%s,
                     ARTNUM=%s, BARCODE=%s, MATCHCODE=%s,
                     BEZEICHNUNG=%s, BEZEICHNUNG_LAND=%s,
                     KURZBEZEICHNUNG=%s, KURZBEZEICHNUNG_LAND=%s,
                     FREITEXT=%s, FREITEXT_LAND=%s,
                     ME_EINHEIT=%s, ME_CODE=%s,
                     PR_EINHEIT=%s, VPE=%s,
                     MENGE=%s, MENGE_SOLL=0,
                     EPREIS=%s, EK_PREIS=%s, GPREIS=%s,
                     RABATT=0, RABATT2=0, RABATT3=0,
                     E_RABATT_BETRAG=0, G_RABATT_BETRAG=0,
                     GEWICHT=%s,
                     STEUER_CODE=%s,
                     ALTTEIL_PROZ=0, ALTTEIL_FLAG='N', ALTTEIL_STCODE=0,
                     GEGENKTO=%s,
                     BRUTTO_FLAG=%s,
                     WARENGRUPPE=%s, WARENGRUPPENNAME=%s,
                     SN_FLAG=%s, SET_ID=%s, LAGER_ID=-2,
                     POSITION=%s, VIEW_POS=%s,
                     ERSTELLT=NOW(), ERST_NAME=%s""",
                (
                    eingang_rec_id, kontext.get('VRENUM') or '',
                    int(wp.get('EKBESTELL_POS_ID') or 0),
                    we_pos_id,
                    addr_id,
                    (wp.get('ARTIKELTYP') or 'N')[:1],
                    artikel_id,
                    (wp.get('ARTNUM') or '')[:50],
                    (wp.get('BARCODE') or '')[:30],
                    (wp.get('MATCHCODE') or '')[:50],
                    (wp.get('BEZEICHNUNG') or '')[:200],
                    (wp.get('BEZEICHNUNG_LAND') or '')[:200],
                    (wp.get('KURZBEZEICHNUNG') or '')[:50],
                    (wp.get('KURZBEZEICHNUNG_LAND') or '')[:50],
                    (wp.get('FREITEXT') or ''),
                    (wp.get('FREITEXT_LAND') or ''),
                    (wp.get('ME_EINHEIT') or '')[:20],
                    (wp.get('ME_CODE') or '')[:5],
                    float(wp.get('PR_EINHEIT') or 1),
                    float(wp.get('VPE') or 0),
                    menge,
                    epreis, ek_preis, gpreis,
                    float(artikel.get('GEWICHT') or 0),
                    int(artikel.get('STEUER_CODE') or 0),
                    int(artikel.get('AUFW_KTO') or 0),
                    kontext.get('BRUTTO_FLAG') or 'N',
                    int(wp.get('WARENGRUPPE') or artikel.get('WARENGRUPPE') or 0),
                    (artikel.get('wgr_name') or '')[:100],
                    (wp.get('SN_FLAG') or 'N')[:1],
                    int(wp.get('SET_ID') or -1),
                    pos_nr, str(pos_nr),
                    ma_name_safe,
                ),
            )
            pos_nr += 1
            ang += 1
        if ang > 0:
            _summen_aktualisieren(cur, eingang_rec_id)
    return {'angehaengt': ang, 'uebersprungen': skip}


def pos_aus_bestellpos_anhaengen(eingang_rec_id: int, bestellpos_id: int,
                                  *, menge: float | None = None,
                                  ma_name: str | None = None) -> dict[str, Any]:
    """Uebernimmt eine offene Bestellpos direkt in den Einkauf (ohne WE).
    EKEINGANG='N', QUELLE_SRC = bestellpos.REC_ID.

    Wenn ``menge`` None ist, wird die noch offene Restmenge der Bestellpos
    (= Bestellmenge minus geliefert minus bereits-in-anderem-Einkauf)
    vorbelegt.
    """
    eingang_rec_id = int(eingang_rec_id)
    bestellpos_id = int(bestellpos_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        kontext = _einkauf_kontext(cur, eingang_rec_id)
        addr_id = int(kontext.get('ADDR_ID') or -1)

        cur.execute(
            """SELECT bp.*, b.STADIUM AS bestell_stadium, b.ADDR_ID AS bestell_addr
                 FROM EKBESTELL_POS bp
                 JOIN EKBESTELL b ON b.REC_ID = bp.EKBESTELL_ID
                WHERE bp.REC_ID = %s""",
            (bestellpos_id,),
        )
        bp = cur.fetchone()
        if not bp:
            raise LookupError(f'Bestellpos {bestellpos_id} nicht gefunden')
        if int(bp.get('bestell_addr') or -1) != addr_id:
            raise PermissionError('Lieferant der Bestellung passt nicht zum Einkauf')
        if int(bp.get('STADIUM') or 0) not in (2, 3, 93, 95):
            raise PermissionError(
                f'Bestellpos STADIUM={bp["STADIUM"]} — nicht mehr offen'
            )

        artikel_id = int(bp.get('ARTIKEL_ID') or 0)
        if artikel_id <= 0:
            raise PermissionError('Bestellpos ohne Artikel-Bezug nicht uebernehmbar')

        artikel = _artikel_lesen(cur, artikel_id)
        ap = _lief_preis_lesen(cur, artikel_id, addr_id)

        if menge is None:
            soll = float(bp.get('MENGE') or 0)
            cur.execute(
                """SELECT COALESCE(SUM(MENGE),0) AS s FROM EKEINGANG_POS
                    WHERE EKBESTELL_POS_ID = %s AND GEBUCHT_FLAG = 'Y'""",
                (bestellpos_id,),
            )
            gel = float(cur.fetchone()['s'] or 0)
            cur.execute(
                """SELECT COALESCE(SUM(jp.MENGE),0) AS s
                     FROM JOURNALPOS jp
                     JOIN JOURNAL j ON j.REC_ID = jp.JOURNAL_ID
                    WHERE jp.QUELLE_SRC = %s AND jp.QUELLE = 15
                      AND j.STADIUM = 0""",
                (bestellpos_id,),
            )
            in_einkauf = float(cur.fetchone()['s'] or 0)
            menge = max(0.0, soll - gel - in_einkauf)
        menge = float(menge)
        if menge <= 0:
            raise ValueError('Keine offene Restmenge')

        if ap and ap.get('PREIS') is not None:
            epreis = float(ap['PREIS'])
        elif bp.get('EPREIS'):
            epreis = float(bp['EPREIS'])
        else:
            epreis = float(artikel.get('EK_PREIS') or 0)
        ek_preis = float(artikel.get('EK_PREIS') or 0)
        gpreis = round(menge * epreis, 2)
        pos_nr = _next_pos_nr(cur, eingang_rec_id)

        cur.execute(
            """INSERT INTO JOURNALPOS SET
                 JOURNAL_ID=%s, VRENUM=%s, QUELLE=15, QUELLE_SUB=0,
                 QUELLE_SRC=%s, QUELLE_WE=0, TOP_POS_ID=-1,
                 EKEINGANG='N',
                 ADDR_ID=%s,
                 ARTIKELTYP=%s, ARTIKEL_ID=%s,
                 ARTNUM=%s, BARCODE=%s, MATCHCODE=%s,
                 BEZEICHNUNG=%s, BEZEICHNUNG_LAND='',
                 KURZBEZEICHNUNG=%s, KURZBEZEICHNUNG_LAND='',
                 FREITEXT='', FREITEXT_LAND='',
                 ME_EINHEIT=%s, ME_CODE=%s,
                 PR_EINHEIT=%s, VPE=%s,
                 MENGE=%s, MENGE_SOLL=0,
                 EPREIS=%s, EK_PREIS=%s, GPREIS=%s,
                 RABATT=0, RABATT2=0, RABATT3=0,
                 E_RABATT_BETRAG=0, G_RABATT_BETRAG=0,
                 GEWICHT=%s,
                 STEUER_CODE=%s,
                 ALTTEIL_PROZ=0, ALTTEIL_FLAG='N', ALTTEIL_STCODE=0,
                 GEGENKTO=%s,
                 BRUTTO_FLAG=%s,
                 WARENGRUPPE=%s, WARENGRUPPENNAME=%s,
                 SN_FLAG='N', SET_ID=-1, LAGER_ID=-2,
                 POSITION=%s, VIEW_POS=%s,
                 ERSTELLT=NOW(), ERST_NAME=%s""",
            (
                eingang_rec_id, kontext.get('VRENUM') or '',
                bestellpos_id,
                addr_id,
                (bp.get('ARTIKELTYP') or 'N')[:1],
                artikel_id,
                (bp.get('ARTNUM') or '')[:50],
                (bp.get('BARCODE') or artikel.get('BARCODE') or '')[:30],
                (bp.get('MATCHCODE') or artikel.get('MATCHCODE') or '')[:50],
                (bp.get('BEZEICHNUNG') or '')[:200],
                (bp.get('KURZBEZEICHNUNG') or '')[:50],
                (bp.get('ME_EINHEIT') or artikel.get('me_einheit') or '')[:20],
                (bp.get('ME_CODE') or artikel.get('me_code') or '')[:5],
                float(bp.get('PR_EINHEIT') or artikel.get('PR_EINHEIT') or 1),
                float(bp.get('VPE') or artikel.get('VPE') or 0),
                menge,
                epreis, ek_preis, gpreis,
                float(artikel.get('GEWICHT') or 0),
                int(bp.get('STEUER_CODE') or artikel.get('STEUER_CODE') or 0),
                int(artikel.get('AUFW_KTO') or 0),
                kontext.get('BRUTTO_FLAG') or 'N',
                int(bp.get('WARENGRUPPE') or artikel.get('WARENGRUPPE') or 0),
                (artikel.get('wgr_name') or '')[:100],
                pos_nr, str(pos_nr),
                ma_name_safe,
            ),
        )
        new_pos_id = int(cur.lastrowid)
        _summen_aktualisieren(cur, eingang_rec_id)
    return {'pos_id': new_pos_id, 'position': pos_nr,
            'menge': menge, 'epreis': epreis}
