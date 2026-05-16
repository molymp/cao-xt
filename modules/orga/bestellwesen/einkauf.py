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

import logging
from datetime import date, datetime
from typing import Any

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)


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


def _ueberweisung_zustand(quelle: int, stadium: int, zahlart_id: int,
                           iban: str, hat_vormerkung: bool,
                           soll_zahlart: int) -> str | None:
    """UI-Zustand des Überweisungs-Knopfs pro EK-Beleg.

    Returns einen von ``None`` (nichts anzeigen), ``'vorbereiten'``,
    ``'iban_fehlt'``, ``'zuruecknehmen'``. Harter Gate: nur Zahlart
    „Überweisung Bank" (sonst None — verhindert Lastschrift-Doppel-
    zahlung).
    """
    if int(quelle or 0) != 5:
        return None
    if int(zahlart_id or -1) != int(soll_zahlart):
        return None
    st = int(stadium or 0)
    if st == 11 or hat_vormerkung:
        return 'zuruecknehmen'
    if st in (2, 7):
        return 'vorbereiten' if (iban or '').strip() else 'iban_fehlt'
    return None


def banking_konfiguriert() -> bool:
    """True, wenn ein Hibiscus-Belastungskonto hinterlegt ist
    (Voraussetzung für die Überweisungs-Buttons)."""
    from common import konfig
    try:
        v = konfig.get('hibiscus.debit_konto_id')
        return bool(v) and int(v) > 0
    except (TypeError, ValueError):
        return False


# Sortierbare Spalten (UI-Key → erlaubter SQL-Ausdruck). Nur hier
# Gelistetes kann in ORDER BY — Schutz gegen SQL-Injection.
EINKAUF_SORT = {
    'belegnr':   'j.VRENUM',
    'eingangsnr': 'j.ORGNUM',
    'datum':     'j.RDATUM',
    'lieferant': "COALESCE(a.NAME1, j.KUN_NAME1, '')",
    'netto':     'j.NSUMME',
    'brutto':    'j.BSUMME',
    'zahlart':   'j.ZAHLART_NAME',
    'stadium':   'j.STADIUM',
}
EINKAUF_DEFAULT_ORDER = 'j.RDATUM DESC, j.REC_ID DESC'


def einkauf_liste(*, suche: str = '', stadium: int | None = None,
                  zahlart_id: int | None = None,
                  storno_aus: bool = True,
                  bezahlt: str = 'alle',
                  von_datum: date | None = None,
                  bis_datum: date | None = None,
                  sort_sql: str = EINKAUF_DEFAULT_ORDER,
                  limit: int = 2000) -> dict[str, Any]:
    """Einkäufe (QUELLE 5/15) eines Zeitraums (RDATUM von/bis),
    serverseitig gefiltert + sortiert. Returns
    ``{'rows': [...], 'total': int, 'gekuerzt': bool}``.

    - ``storno_aus`` (Default True): STADIUM 125/126/127 ausblenden.
    - ``bezahlt``: ``'alle'`` | ``'bezahlt'`` (STADIUM 8/9) |
      ``'unbezahlt'`` (alles andere = noch offener Betrag).
    - ``limit``: Sicherheits-Cap; ``gekuerzt`` = total > limit.
    """
    _hibiscus_vormerkung_schema()
    soll_zahlart = _ek_zahlart_ueberweisung_id()
    where = ['j.QUELLE IN (5, 15)']
    params: list[Any] = []
    if suche:
        where.append('(j.VRENUM LIKE %s OR a.NAME1 LIKE %s)')
        params.extend([f'%{suche}%', f'%{suche}%'])
    if stadium is not None:
        where.append('j.STADIUM = %s')
        params.append(int(stadium))
    if zahlart_id is not None:
        where.append('j.ZAHLART = %s')
        params.append(int(zahlart_id))
    if storno_aus:
        where.append('j.STADIUM NOT IN (125, 126, 127)')
    if bezahlt == 'bezahlt':
        where.append('j.STADIUM IN (8, 9)')
    elif bezahlt == 'unbezahlt':
        where.append('j.STADIUM NOT IN (8, 9)')
    if von_datum is not None:
        where.append('j.RDATUM >= %s')
        params.append(von_datum)
    if bis_datum is not None:
        where.append('j.RDATUM <= %s')
        params.append(bis_datum)
    where_sql = ' AND '.join(where)

    with get_db() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM JOURNAL j "
            f"LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID "
            f"WHERE {where_sql}",
            params,
        )
        total = int((cur.fetchone() or {}).get('n') or 0)

        cur.execute(
            f"""
            SELECT
                j.REC_ID                            AS rec_id,
                j.QUELLE                            AS quelle,
                j.VRENUM                            AS vrenum,
                j.ORGNUM                            AS orgnum,
                j.RDATUM                            AS rdatum,
                j.STADIUM                           AS stadium,
                j.ADDR_ID                           AS addr_id,
                COALESCE(a.NAME1, j.KUN_NAME1, '–') AS lief_name,
                j.NSUMME                            AS nsumme,
                j.MSUMME                            AS msumme,
                j.BSUMME                            AS bsumme,
                j.ZAHLART_NAME                      AS zahlart_name,
                j.ZAHLART                           AS zahlart_id,
                COALESCE(a.IBAN, '')                AS lief_iban,
                (
                    SELECT COUNT(*) FROM JOURNALPOS p
                     WHERE p.JOURNAL_ID = j.REC_ID AND p.TOP_POS_ID = -1
                )                                   AS pos_anzahl,
                (
                    SELECT COUNT(*) FROM XT_HIBISCUS_VORMERKUNG v
                     WHERE v.MODUL = 'einkauf' AND v.REFERENZ_ID = j.REC_ID
                       AND v.STATUS = 'vorgemerkt'
                )                                   AS hat_vormerkung
            FROM JOURNAL j
            LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
            WHERE {where_sql}
            ORDER BY {sort_sql}
            LIMIT %s
            """,
            params + [int(limit)],
        )
        rows = cur.fetchall()
    for r in rows:
        r['stadium_label'] = _stadium_label(r.get('stadium'))
        r['ist_offen'] = (int(r.get('stadium') or 0) == 0)
        r['ueberweisung_zustand'] = _ueberweisung_zustand(
            r.get('quelle'), r.get('stadium'), r.get('zahlart_id'),
            r.get('lief_iban'), bool(r.get('hat_vormerkung')),
            soll_zahlart)
    return {'rows': rows, 'total': total, 'gekuerzt': total > int(limit)}


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
                      COALESCE(a.ORT, j.KUN_ORT, '') AS lief_ort,
                      COALESCE(a.IBAN, '')  AS lief_iban,
                      COALESCE(a.SWIFT, '') AS lief_bic
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

        # Überweisungs-Zustand (gleiche Logik wie in der Übersicht).
        _hibiscus_vormerkung_schema()
        cur.execute(
            "SELECT COUNT(*) AS n FROM XT_HIBISCUS_VORMERKUNG "
            " WHERE MODUL='einkauf' AND REFERENZ_ID=%s "
            "   AND STATUS='vorgemerkt'",
            (rec_id,)
        )
        hat_vm = int((cur.fetchone() or {}).get('n') or 0) > 0
    kopf['ueberweisung_zustand'] = _ueberweisung_zustand(
        kopf.get('QUELLE'), kopf.get('STADIUM'), kopf.get('ZAHLART'),
        kopf.get('lief_iban'), hat_vm, _ek_zahlart_ueberweisung_id())
    kopf['banking_konfiguriert'] = banking_konfiguriert()
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


def pos_aus_we_anhaengen_bulk(eingang_rec_id: int, ekeingang_ids: list[int],
                               *, ma_name: str | None = None) -> dict[str, Any]:
    """Mehrere Wareneingaenge auf einmal uebernehmen — schleift einfach
    durch die IDs. Antwortet mit Summen-Counter."""
    ang_total = 0
    skip_total = 0
    for we_id in ekeingang_ids:
        try:
            r = pos_aus_we_anhaengen(eingang_rec_id, int(we_id), ma_name=ma_name)
            ang_total += int(r.get('angehaengt', 0))
            skip_total += int(r.get('uebersprungen', 0))
        except (LookupError, PermissionError, ValueError):
            skip_total += 1
    return {'angehaengt': ang_total, 'uebersprungen': skip_total}


def pos_aus_bestellpos_anhaengen_bulk(eingang_rec_id: int,
                                       items: list[dict],
                                       *, ma_name: str | None = None) -> dict[str, Any]:
    """Mehrere Bestellpositionen auf einmal uebernehmen.

    items: list of ``{pos_id, menge?}``-Dicts. Wenn menge fehlt, wird
    die noch offene Restmenge uebernommen.
    """
    ang = 0
    fehler: list[str] = []
    for it in items:
        try:
            pid = int(it.get('pos_id') or 0)
            if pid <= 0:
                continue
            mraw = it.get('menge')
            if mraw is not None:
                try:
                    m = float(str(mraw).replace(',', '.'))
                except (TypeError, ValueError):
                    m = None
            else:
                m = None
            pos_aus_bestellpos_anhaengen(eingang_rec_id, pid,
                                          menge=m, ma_name=ma_name)
            ang += 1
        except (LookupError, PermissionError, ValueError) as e:
            fehler.append(f'Pos {it.get("pos_id")}: {e}')
    return {'angehaengt': ang, 'fehler': fehler}


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


# ── Phase C.3: Buchen ─────────────────────────────────────────────
#
# Wandelt einen "in Bearbeitung"-Einkauf (QUELLE=15, STADIUM=0,
# VRENUM='EDI-NNNNNN') in eine verbuchte EK-Rechnung um:
#   QUELLE=5, STADIUM=2 (offen/unbezahlt), VRENUM=Belegnummer aus
#   REGISTRY 'EK-RECH' (Counter +1 atomar).
#
# Trace-Schritte siehe memory/project_einkauf_buchen_phasec.md.
# CAO-Caches (ARTIKEL_BDATEN, EKBESTELL_OP, JOURNAL_OP) sind hier
# bewusst NICHT aktualisiert — die werden beim naechsten CAO-Sync
# bzw. beim Lese-Zugriff in CAO neu aufgebaut. Falls XT-Anzeigen
# darauf bauen, separate Tasks (TODO).


def buchen_vorschau(rec_id: int) -> dict[str, Any]:
    """Read-only-Pruefung VOR dem eigentlichen Buchen.

    Liefert:
      ``ok`` / ``fehler`` — Beleg ueberhaupt buchbar?
      ``warnungen`` — soft (z.B. 'kein Lieferant')
      ``preisabweichungen`` — Liste {pos_id, artnum, bezeichnung,
        alt_ek, neu_ek, diff_proz} fuer Pos mit
        ``EPREIS != ARTIKEL_PREIS.PREIS`` (Lief-Preis bei PREIS_TYP=5).
        Das UI zeigt diese Liste vor dem Buchen, der User entscheidet
        pro Pos ob der EK-Preis im Stamm uebernommen wird.
      ``naechste_belegnum`` — Vorschau der EK-RECH-Nummer (NICHT reserviert).
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM JOURNAL WHERE REC_ID=%s AND QUELLE=15",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            return {'ok': False, 'fehler': 'Beleg ist nicht in Bearbeitung'}
        if int(kopf.get('STADIUM') or 0) != 0:
            return {'ok': False,
                    'fehler': f"STADIUM={kopf['STADIUM']} — schon gebucht"}

        warnungen: list[dict[str, str]] = []
        addr_id = int(kopf.get('ADDR_ID') or -1)
        if addr_id <= 0:
            warnungen.append({'art': 'lieferant_fehlt',
                              'text': 'Kein Lieferant gesetzt'})

        cur.execute(
            "SELECT COUNT(*) AS n FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND TOP_POS_ID=-1",
            (rec_id,)
        )
        if int((cur.fetchone() or {}).get('n') or 0) == 0:
            warnungen.append({'art': 'keine_pos',
                              'text': 'Keine Positionen'})

        # Preisabweichungen: EPREIS vs. ARTIKEL_PREIS.PREIS
        # (LEFT JOIN — Pos ohne Lief-Preis-Pflege ist NICHT abweichend)
        preisabweichungen: list[dict[str, Any]] = []
        if addr_id > 0:
            cur.execute(
                """SELECT jp.REC_ID AS pos_id, jp.ARTIKEL_ID, jp.ARTNUM,
                          jp.BEZEICHNUNG, jp.EPREIS AS neu_ek,
                          ap.PREIS AS alt_ek
                     FROM JOURNALPOS jp
                LEFT JOIN ARTIKEL_PREIS ap
                       ON ap.ARTIKEL_ID = jp.ARTIKEL_ID
                      AND ap.ADRESS_ID = %s
                      AND ap.PREIS_TYP = 5
                    WHERE jp.JOURNAL_ID = %s AND jp.TOP_POS_ID = -1
                      AND jp.ARTIKEL_ID > 0""",
                (addr_id, rec_id),
            )
            for r in cur.fetchall():
                if r.get('alt_ek') is None:
                    # Kein Lief-Preis gepflegt — wird beim Buchen neu
                    # angelegt (Phase 5a-Mechanik).  Wir markieren das
                    # als "neuer Preis", damit der User es sieht.
                    preisabweichungen.append({
                        'pos_id': int(r['pos_id']),
                        'artnum': r['ARTNUM'],
                        'bezeichnung': r['BEZEICHNUNG'],
                        'alt_ek': None,
                        'neu_ek': float(r['neu_ek'] or 0),
                        'diff_proz': None,
                        'art': 'neu',
                    })
                    continue
                alt = float(r['alt_ek'] or 0)
                neu = float(r['neu_ek'] or 0)
                if abs(alt - neu) > 0.0001:
                    diff_proz = ((neu - alt) / alt * 100) if alt > 0 else None
                    preisabweichungen.append({
                        'pos_id': int(r['pos_id']),
                        'artnum': r['ARTNUM'],
                        'bezeichnung': r['BEZEICHNUNG'],
                        'alt_ek': alt,
                        'neu_ek': neu,
                        'diff_proz': diff_proz,
                        'art': 'geaendert',
                    })

        # Vorschau-Belegnummer (NICHT reservieren — nur fuer Anzeige)
        cur.execute(
            r"SELECT VAL_INT2, VAL_CHAR FROM REGISTRY "
            r"WHERE MAINKEY='MAIN\\NUMBERS' AND NAME='EK-RECH'"
        )
        row = cur.fetchone() or {}
        next_n = int(row.get('VAL_INT2') or 0) + 1
        pad = (row.get('VAL_CHAR') or '000000')
        n_stellen = pad.count('0') if pad.count('0') > 0 else 6
        belegnum_vorschau = f'{next_n:0{n_stellen}d}'

    kann_buchen = not any(
        w['art'] in ('lieferant_fehlt', 'keine_pos') for w in warnungen
    )
    return {
        'ok': True,
        'kann_buchen': kann_buchen,
        'warnungen': warnungen,
        'preisabweichungen': preisabweichungen,
        'naechste_belegnum': belegnum_vorschau,
    }


def einkauf_buchen(rec_id: int, *, ma_id: int | None = None,
                   ma_name: str = '',
                   preis_uebernahmen: dict | None = None
                   ) -> dict[str, Any]:
    """Verbucht einen Einkauf endgueltig.

    Trace-Schritte (siehe memory/project_einkauf_buchen_phasec.md):
      8a RDATUM final
      8b NUMMERN_LOG + Belegnummer aus REGISTRY 'EK-RECH'
      8c Lieferanten-Status
      8d JOURNAL final (QUELLE=5, STADIUM=2, VRENUM=…)
      8e ZUSATZDATEN (best-effort)
      8f Pro Pos:
         - ARTIKEL_PREIS Update (nur bei 'uebernehmen'-Entscheidung)
         - EKEINGANG_POS.BERECHNET='Y' (bei Pos aus WE)
         - ARTIKEL_HISTORIE + MENGE_AKT (nur bei freien/Bestell-Pos
           ohne WE-Bezug — bei WE-Pos wurde Lager schon beim WE-Buchen
           gebucht)
         - JOURNALPOS QUELLE→5
      8h+8i EKBESTELL_POS / EKBESTELL Status-Sync
      8m EKEINGANG.STADIUM=9 fuer voll berechnete WE

    Args:
      rec_id: JOURNAL.REC_ID des Einkaufs (muss QUELLE=15, STADIUM=0)
      ma_id, ma_name: Mitarbeiter (fuer GEAEND_NAME, ZUSATZDATEN)
      preis_uebernahmen: dict {pos_id (str|int) -> 'uebernehmen'|'behalten'}
        Default-Verhalten falls Pos nicht im dict: 'uebernehmen'.
        Aufrufer sollte vorher buchen_vorschau() aufrufen und das UI
        die Entscheidungen sammeln lassen.

    Returns:
      ``{'ok': True, 'rec_id': ..., 'vrenum': '253433', ...}``
    """
    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]
    preis_uebernahmen = preis_uebernahmen or {}
    # Lookups vereinheitlichen: keys koennen str oder int sein
    _entscheidung = lambda pid: (
        preis_uebernahmen.get(str(pid))
        or preis_uebernahmen.get(int(pid))
        or 'uebernehmen'
    )

    # cao_log_hashsum + Phase-5a-Helper sind beide in common.*; lokal
    # importieren um Zirkular-Imports beim Modul-Laden zu vermeiden.
    from common import cao_log_hashsum
    from common.einkauf import (_next_registry_nummer,
                                 _vk_kontrolle_ek_eintrag)

    # ── ACHTUNG: CAO-Tabellen sind MyISAM, also KEINE Transaktionen.
    # Rollback ist effektiv ein No-Op. Wir designen daher idempotent:
    # jeder Schritt darf mehrfach laufen ohne Schaden anzurichten.
    # Der Aufrufer kann bei einem Crash mid-flight einfach erneut
    # aufrufen — die WHERE-Clauses und Existenz-Checks fangen ab.
    with get_db_transaction() as cur:
        # 0. Beleg validieren — akzeptiert sowohl frisch (QUELLE=15)
        # als auch resume nach partieller Buchung (QUELLE=5, STADIUM=2).
        cur.execute(
            "SELECT * FROM JOURNAL WHERE REC_ID=%s AND QUELLE IN (5, 15)",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            raise PermissionError('Beleg nicht gefunden')
        ist_resume = (int(kopf.get('QUELLE') or 0) == 5
                      and int(kopf.get('STADIUM') or 0) == 2)
        ist_frisch = (int(kopf.get('QUELLE') or 0) == 15
                      and int(kopf.get('STADIUM') or 0) == 0)
        if not (ist_frisch or ist_resume):
            raise PermissionError(
                f"QUELLE={kopf['QUELLE']}, STADIUM={kopf['STADIUM']} — "
                "weder in Bearbeitung noch resumebar (offen/unbezahlt)"
            )
        addr_id = int(kopf.get('ADDR_ID') or -1)
        if addr_id <= 0:
            raise ValueError('Lieferant fehlt — bitte vor dem Buchen setzen')

        cur.execute(
            "SELECT * FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND TOP_POS_ID=-1 "
            "ORDER BY POSITION",
            (rec_id,)
        )
        positionen = cur.fetchall()
        if not positionen:
            raise ValueError('Keine Positionen — nicht buchbar')

        # 8a/8b/8d Header — nur bei frischem Lauf.  Bei resume ist die
        # VRENUM schon vergeben und das JOURNAL ist auf QUELLE=5/STADIUM=2.
        if ist_frisch:
            cur.execute(
                "UPDATE JOURNAL SET RDATUM=NOW(), GEAEND=CURDATE(), "
                "GEAEND_NAME=%s WHERE REC_ID=%s AND QUELLE=15",
                (ma_name_safe, rec_id)
            )
            belegnum = _next_registry_nummer(cur, 'EK-RECH')

            # NUMMERN_LOG-Eintrag (XT-eigene HASHSUM)
            cur.execute(
                "INSERT INTO NUMMERN_LOG "
                "(QUELLE, JOURNAL_ID, NUMMER, ANGELEGT, ANGELEGT_NAME, HASHSUM) "
                "VALUES (5, %s, %s, NOW(), %s, %s)",
                (rec_id, belegnum, ma_name_safe, '$$')
            )
            nl_id = int(cur.lastrowid)
            cur.execute(
                "SELECT HASHSUM FROM NUMMERN_LOG "
                "WHERE REC_ID < %s ORDER BY REC_ID DESC LIMIT 1",
                (nl_id,)
            )
            prev_row = cur.fetchone()
            prev = prev_row.get('HASHSUM') if prev_row else None
            try:
                new_hash = cao_log_hashsum.compute(
                    table_name='NUMMERN_LOG',
                    hashstring=f"V1|{nl_id}|5|{rec_id}|{belegnum}",
                    previous_hashsum=prev,
                )
                cur.execute(
                    "UPDATE NUMMERN_LOG SET HASHSUM=%s WHERE REC_ID=%s",
                    (new_hash, nl_id)
                )
            except Exception as exc:
                log.warning('NUMMERN_LOG-HASHSUM (rec %s): %s', nl_id, exc)
        else:
            # Resume: existierende Daten weiterverwenden
            belegnum = (kopf.get('VRENUM') or '').strip()
            if not belegnum:
                raise PermissionError(
                    'Resume nicht möglich — JOURNAL.VRENUM leer')
            cur.execute(
                "SELECT REC_ID FROM NUMMERN_LOG "
                "WHERE QUELLE=5 AND JOURNAL_ID=%s AND NUMMER=%s "
                "ORDER BY REC_ID DESC LIMIT 1",
                (rec_id, belegnum)
            )
            row = cur.fetchone()
            nl_id = int(row['REC_ID']) if row else 0
            log.info('einkauf_buchen RESUME: rec_id=%s vrenum=%s',
                     rec_id, belegnum)

        # 8c. Lieferanten-Status: Default-Zahlart setzen (falls leer),
        # STATUS-Bit 16 (Lieferant) setzen.
        zahlart_id = kopf.get('ZAHLART')
        if zahlart_id is not None:
            cur.execute(
                "UPDATE ADRESSEN SET LIEF_ZAHLART=%s "
                "WHERE REC_ID=%s AND (LIEF_ZAHLART IS NULL OR LIEF_ZAHLART<0)",
                (int(zahlart_id), addr_id)
            )
        cur.execute(
            "UPDATE ADRESSEN SET STATUS=COALESCE(STATUS,0)|16 "
            "WHERE REC_ID=%s",
            (addr_id,)
        )

        # 8d. JOURNAL final-state. MA_ID setzen falls noch nicht (Audit).
        cur.execute(
            "UPDATE JOURNAL SET QUELLE=5, VRENUM=%s, STADIUM=2, "
            "GEAEND=CURDATE(), GEAEND_NAME=%s, "
            "MA_ID=COALESCE(NULLIF(MA_ID,0), %s) "
            "WHERE REC_ID=%s",
            (belegnum, ma_name_safe, ma_id or 0, rec_id)
        )

        # 8e. ZUSATZDATEN (best-effort — Snapshot des bearbeitenden MA).
        # ZUSATZDATEN hat KEIN REC_ID/MA_ID/ERSTELLT — nur natuerliche Keys
        # FREMD_ID + FREMD_QUELLE + MA_*-Snapshot-Spalten.  Wir schreiben
        # nur das Minimum und ignorieren Duplikate (PK-Kollision wenn der
        # Beleg ein zweites Mal angefasst wird).
        try:
            cur.execute(
                "INSERT IGNORE INTO ZUSATZDATEN "
                "(FREMD_ID, FREMD_QUELLE, MA_NAME) "
                "VALUES (%s, 5, %s)",
                (rec_id, ma_name_safe)
            )
        except Exception as exc:
            log.info('ZUSATZDATEN nicht geschrieben (%s): %s', rec_id, exc)

        # 8f. Pro Pos — nur die Pos verarbeiten, die noch QUELLE=15 sind.
        # Schon-finalisierte Pos (QUELLE=5) ueberspringen wir, damit
        # MENGE_AKT/ARTIKEL_HISTORIE bei einem Re-Run nicht dupliziert
        # werden. Idempotenz!
        for p in positionen:
            if int(p.get('QUELLE') or 0) != 15:
                continue
            pos_id = int(p['REC_ID'])
            artikel_id = int(p.get('ARTIKEL_ID') or 0)
            menge = float(p.get('MENGE') or 0)
            epreis = float(p.get('EPREIS') or 0)
            ekeingang_flag = (p.get('EKEINGANG') or 'N')
            we_pos_id = int(p.get('QUELLE_WE') or 0)
            best_pos_id = int(p.get('QUELLE_SRC') or 0)

            # 8f.1 ARTIKEL_PREIS: existiert Lief-Preis?
            # Composite-PK: (ARTIKEL_ID, ADRESS_ID, PREIS_TYP) — keine REC_ID.
            if artikel_id > 0:
                cur.execute(
                    "SELECT PREIS FROM ARTIKEL_PREIS "
                    "WHERE ARTIKEL_ID=%s AND ADRESS_ID=%s AND PREIS_TYP=5 "
                    "FOR UPDATE",
                    (artikel_id, addr_id)
                )
                ap = cur.fetchone()
                ent = _entscheidung(pos_id)

                if ap is None:
                    # Kein Lief-Preis: bei 'uebernehmen' anlegen.
                    # ARTIKEL_PREIS hat kein ANGELEGT — nur GEAEND/GEAEND_NAME.
                    if ent == 'uebernehmen':
                        cur.execute(
                            "INSERT INTO ARTIKEL_PREIS "
                            "(ARTIKEL_ID, ADRESS_ID, PREIS_TYP, PT2, "
                            " PREIS, GEAEND, GEAEND_NAME) "
                            "VALUES (%s, %s, 5, 'EK', %s, NOW(), %s)",
                            (artikel_id, addr_id, epreis, ma_name_safe)
                        )
                else:
                    alt_preis = float(ap.get('PREIS') or 0)
                    if abs(alt_preis - epreis) > 0.0001 and ent == 'uebernehmen':
                        cur.execute(
                            "UPDATE ARTIKEL_PREIS "
                            "SET PREIS=%s, GEAEND=NOW(), GEAEND_NAME=%s "
                            "WHERE ARTIKEL_ID=%s AND ADRESS_ID=%s "
                            "  AND PREIS_TYP=5",
                            (epreis, ma_name_safe, artikel_id, addr_id)
                        )
                        try:
                            _vk_kontrolle_ek_eintrag(
                                artikel_rec_id=artikel_id,
                                alt_ek=alt_preis,
                                neu_ek=epreis,
                                bestellung_rec_id=rec_id,
                                ma_id=ma_id,
                                bestell_nr=belegnum,
                                lief_kuerzel='',
                            )
                        except Exception as exc:
                            log.warning('VK-Kontrolle ART %s: %s',
                                        artikel_id, exc)
                    else:
                        # Nur Touch-Marker fuer "wann zuletzt gesehen"
                        cur.execute(
                            "UPDATE ARTIKEL_PREIS SET GEAEND=NOW() "
                            "WHERE ARTIKEL_ID=%s AND ADRESS_ID=%s "
                            "  AND PREIS_TYP=5",
                            (artikel_id, addr_id)
                        )

            # 8f.2 Lager-Bewegung
            if ekeingang_flag == 'Y' and we_pos_id > 0:
                # Aus WE: Lager schon gebucht → nur 'berechnet' markieren
                cur.execute(
                    "UPDATE EKEINGANG_POS SET BERECHNET='Y' WHERE REC_ID=%s",
                    (we_pos_id,)
                )
                if best_pos_id > 0:
                    cur.execute(
                        "UPDATE EKBESTELL_POS SET EKEINGANG='N' "
                        "WHERE REC_ID=%s",
                        (best_pos_id,)
                    )
            else:
                # Frei oder direkt aus Bestellung → Lager bewegen
                if artikel_id > 0:
                    cur.execute(
                        "SELECT MENGE_AKT FROM ARTIKEL "
                        "WHERE REC_ID=%s FOR UPDATE",
                        (artikel_id,)
                    )
                    art = cur.fetchone() or {}
                    alt_lager = float(art.get('MENGE_AKT') or 0)
                    neu_lager = alt_lager + menge
                    try:
                        cur.execute(
                            "INSERT INTO ARTIKEL_HISTORIE "
                            "(ARTIKEL_ID, QUELLE, QUELLE_STR, "
                            " MENGE_LAGER, MENGE_GEBUCHT, JID, "
                            " GEAND, GEAND_NAME, INFO) "
                            "VALUES (%s, 5, %s, %s, %s, %s, "
                            "        NOW(), %s, '')",
                            (artikel_id, f'EK-Rechnung {belegnum}',
                             neu_lager, menge, rec_id, ma_name_safe)
                        )
                    except Exception as exc:
                        log.warning('ARTIKEL_HISTORIE ART %s: %s',
                                    artikel_id, exc)
                    cur.execute(
                        "UPDATE ARTIKEL "
                        "SET MENGE_AKT=COALESCE(MENGE_AKT,0)+%s, "
                        "    SHOP_CHANGE_FLAG=1 "
                        "WHERE REC_ID=%s",
                        (menge, artikel_id)
                    )

            # 8f.3 JOURNALPOS finalisieren (Schema hat KEIN GEAEND/MA_ID,
            # nur QUELLE/VRENUM/GEBUCHT — Audit liegt in JOURNAL).
            # WHERE QUELLE=15 als zusaetzlicher Idempotenz-Schutz.
            cur.execute(
                "UPDATE JOURNALPOS "
                "SET QUELLE=5, VRENUM=%s, GEBUCHT='Y' "
                "WHERE REC_ID=%s AND QUELLE=15",
                (belegnum, pos_id)
            )

        # 8h+8i EKBESTELL/EKBESTELL_POS Status-Sync
        cur.execute(
            "SELECT DISTINCT bp.EKBESTELL_ID "
            "  FROM JOURNALPOS jp "
            "  JOIN EKBESTELL_POS bp ON bp.REC_ID = jp.QUELLE_SRC "
            " WHERE jp.JOURNAL_ID=%s AND jp.QUELLE_SRC>0",
            (rec_id,)
        )
        bestell_ids = [int(r['EKBESTELL_ID']) for r in cur.fetchall()]
        for bid in bestell_ids:
            # Pro Bestellpos: STADIUM=9 wenn alles abgerechnet,
            # =3 wenn teilweise. Wir zaehlen ueber JOURNALPOS QUELLE=5.
            cur.execute(
                """UPDATE EKBESTELL_POS bp
                      SET STADIUM = CASE
                          WHEN (bp.MENGE - COALESCE((
                              SELECT SUM(jp.MENGE) FROM JOURNALPOS jp
                              JOIN JOURNAL j ON j.REC_ID=jp.JOURNAL_ID
                              WHERE jp.QUELLE_SRC=bp.REC_ID AND j.QUELLE=5
                          ), 0)) <= 0.0001 THEN 9
                          WHEN COALESCE((
                              SELECT SUM(jp.MENGE) FROM JOURNALPOS jp
                              JOIN JOURNAL j ON j.REC_ID=jp.JOURNAL_ID
                              WHERE jp.QUELLE_SRC=bp.REC_ID AND j.QUELLE=5
                          ), 0) > 0 THEN 3
                          ELSE bp.STADIUM
                      END
                    WHERE bp.EKBESTELL_ID=%s
                      AND bp.STADIUM IN (2,3,93,95)""",
                (bid,)
            )
            cur.execute(
                """UPDATE EKBESTELL b
                      SET STADIUM = CASE
                          WHEN (SELECT COUNT(*) FROM EKBESTELL_POS p
                                 WHERE p.EKBESTELL_ID=b.REC_ID
                                   AND p.STADIUM NOT IN (9,127)) = 0 THEN 9
                          WHEN (SELECT COUNT(*) FROM EKBESTELL_POS p
                                 WHERE p.EKBESTELL_ID=b.REC_ID
                                   AND p.STADIUM IN (9,3)) > 0 THEN 3
                          ELSE b.STADIUM
                      END
                    WHERE b.REC_ID=%s""",
                (bid,)
            )

        # 8m. EKEINGANG.STADIUM=9 fuer voll berechnete WE
        cur.execute(
            "SELECT DISTINCT QUELLE_WE FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND QUELLE_WE>0 AND EKEINGANG='Y'",
            (rec_id,)
        )
        we_pos_ids = [int(r['QUELLE_WE']) for r in cur.fetchall()
                       if int(r.get('QUELLE_WE') or 0) > 0]
        if we_pos_ids:
            placeholders = ','.join(['%s'] * len(we_pos_ids))
            cur.execute(
                f"SELECT DISTINCT EKEINGANG_ID FROM EKEINGANG_POS "
                f"WHERE REC_ID IN ({placeholders})",
                we_pos_ids
            )
            we_ids = [int(r['EKEINGANG_ID']) for r in cur.fetchall()]
            for we_id in we_ids:
                cur.execute(
                    "UPDATE EKEINGANG SET STADIUM=9 "
                    "WHERE REC_ID=%s AND NOT EXISTS ("
                    "  SELECT 1 FROM EKEINGANG_POS "
                    "  WHERE EKEINGANG_ID=%s AND BERECHNET='N'"
                    ")",
                    (we_id, we_id)
                )

    return {'ok': True, 'rec_id': rec_id, 'vrenum': belegnum,
            'nummern_log_id': nl_id}


# ── Storno + Kopieren von gebuchten EK-Rechnungen ─────────────────


def einkauf_storno_pruefung(rec_id: int) -> dict:
    """Pre-Check fuer EK-Storno: gibt es aktive Zahlungen?

    Aktive Zahlung = ``ZAHLUNGEN.STORNO=0 AND GEBUCHT='Y'`` (siehe
    reference_cao_zahlungen.md). XT storniert Zahlungen NICHT selbst —
    der User muss das in CAO Faktura erledigen.
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, QUELLE, STADIUM, VRENUM FROM JOURNAL "
            "WHERE REC_ID=%s",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            raise LookupError(f'Beleg {rec_id} nicht gefunden')

        cur.execute(
            "SELECT REC_ID, DATUM, BETRAG, ART, ZAHLART_NAME "
            "  FROM ZAHLUNGEN "
            " WHERE JOURNAL_ID=%s AND QUELLE=5 "
            "   AND STORNO=0 AND GEBUCHT='Y' "
            " ORDER BY DATUM DESC",
            (rec_id,)
        )
        zahlungen = cur.fetchall()

    return {
        'ok': not zahlungen,
        'aktive_zahlungen': zahlungen,
        'kopf': {
            'REC_ID': kopf['REC_ID'],
            'QUELLE': kopf['QUELLE'],
            'STADIUM': kopf['STADIUM'],
            'VRENUM': kopf['VRENUM'],
        },
    }


def einkauf_storno_gebucht(rec_id: int, *, ma_id: int | None = None,
                             ma_name: str = '') -> dict[str, Any]:
    """Storniert eine GEBUCHTE EK-Rechnung (QUELLE=5).

    Pre-Check: keine aktiven Zahlungen. Bei Blockierung
    PermissionError mit Hinweis "in CAO Faktura stornieren".

    Effekte (idempotent — siehe feedback_myisam_idempotent.md):
      - JOURNAL.STADIUM = 127, INFO mit Storno-Vermerk
      - JOURNALPOS.STATUS_FLAG = 127 (CAO-Mimik fuer Pos-Storno-Marker)
      - Lager-Korrektur fuer freie/Bestell-Pos (EKEINGANG='N'):
        ARTIKEL.MENGE_AKT - MENGE, ARTIKEL_HISTORIE-Eintrag (Storno)
      - EKEINGANG_POS.BERECHNET = 'N' (fuer Pos die aus WE kamen)
      - EKEINGANG.STADIUM zurueck auf 2/3 (re-compute)
      - EKBESTELL_POS / EKBESTELL Status zurueck (re-compute analog Buchen)
      - ARTIKEL_PREIS bleibt unveraendert (Audit-Wert)
      - NUMMERN_LOG bleibt (Audit-Pflicht — KEIN Loeschen!)

    NICHT-storniert: in-Bearbeitung-Belege (QUELLE=15) → nutze
    ``einkauf_storno()`` (DELETE).
    """
    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:50]

    # Pre-Check
    pruef = einkauf_storno_pruefung(rec_id)
    kopf_pruef = pruef['kopf']
    if int(kopf_pruef.get('QUELLE') or 0) != 5:
        raise PermissionError(
            f"QUELLE={kopf_pruef.get('QUELLE')} — kein gebuchter EK-Beleg "
            "(QUELLE=5 erwartet)"
        )
    if int(kopf_pruef.get('STADIUM') or 0) == 127:
        # idempotent: schon storniert
        return {'ok': True, 'rec_id': rec_id, 'idempotent': True}
    if not pruef['ok']:
        n = len(pruef['aktive_zahlungen'])
        raise PermissionError(
            f'Storno blockiert — {n} aktive Zahlung(en) '
            'bitte zuerst in CAO Faktura stornieren'
        )

    with get_db_transaction() as cur:
        # Pos lesen (alle, aber Lager nur fuer noch-nicht-stornierte
        # Pos zurueckrollen)
        cur.execute(
            "SELECT * FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND TOP_POS_ID=-1 "
            "ORDER BY POSITION",
            (rec_id,)
        )
        positionen = cur.fetchall()

        # Pos-Loop: Lager-Korrektur + EKEINGANG_POS-Reset
        # Idempotenz: nur Pos die noch STATUS_FLAG != 127 sind anfassen.
        for p in positionen:
            if int(p.get('STATUS_FLAG') or 0) == 127:
                continue   # Pos schon als storniert markiert
            pos_id = int(p['REC_ID'])
            artikel_id = int(p.get('ARTIKEL_ID') or 0)
            menge = float(p.get('MENGE') or 0)
            ekeingang_flag = (p.get('EKEINGANG') or 'N')
            we_pos_id = int(p.get('QUELLE_WE') or 0)

            # Lager-Korrektur: nur fuer Pos die ueberhaupt Lager bewegt
            # haben (frei / direkt aus Bestellung).  Pos aus WE haben
            # KEIN Lager bewegt (das war der WE-Buchen-Step).
            if ekeingang_flag == 'N' and artikel_id > 0 and menge > 0:
                cur.execute(
                    "SELECT MENGE_AKT FROM ARTIKEL WHERE REC_ID=%s",
                    (artikel_id,)
                )
                art = cur.fetchone() or {}
                neu_lager = float(art.get('MENGE_AKT') or 0) - menge
                cur.execute(
                    "INSERT INTO ARTIKEL_HISTORIE "
                    "(ARTIKEL_ID, QUELLE, QUELLE_STR, MENGE_LAGER, "
                    " MENGE_GEBUCHT, JID, GEAND, GEAND_NAME, INFO) "
                    "VALUES (%s, 5, %s, %s, %s, %s, NOW(), %s, %s)",
                    (artikel_id,
                     f'Storno EK-Rechnung {kopf_pruef.get("VRENUM") or rec_id}',
                     neu_lager, -menge, rec_id, ma_name_safe,
                     'EK-Rechnungs-Storno: Lager-Korrektur'),
                )
                cur.execute(
                    "UPDATE ARTIKEL "
                    "SET MENGE_AKT=COALESCE(MENGE_AKT,0)-%s, "
                    "    SHOP_CHANGE_FLAG=1 "
                    "WHERE REC_ID=%s",
                    (menge, artikel_id)
                )

            # WE-Pos: Berechnet zurueck auf 'N'
            if ekeingang_flag == 'Y' and we_pos_id > 0:
                cur.execute(
                    "UPDATE EKEINGANG_POS SET BERECHNET='N' "
                    "WHERE REC_ID=%s AND BERECHNET='Y'",
                    (we_pos_id,)
                )

            # Pos-Storno-Marker: STATUS_FLAG=127
            cur.execute(
                "UPDATE JOURNALPOS SET STATUS_FLAG=127 "
                "WHERE REC_ID=%s AND COALESCE(STATUS_FLAG,0)!=127",
                (pos_id,)
            )

        # Header: STADIUM=127 + INFO (Idempotenz: WHERE STADIUM!=127)
        info_text = (f'Storniert am {date.today().strftime("%d.%m.%Y")} '
                      f'durch {ma_name_safe}')
        cur.execute(
            "UPDATE JOURNAL "
            "SET STADIUM=127, "
            "    GEAEND=CURDATE(), GEAEND_NAME=%s, "
            "    STORNO_INFO=%s "
            "WHERE REC_ID=%s AND STADIUM!=127",
            (ma_name_safe, info_text[:255], rec_id)
        )

        # EKBESTELL_POS-Status neu berechnen (Pos die jetzt durch das
        # Storno wieder unbedient sind)
        cur.execute(
            "SELECT DISTINCT bp.EKBESTELL_ID, bp.REC_ID AS bp_id "
            "  FROM JOURNALPOS jp "
            "  JOIN EKBESTELL_POS bp ON bp.REC_ID = jp.QUELLE_SRC "
            " WHERE jp.JOURNAL_ID=%s AND jp.QUELLE_SRC>0",
            (rec_id,)
        )
        bp_ids = [(int(r['EKBESTELL_ID']), int(r['bp_id']))
                   for r in cur.fetchall()]
        for ek_id, bp_id in bp_ids:
            # Re-compute: ist die Bestellpos nach dem Storno wieder offen?
            cur.execute(
                """UPDATE EKBESTELL_POS bp
                      SET STADIUM = CASE
                          WHEN COALESCE((
                              SELECT SUM(jp.MENGE) FROM JOURNALPOS jp
                              JOIN JOURNAL j ON j.REC_ID=jp.JOURNAL_ID
                              WHERE jp.QUELLE_SRC=bp.REC_ID
                                AND j.QUELLE=5
                                AND j.STADIUM NOT IN (125,126,127)
                                AND COALESCE(jp.STATUS_FLAG,0)!=127
                          ), 0) <= 0.0001 THEN 2
                          ELSE 3
                      END
                    WHERE bp.REC_ID=%s
                      AND bp.STADIUM NOT IN (127)""",
                (bp_id,)
            )

        # EKBESTELL-Header neu berechnen (analog buchen)
        for ek_id, _ in bp_ids:
            cur.execute(
                """UPDATE EKBESTELL b
                      SET STADIUM = CASE
                          WHEN (SELECT COUNT(*) FROM EKBESTELL_POS p
                                 WHERE p.EKBESTELL_ID=b.REC_ID
                                   AND p.STADIUM NOT IN (9,127)) = 0
                                AND (SELECT COUNT(*) FROM EKBESTELL_POS p
                                      WHERE p.EKBESTELL_ID=b.REC_ID
                                        AND p.STADIUM != 127) > 0 THEN 9
                          WHEN (SELECT COUNT(*) FROM EKBESTELL_POS p
                                 WHERE p.EKBESTELL_ID=b.REC_ID
                                   AND p.STADIUM IN (3,9)) > 0 THEN 3
                          WHEN (SELECT COUNT(*) FROM EKBESTELL_POS p
                                 WHERE p.EKBESTELL_ID=b.REC_ID
                                   AND p.STADIUM = 2) > 0 THEN 2
                          ELSE b.STADIUM
                      END
                    WHERE b.REC_ID=%s""",
                (ek_id,)
            )

        # EKEINGANG.STADIUM neu berechnen — wenn jetzt wieder unberechnete
        # Pos existieren, zurueck auf STADIUM=2 (oder 3 bei Mix).
        cur.execute(
            "SELECT DISTINCT QUELLE_WE FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND QUELLE_WE>0 AND EKEINGANG='Y'",
            (rec_id,)
        )
        we_pos_ids = [int(r['QUELLE_WE']) for r in cur.fetchall()
                       if int(r.get('QUELLE_WE') or 0) > 0]
        if we_pos_ids:
            placeholders = ','.join(['%s'] * len(we_pos_ids))
            cur.execute(
                f"SELECT DISTINCT EKEINGANG_ID FROM EKEINGANG_POS "
                f"WHERE REC_ID IN ({placeholders})",
                we_pos_ids
            )
            we_ids = [int(r['EKEINGANG_ID']) for r in cur.fetchall()]
            for we_id in we_ids:
                cur.execute(
                    "UPDATE EKEINGANG SET STADIUM = CASE "
                    "  WHEN EXISTS (SELECT 1 FROM EKEINGANG_POS "
                    "               WHERE EKEINGANG_ID=%s AND BERECHNET='N') "
                    "  AND EXISTS (SELECT 1 FROM EKEINGANG_POS "
                    "              WHERE EKEINGANG_ID=%s AND BERECHNET='Y') "
                    "  THEN 3 "
                    "  WHEN EXISTS (SELECT 1 FROM EKEINGANG_POS "
                    "               WHERE EKEINGANG_ID=%s AND BERECHNET='N') "
                    "  THEN 2 "
                    "  ELSE STADIUM END "
                    "WHERE REC_ID=%s AND STADIUM IN (3,9)",
                    (we_id, we_id, we_id, we_id)
                )

    return {'ok': True, 'rec_id': rec_id, 'storniert': True}


def einkauf_kopieren(rec_id: int, *, ma_id: int | None = None,
                      ma_name: str = '') -> dict[str, Any]:
    """Kopiert eine EK-Rechnung als neuen Einkauf in Bearbeitung
    (QUELLE=15, STADIUM=0, neue ``EDI-NNNNNN`` VRENUM).

    Alle JOURNALPOS-Felder werden 1:1 uebernommen, **inklusive**
    QUELLE_SRC, QUELLE_WE und EKEINGANG-Flag — damit beim erneuten
    Buchen der Kopie der gleiche WE/Bestell-Bezug genutzt wird.
    Voraussetzung: das Original muss vorher storniert sein, sonst
    wuerden die WE-Pos doppelt referenziert sein. Wir lassen das
    aber zu (User kann kopieren ohne zu stornieren) — er muss dann
    selbst die Quellen anpassen oder das Original stornieren.

    Returns: ``{'ok': True, 'neue_rec_id': N, 'neue_vrenum': 'EDI-...'}``
    """
    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:100]

    with get_db_transaction() as cur:
        cur.execute(
            "SELECT * FROM JOURNAL WHERE REC_ID=%s AND QUELLE IN (5, 15)",
            (rec_id,)
        )
        original = cur.fetchone()
        if not original:
            raise LookupError(f'Beleg {rec_id} nicht gefunden')

        # Neuer EDI-Counter
        neue_vrenum = _next_edi_belegnum(cur)

        # JOURNAL-Header kopieren mit den anlegen-Default-Werten
        # (QUELLE=15, STADIUM=0, HASHSUM='$$', neue VRENUM, RDATUM=NOW)
        cur.execute(
            """INSERT INTO JOURNAL
               (QUELLE, QUELLE_SUB, ADDR_ID, ASP_ID, PROJEKT_ID, SPRACH_ID,
                VRENUM, RDATUM, WAEHRUNG, STADIUM, BRUTTO_FLAG, MWST_FREI_FLAG,
                HASHSUM, FIRMA_ID, MWST_0, MWST_1, MWST_2, MWST_3, AT_MWST,
                ER_DATUM, DEL_FLAG,
                ZAHLART, ZAHLART_NAME, ZAHLART_KURZ, ZAHLART_LANG,
                GEGENKONTO,
                KUN_NAME1, KUN_NAME2, KUN_NAME3, KUNNUM1,
                KUN_STRASSE, KUN_HAUSNR, KUN_LAND, KUN_PLZ, KUN_ORT,
                ANREDE, MA_ID,
                ERSTELLT, ERST_NAME, GEAEND, GEAEND_NAME)
               VALUES (15, 0, %s, %s, %s, %s,
                       %s, NOW(), %s, 0, %s, %s,
                       '$$', %s, %s, %s, %s, %s, %s,
                       NOW(), 'N',
                       %s, %s, %s, %s,
                       %s,
                       %s, %s, %s, %s,
                       %s, %s, %s, %s, %s,
                       %s, %s,
                       CURDATE(), %s, CURDATE(), %s)""",
            (
                int(original.get('ADDR_ID') or -1),
                int(original.get('ASP_ID') or -1),
                int(original.get('PROJEKT_ID') or -1),
                int(original.get('SPRACH_ID') or 2),
                neue_vrenum,
                (original.get('WAEHRUNG') or '€')[:3],
                (original.get('BRUTTO_FLAG') or 'N')[:1],
                (original.get('MWST_FREI_FLAG') or 'N')[:1],
                int(original.get('FIRMA_ID') or 8),
                float(original.get('MWST_0') or 0),
                float(original.get('MWST_1') or 19),
                float(original.get('MWST_2') or 7),
                float(original.get('MWST_3') or 7.8),
                float(original.get('AT_MWST') or 10),
                int(original.get('ZAHLART') or -1),
                (original.get('ZAHLART_NAME') or '')[:100],
                (original.get('ZAHLART_KURZ') or '')[:30],
                (original.get('ZAHLART_LANG') or '')[:255],
                int(original.get('GEGENKONTO') or 0),
                (original.get('KUN_NAME1') or '')[:80],
                (original.get('KUN_NAME2') or '')[:80],
                (original.get('KUN_NAME3') or '')[:80],
                (original.get('KUNNUM1') or '')[:30],
                (original.get('KUN_STRASSE') or '')[:60],
                (original.get('KUN_HAUSNR') or '')[:10],
                (original.get('KUN_LAND') or '')[:5],
                (original.get('KUN_PLZ') or '')[:10],
                (original.get('KUN_ORT') or '')[:60],
                (original.get('ANREDE') or '')[:30],
                int(original.get('MA_ID') or 0) if ma_id is None else int(ma_id),
                ma_name_safe, ma_name_safe,
            )
        )
        neue_rec_id = int(cur.lastrowid)

        # Pos kopieren — alle Felder bis auf REC_ID/JOURNAL_ID/VRENUM/QUELLE
        # Wir nutzen den dynamischen INSERT … SELECT-Trick:
        cur.execute(
            "SELECT * FROM JOURNALPOS "
            "WHERE JOURNAL_ID=%s AND TOP_POS_ID=-1 "
            "ORDER BY POSITION",
            (rec_id,)
        )
        original_pos = cur.fetchall()
        for p in original_pos:
            # STATUS_FLAG=127 (storniert) ueberspringen — die wuerden
            # in die Kopie kommen und dann durch die Buchen-Logik
            # nochmal ueber den Pos-Loop gefuehrt werden.
            if int(p.get('STATUS_FLAG') or 0) == 127:
                continue
            cur.execute(
                """INSERT INTO JOURNALPOS SET
                     JOURNAL_ID=%s, VRENUM=%s, QUELLE=15, QUELLE_SUB=0,
                     QUELLE_SRC=%s, QUELLE_WE=%s, TOP_POS_ID=-1,
                     EKEINGANG=%s,
                     ADDR_ID=%s,
                     ARTIKELTYP=%s, ARTIKEL_ID=%s,
                     ARTNUM=%s, BARCODE=%s, MATCHCODE=%s,
                     BEZEICHNUNG=%s, BEZEICHNUNG_LAND='',
                     KURZBEZEICHNUNG=%s, KURZBEZEICHNUNG_LAND='',
                     FREITEXT=%s, FREITEXT_LAND='',
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
                    neue_rec_id, neue_vrenum,
                    int(p.get('QUELLE_SRC') or 0),
                    int(p.get('QUELLE_WE') or 0),
                    (p.get('EKEINGANG') or 'N')[:1],
                    int(p.get('ADDR_ID') or -1),
                    (p.get('ARTIKELTYP') or 'N')[:1],
                    int(p.get('ARTIKEL_ID') or 0),
                    (p.get('ARTNUM') or '')[:50],
                    (p.get('BARCODE') or '')[:30],
                    (p.get('MATCHCODE') or '')[:50],
                    (p.get('BEZEICHNUNG') or '')[:200],
                    (p.get('KURZBEZEICHNUNG') or '')[:50],
                    (p.get('FREITEXT') or '')[:1000],
                    (p.get('ME_EINHEIT') or '')[:20],
                    (p.get('ME_CODE') or '')[:5],
                    float(p.get('PR_EINHEIT') or 1),
                    float(p.get('VPE') or 0),
                    float(p.get('MENGE') or 0),
                    float(p.get('EPREIS') or 0),
                    float(p.get('EK_PREIS') or 0),
                    float(p.get('GPREIS') or 0),
                    float(p.get('GEWICHT') or 0),
                    int(p.get('STEUER_CODE') or 0),
                    int(p.get('GEGENKTO') or 0),
                    (p.get('BRUTTO_FLAG') or 'N')[:1],
                    int(p.get('WARENGRUPPE') or 0),
                    (p.get('WARENGRUPPENNAME') or '')[:100],
                    int(p.get('POSITION') or 0),
                    str(p.get('VIEW_POS') or '')[:20],
                    ma_name_safe,
                )
            )
        # Header-Summen aus den kopierten Pos neu rechnen
        _summen_aktualisieren(cur, neue_rec_id)

    return {'ok': True, 'neue_rec_id': neue_rec_id,
            'neue_vrenum': neue_vrenum}


def einkauf_storno_und_kopieren(rec_id: int, *, ma_id: int | None = None,
                                 ma_name: str = '') -> dict[str, Any]:
    """Storniert die Original-Rechnung und legt eine Kopie in Bearbeitung an.

    Reihenfolge: Pre-Check (keine Zahlungen) → Storno → Kopie. Wenn
    Storno blockiert ist, wird auch keine Kopie angelegt.
    """
    pruef = einkauf_storno_pruefung(rec_id)
    if not pruef['ok']:
        n = len(pruef['aktive_zahlungen'])
        raise PermissionError(
            f'Storno blockiert — {n} aktive Zahlung(en) '
            'bitte zuerst in CAO Faktura stornieren'
        )
    storno_res = einkauf_storno_gebucht(rec_id, ma_id=ma_id, ma_name=ma_name)
    kopie_res = einkauf_kopieren(rec_id, ma_id=ma_id, ma_name=ma_name)
    return {
        'ok': True,
        'storno': storno_res,
        'kopie': kopie_res,
    }


# ── Phase D: Zahlungs-Erfassung manuell ─────────────────────────


def _zahlung_aus_cao_sepa(z: dict) -> bool:
    """True wenn die Zahlung aus einem CAO-SEPA-Lauf stammt — dann
    blockiert XT den Storno und der User muss in CAO unter
    Finanzen/Ueberweisungen ruecknehmen.

    Erkennung: ART='UB' (Ueberweisung) UND/ODER UW_NUM > 0 (gehoert
    zu einem Ueberweisungs-Lauf). Live-DB-Auswertung zeigt 1:1
    Korrelation der beiden Felder, wir pruefen beide defensiv.
    """
    if (z.get('ART') or '').strip() == 'UB':
        return True
    if int(z.get('UW_NUM') or -1) > 0:
        return True
    return False


# Kassen-relevante Zahlarten (KassenSichV §146a / TSE-Pflicht): Bar, EC,
# Scheck, Kreditkarte duerfen in der Orga-App NICHT erfasst werden —
# das gehoert in die Kasse (Phase Kasse-Zahlungsuebernahme, Backlog
# project_kasse_zahlungsuebernahme.md). Wir filtern sie aus dem
# Erfassungs-Dropdown.
_KASSEN_ZAHLART_REC_IDS = {1, 5, 6, 7, -6}


def zahlungsarten_filter() -> list[dict[str, Any]]:
    """Schlanke Liste ``[{'id','name'}]`` aller aktiven Zahlungsarten
    für das Filter-Dropdown der Einkaufs-Übersicht."""
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, NAME FROM ZAHLUNGSARTEN "
            " WHERE AKTIV_FLAG='Y' ORDER BY NAME"
        )
        return [{'id': int(r['REC_ID']),
                 'name': (r.get('NAME') or '').strip()}
                for r in (cur.fetchall() or [])]


def zahlungsarten_aktiv(*, ohne_kassen_relevant: bool = True
                          ) -> list[dict[str, Any]]:
    """Aktive ZAHLUNGSARTEN + die zur Auswahl stehenden FIBU-Konten,
    damit das Erfassungs-Modal direkt die richtige Bank-/Kasse-Konto-
    Auswahl anbieten kann.

    ``FIBU_KONTEN`` in ZAHLUNGSARTEN ist eine kommagetrennte Liste von
    Konto-Nummern. Wir loesen sie via FIBU_KONTEN-Tabelle (KONTORAHMEN
    aus REGISTRY ``MAIN\\BELEGE / KONTORAHMEN``) zu vollstaendigen
    Konto-Eintraegen auf.

    ``ohne_kassen_relevant`` (default True) blendet Bar/EC/Scheck/
    Kreditkarte aus — diese sind TSE-pflichtig und werden ueber die
    Kasse abgewickelt, nicht ueber die Orga-App.
    """
    with get_db() as cur:
        cur.execute(
            r"SELECT VAL_CHAR FROM REGISTRY "
            r"WHERE MAINKEY='MAIN\\BELEGE' AND NAME='KONTORAHMEN'"
        )
        row = cur.fetchone()
        kontorahmen = (row.get('VAL_CHAR') if row else '') or 'SKR03'

        cur.execute(
            "SELECT REC_ID, NAME, TEXT_KURZ, NETTO_TAGE, "
            "       SKONTO_TAGE, SKONTO_PROZ, FIBU_KONTEN "
            "  FROM ZAHLUNGSARTEN "
            " WHERE AKTIV_FLAG = 'Y' "
            " ORDER BY REC_ID"
        )
        rows = list(cur.fetchall() or [])
        if ohne_kassen_relevant:
            rows = [r for r in rows
                     if int(r['REC_ID']) not in _KASSEN_ZAHLART_REC_IDS]

        # Alle in den FIBU_KONTEN-Listen vorkommenden Konten in einer
        # Bulk-Query nachschlagen
        alle_kontonr: set[int] = set()
        for r in rows:
            for tok in (r.get('FIBU_KONTEN') or '').split(','):
                tok = tok.strip()
                if tok.isdigit():
                    alle_kontonr.add(int(tok))
        konten_map: dict[int, dict] = {}
        if alle_kontonr:
            ph = ','.join(['%s'] * len(alle_kontonr))
            # Nur echte Geldkonten: KONTOART=20 (Bank) bzw. KONTOART=3
            # (Kasse). Alles andere fliegt aus der Auswahl raus, sodass
            # der User nicht versehentlich auf ein Verbindlichkeits-
            # oder Anlagen-Konto bucht.
            cur.execute(
                f"SELECT KONTO, KONTONAME, IBAN, BANK_NAME, KONTOART "
                f"  FROM FIBU_KONTEN "
                f" WHERE KONTORAHMEN=%s "
                f"   AND KONTO IN ({ph}) "
                f"   AND KONTOART IN (3, 20)",
                (kontorahmen, *alle_kontonr)
            )
            for k in cur.fetchall():
                konten_map[int(k['KONTO'])] = k

        for r in rows:
            konten: list[dict] = []
            for tok in (r.get('FIBU_KONTEN') or '').split(','):
                tok = tok.strip()
                if not tok.isdigit():
                    continue
                k = konten_map.get(int(tok))
                if k:
                    konten.append({
                        'konto':     int(k['KONTO']),
                        'name':      (k.get('KONTONAME') or '').strip(),
                        'iban':      (k.get('IBAN') or '').strip(),
                        'kontoart':  int(k.get('KONTOART') or 0),
                    })
            r['konten'] = konten
        return rows


def zahlungen_zu_einkauf(rec_id: int) -> dict[str, Any]:
    """Liefert alle Zahlungen zu einer EK-Rechnung (QUELLE=5) plus
    Zahlungsziel-Info aus dem JOURNAL-Header (RDATUM/SOLL_NTAGE/
    SOLL_STAGE/SOLL_SKONTO) — wird vom Erfassungs-Modal als
    Stammdaten-Hinweis angezeigt.

    Returns: ``{'zahlungen': [...], 'ziel_info': {...}}``
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        cur.execute(
            """SELECT RDATUM, SOLL_NTAGE, SOLL_STAGE, SOLL_SKONTO,
                      BSUMME
                 FROM JOURNAL WHERE REC_ID=%s""",
            (rec_id,)
        )
        kopf = cur.fetchone() or {}
        cur.execute(
            """SELECT z.REC_ID, z.DATUM, z.VALUTA, z.BETRAG,
                      z.SKONTO_PROZ, z.SKONTO_BETRAG,
                      z.WAEHRUNG, z.ART, z.ZAHLART,
                      z.ZAHLART_NAME, z.BELEGNUM, z.VERW_ZWECK,
                      z.GEBUCHT, z.STORNO, z.STORNOGRUND,
                      z.UW_NUM, z.ERSTELLT_AM, z.ERSTELLT_NAME,
                      za.NAME AS zahlart_stamm
                 FROM ZAHLUNGEN z
            LEFT JOIN ZAHLUNGSARTEN za ON za.REC_ID = z.ZAHLART
                WHERE z.JOURNAL_ID = %s AND z.QUELLE = 5
                ORDER BY z.DATUM, z.REC_ID""",
            (rec_id,)
        )
        zeilen = list(cur.fetchall() or [])
    for r in zeilen:
        r['ist_storniert'] = (int(r.get('STORNO') or 0) > 0
                              or (r.get('GEBUCHT') or '') == 'S')
        r['ist_aktiv']     = (not r['ist_storniert']
                              and (r.get('GEBUCHT') or '') == 'Y')
        r['aus_cao_sepa']  = _zahlung_aus_cao_sepa(r)

    # Zahlungsziel-Berechnung (RDATUM + Tage)
    rdatum = kopf.get('RDATUM')
    soll_ntage = int(kopf.get('SOLL_NTAGE') or 0)
    soll_stage = int(kopf.get('SOLL_STAGE') or 0)
    soll_skonto = float(kopf.get('SOLL_SKONTO') or 0)
    bsumme = float(kopf.get('BSUMME') or 0)
    netto_datum = None
    skonto_datum = None
    if rdatum:
        from datetime import timedelta
        rdate = rdatum.date() if hasattr(rdatum, 'date') else rdatum
        netto_datum = rdate + timedelta(days=soll_ntage) if soll_ntage else None
        if soll_stage > 0 and soll_skonto > 0.001:
            skonto_datum = rdate + timedelta(days=soll_stage)
    skonto_max_betrag = (round(bsumme * soll_skonto / 100.0, 2)
                          if soll_skonto > 0.001 else 0.0)

    return {
        'zahlungen': zeilen,
        'ziel_info': {
            'rdatum':            rdatum.isoformat() if rdatum else None,
            'netto_tage':        soll_ntage,
            'skonto_tage':       soll_stage,
            'skonto_proz':       soll_skonto,
            'netto_datum':       netto_datum.isoformat() if netto_datum else None,
            'skonto_datum':      skonto_datum.isoformat() if skonto_datum else None,
            'skonto_max_betrag': skonto_max_betrag,
            'bsumme':            bsumme,
        },
    }


def _zahlungssumme_und_skonto(cur, rec_id: int
                               ) -> tuple[float, float]:
    """Aktive (= nicht stornierte, gebuchte) Zahlungen aufaddieren.

    WICHTIG: ZAHLUNGEN.BETRAG/SKONTO_BETRAG sind bei QUELLE=5 (EK)
    NEGATIV (Geldfluss aus Sicht der Firma = Geld geht raus).
    Wir liefern hier die ABSOLUTBETRAEGE (positiv) zurueck — das macht
    die STADIUM-Berechnung gegen BSUMME (positiv) lesbar.
    """
    cur.execute(
        """SELECT COALESCE(SUM(ABS(BETRAG)), 0) AS s_betrag,
                  COALESCE(SUM(ABS(SKONTO_BETRAG)), 0) AS s_skonto
             FROM ZAHLUNGEN
            WHERE JOURNAL_ID = %s AND QUELLE = 5
              AND STORNO = 0 AND GEBUCHT = 'Y'""",
        (rec_id,)
    )
    r = cur.fetchone() or {}
    return float(r.get('s_betrag') or 0), float(r.get('s_skonto') or 0)


def _stadium_aus_zahlungen(cur, rec_id: int,
                            bsumme: float) -> int | None:
    """Berechnet den passenden ``JOURNAL.STADIUM`` aus dem
    Zahlungs-Bestand. None bedeutet "keine Aenderung".

    Logik (alle Werte als Absolut-Betraege):
        keine aktive Zahlung           → STADIUM=2 (offen)
        |Betrag|+|Skonto| >= BSUMME-1ct, Skonto>0 → 8 (bezahlt mit Skonto)
        |Betrag|+|Skonto| >= BSUMME-1ct           → 9 (bezahlt)
        sonst (Teilzahlung)                       → 7 (Teilzahlung)
    """
    s_betrag, s_skonto = _zahlungssumme_und_skonto(cur, rec_id)
    if s_betrag + s_skonto <= 0.0001:
        return 2
    # 1 Cent Toleranz; ABS(bsumme) fuer Gutschriften (BSUMME<0)
    soll = abs(float(bsumme))
    if s_betrag + s_skonto >= soll - 0.01:
        return 8 if s_skonto > 0.0001 else 9
    return 7


def _journal_op_rebuild_qu5(cur) -> None:
    """Baut die JOURNAL_OP-Hilfstabelle fuer QUELLE=5 (EK-Rechnungen)
    komplett neu. Folgt dem CAO-Faktura-Pattern (siehe SQL-Trace
    2026-05-10): zwei INSERTs, einer fuer BSUMME>0 (normale Rechnungen)
    und einer fuer BSUMME<0 (Stornorechnungen mit umgedrehtem
    Vorzeichen).

    Wird nach jedem ZAHLUNGEN-INSERT/UPDATE aufgerufen, damit die
    "offene Posten"-Liste in CAO-UI aktuell ist.
    """
    cur.execute("DELETE FROM JOURNAL_OP WHERE QUELLE = 5")
    cur.execute(
        """INSERT INTO JOURNAL_OP
           SELECT J.QUELLE, J.ADDR_ID, J.REC_ID,
                  J.BSUMME * -1 AS BSUMME_NEG,
                  COUNT(ZA.REC_ID),
                  IFNULL(SUM(ZA.BETRAG + ZA.SKONTO_BETRAG), 0),
                  J.WAEHRUNG
             FROM JOURNAL J
        LEFT JOIN ZAHLUNGEN ZA ON ZA.JOURNAL_ID = J.REC_ID
                              AND ZA.GEBUCHT != 'S' AND ZA.STORNO = 0
            WHERE J.QUELLE = 5 AND J.BSUMME > 0 AND J.ADDR_ID > 0
              AND YEAR(J.RDATUM) > 2000
              AND J.STADIUM IN (2, 3, 4, 5, 6, 7, 11)
            GROUP BY J.REC_ID
           HAVING IFNULL(SUM(ZA.BETRAG + ZA.SKONTO_BETRAG), 0) > BSUMME_NEG"""
    )
    cur.execute(
        """INSERT INTO JOURNAL_OP
           SELECT J.QUELLE, J.ADDR_ID, J.REC_ID,
                  J.BSUMME * -1 AS BSUMME_NEG,
                  COUNT(ZA.REC_ID),
                  IFNULL(SUM(ZA.BETRAG + ZA.SKONTO_BETRAG), 0),
                  J.WAEHRUNG
             FROM JOURNAL J
        LEFT JOIN ZAHLUNGEN ZA ON ZA.JOURNAL_ID = J.REC_ID
                              AND ZA.GEBUCHT != 'S' AND ZA.STORNO = 0
            WHERE J.QUELLE = 5 AND J.BSUMME < 0 AND J.ADDR_ID > 0
              AND YEAR(J.RDATUM) > 2000
              AND J.STADIUM IN (2, 3, 4, 5, 6, 7, 11)
            GROUP BY J.REC_ID
           HAVING IFNULL(SUM(ZA.BETRAG + ZA.SKONTO_BETRAG), 0) < BSUMME_NEG"""
    )


def _stadium_neuberechnen(cur, rec_id: int) -> int | None:
    """Liest den Header, berechnet das STADIUM aus den Zahlungen und
    schreibt es zurueck (nur wenn nicht storniert/gemahnt)."""
    cur.execute(
        "SELECT BSUMME, STADIUM FROM JOURNAL "
        "WHERE REC_ID=%s AND QUELLE=5",
        (rec_id,)
    )
    row = cur.fetchone()
    if not row:
        return None
    alt = int(row.get('STADIUM') or 0)
    # Stornierte/Mahn-Stadien nicht ueberschreiben
    if alt in (3, 4, 5, 6, 11, 125, 126, 127):
        return alt
    bsumme = float(row.get('BSUMME') or 0)
    neu = _stadium_aus_zahlungen(cur, rec_id, bsumme)
    if neu is not None and neu != alt:
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=%s WHERE REC_ID=%s",
            (neu, rec_id)
        )
    return neu if neu is not None else alt


def einkauf_zahlung_erfassen(rec_id: int, *,
                               betrag: float,
                               datum: date | str | None = None,
                               valuta: date | str | None = None,
                               zahlart_id: int | None = None,
                               zahlart_name: str = '',
                               skonto_proz: float = 0.0,
                               skonto_betrag: float = 0.0,
                               fibu_kto: int | None = None,
                               belegnum: str = '',
                               verw_zweck: str = '',
                               ma_id: int | None = None,
                               ma_name: str = '') -> dict[str, Any]:
    """Erfasst eine EK-Zahlung manuell (CAO-Mimik, Trace 2026-05-10).

    Wichtige Konventionen:
      - BETRAG/SKONTO_BETRAG werden NEGATIV gespeichert (EK = Geld-
        Ausgang). User uebergibt positive Betraege, wir flippen das
        Vorzeichen.
      - WAEHRUNG = '€' (varchar(3), nicht 'EUR').
      - FIBU_KTO = User-Wahl (Bank-/Kasse-Konto aus
        ZAHLUNGSARTEN.FIBU_KONTEN). Bei nur einem Kandidaten nehmen
        wir automatisch den.
      - FIBU_GEGENKTO = JOURNAL.GEGENKONTO (= Lieferanten-/Kreditor-
        Konto aus dem JOURNAL-Header).
      - JOURNAL.BEZAHLT_KASSE='N' wird gesetzt (CAO-Marker).
      - KA_ID=-2 (laut Trace).
      - ART='?', UW_NUM=-1 (= XT-eigene Erfassung, kein SEPA-Lauf).

    Nach dem Insert:
      - STADIUM-Update ueber _stadium_neuberechnen
      - JOURNAL_OP-Rebuild fuer QUELLE=5 (CAO-Sync)
    """
    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:50]
    if betrag is None or abs(float(betrag)) < 0.005:
        raise ValueError('Betrag darf nicht 0 sein')
    # CAO-Konvention: BETRAG hat das UMGEKEHRTE Vorzeichen von BSUMME.
    # - Normale EK-Rechnung (BSUMME>0): User gibt +480 ein → BETRAG=-480
    # - Gutschrift     (BSUMME<0): User gibt -3,41 ein → BETRAG=+3,41
    # Wir flippen also einfach das Vorzeichen — der User uebergibt den
    # Wert mit demselben Vorzeichen wie BSUMME.
    betrag = round(float(betrag), 2)
    skonto_proz = round(float(skonto_proz or 0), 3)
    skonto_betrag = round(float(skonto_betrag or 0), 2)
    betrag_neg = -betrag
    skonto_neg = -skonto_betrag

    def _parse_date(d):
        if d is None or d == '':
            return None
        if isinstance(d, date):
            return d
        try:
            return date.fromisoformat(str(d)[:10])
        except (ValueError, TypeError):
            return None
    datum_d  = _parse_date(datum) or date.today()
    valuta_d = _parse_date(valuta) or datum_d

    with get_db_transaction() as cur:
        cur.execute(
            "SELECT j.QUELLE, j.STADIUM, j.BSUMME, j.ADDR_ID, "
            "       j.GEGENKONTO, j.VRENUM, "
            "       COALESCE(a.NAME1, j.KUN_NAME1, '') AS lief_name "
            "  FROM JOURNAL j "
            "  LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID "
            " WHERE j.REC_ID=%s",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            raise LookupError(f'Beleg {rec_id} nicht gefunden')
        if int(kopf.get('QUELLE') or 0) != 5:
            raise PermissionError(
                f"QUELLE={kopf.get('QUELLE')} — kein gebuchter Einkauf"
            )
        st = int(kopf.get('STADIUM') or 0)
        if st in (8, 9):
            raise PermissionError(
                'Beleg ist bereits voll bezahlt — keine weitere '
                'Zahlung erfassbar'
            )
        if st == 11:
            raise PermissionError(
                'Beleg ist angewiesen (Überweisung läuft) — '
                'keine zusätzliche Zahlung möglich'
            )
        if st in (125, 126, 127):
            raise PermissionError('Beleg ist storniert')

        addr_id = int(kopf.get('ADDR_ID') or -1)
        fibu_gegenkto = int(kopf.get('GEGENKONTO') or 0)

        # CAO-Defaults uebernehmen (Trace 2026-05-10):
        # BELEGNUM   = JOURNAL.VRENUM (z.B. '253430')
        # VERW_ZWECK = 'ZA EK-RE <Lieferantenname>'
        # Beide werden nur gesetzt, wenn der Aufrufer keine eigenen
        # Werte uebergibt — der UI-User kann also ueberschreiben.
        if not belegnum:
            belegnum = (kopf.get('VRENUM') or '').strip()
        if not verw_zweck:
            lief_name = (kopf.get('lief_name') or '').strip()
            if lief_name:
                verw_zweck = f'ZA EK-RE {lief_name}'

        # Zahlart-Name + FIBU_KTO-Default aus ZAHLUNGSARTEN.FIBU_KONTEN
        if zahlart_id is not None:
            cur.execute(
                "SELECT NAME, FIBU_KONTEN FROM ZAHLUNGSARTEN "
                "WHERE REC_ID=%s",
                (int(zahlart_id),)
            )
            row = cur.fetchone()
            if row:
                if not zahlart_name:
                    zahlart_name = (row.get('NAME') or '')[:100]
                if fibu_kto is None:
                    konten_liste = [int(t.strip())
                                     for t in (row.get('FIBU_KONTEN') or '').split(',')
                                     if t.strip().isdigit()]
                    # Bei genau einem Konto automatisch nehmen (z.B. Bar→1000)
                    if len(konten_liste) == 1:
                        fibu_kto = konten_liste[0]

        # JOURNAL: STADIUM vorab + BEZAHLT_KASSE='N' (CAO-Trace-Mimik)
        # Wir berechnen das STADIUM-Vorhersagewert, Header dann updaten.
        bsumme = float(kopf.get('BSUMME') or 0)
        # Pruefen ob die neue Zahlung den Beleg voll bezahlt.
        # Mit ABS-Logik damit Gutschriften (BSUMME<0) sauber funktionieren.
        cur.execute(
            "SELECT COALESCE(SUM(ABS(BETRAG))+SUM(ABS(SKONTO_BETRAG)),0) AS s "
            "  FROM ZAHLUNGEN "
            " WHERE JOURNAL_ID=%s AND QUELLE=5 AND STORNO=0 AND GEBUCHT='Y'",
            (rec_id,)
        )
        s_alt = float((cur.fetchone() or {}).get('s') or 0)
        s_neu = s_alt + abs(betrag) + abs(skonto_betrag)
        if s_neu >= abs(bsumme) - 0.01:
            neues_stadium = 8 if abs(skonto_betrag) > 0.0001 else 9
        else:
            neues_stadium = 7
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=%s, BEZAHLT_KASSE='N' "
            "WHERE REC_ID=%s",
            (neues_stadium, rec_id)
        )

        cur.execute(
            """INSERT INTO ZAHLUNGEN
               (FIBU_KTO, FIBU_GEGENKTO, MA_ID, ADDR_ID,
                QUELLE, JOURNAL_ID, KASSEN_ID, KA_ID,
                ZAHLART, ART, AUSZUG, UW_NUM,
                DATUM, VALUTA, BELEGNUM,
                BETRAG, SKONTO_PROZ, SKONTO_BETRAG, WAEHRUNG,
                TEXTSCHLUESSEL, VERW_ZWECK,
                GEBUCHT, STORNO,
                LFD_NUMMMER,
                ERSTELLT_AM, ERSTELLT_NAME,
                ZAHLART_NAME, SIG_AUSGEFALLEN, Z_ID, BEREINIGT,
                REFERENZ_ID, SUB_QUELLE, MWST)
               VALUES (%s, %s, %s, %s,
                       5, %s, -1, -2,
                       %s, '?', 0, -1,
                       %s, %s, %s,
                       %s, %s, %s, '€',
                       0, %s,
                       'Y', 0,
                       -1,
                       NOW(), %s,
                       %s, 'N', -1, 'N',
                       -1, -1, 0)""",
            (
                int(fibu_kto or 0), fibu_gegenkto,
                int(ma_id or 0), addr_id,
                rec_id,
                int(zahlart_id) if zahlart_id is not None else -1,
                datum_d, valuta_d, belegnum[:100],
                betrag_neg, skonto_proz, skonto_neg,
                verw_zweck[:1000],
                ma_name_safe,
                zahlart_name[:100],
            )
        )
        new_id = int(cur.lastrowid)

        # JOURNAL_OP rebuild (CAO-Mimik nach jedem Schreiben)
        _journal_op_rebuild_qu5(cur)

    return {'ok': True, 'rec_id': new_id, 'stadium': neues_stadium}


# ── Phase E.2: SEPA-Überweisung via Hibiscus vormerken ───────────


def _verwendungszweck_ek(vrenum: str, orgnum: str,
                          lief_name: str) -> str:
    """Baut den SEPA-Verwendungszweck einer EK-Rechnung.

    Bevorzugt die externe Rechnungs-Nr (ORGNUM, das was der Lieferant
    auf SEINER Rechnung schreibt — danach sucht er beim Abgleich),
    sonst die interne VRENUM. Plus Lieferantenname, hart auf 140
    Zeichen (SEPA-Limit) gekürzt.
    """
    ref = (orgnum or '').strip() or (vrenum or '').strip()
    name = (lief_name or '').strip()
    teile = ['Rechnung', ref] if ref else ['Rechnung']
    if name:
        teile.append(name)
    return ' '.join(teile)[:140]


# Generische Verknüpfung Dorfkern-Vorgang ↔ Hibiscus-SEPA-Auftrag.
# Bewusst modulübergreifend (MODUL/REFERENZ_ID), damit später auch
# Lohn/VK/… andocken können, OHNE dass JOURNAL.STADIUM die Wahrheit
# trägt. Diese Tabelle IST zugleich die Sicherheitsgrenze des
# (späteren) E.3-Reconcilers: er fasst NUR Aufträge an, die hier
# stehen — manuell in Jameica erfasste SEPA-Aufträge bleiben unberührt.
def _hibiscus_vormerkung_schema() -> None:
    """Legt ``XT_HIBISCUS_VORMERKUNG`` an. Idempotent."""
    with get_db() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS XT_HIBISCUS_VORMERKUNG (
              REC_ID               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              MODUL                VARCHAR(32)   NOT NULL,
              REFERENZ_ID          BIGINT        NOT NULL,
              RICHTUNG             CHAR(1)       NOT NULL DEFAULT 'A',
              HIBISCUS_AUFTRAG_ID  VARCHAR(64)   NULL,
              ENDTOENDID           VARCHAR(35)   NOT NULL,
              IBAN                 VARCHAR(34)   NULL,
              BIC                  VARCHAR(11)   NULL,
              EMPFAENGER           VARCHAR(140)  NULL,
              BETRAG               DECIMAL(13,2) NOT NULL,
              STATUS               ENUM('vorgemerkt','bezahlt',
                                        'zurueckgesetzt','fehler')
                                     NOT NULL DEFAULT 'vorgemerkt',
              ANGELEGT_AM          DATETIME      NOT NULL
                                     DEFAULT CURRENT_TIMESTAMP,
              ANGELEGT_VON         VARCHAR(50)   NULL,
              AKTUALISIERT_AM      DATETIME      NOT NULL
                                     DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
              NOTIZ                VARCHAR(255)  NULL,
              UNIQUE KEY uq_endtoendid (ENDTOENDID),
              KEY idx_modul_ref (MODUL, REFERENZ_ID),
              KEY idx_status (STATUS),
              KEY idx_auftrag (HIBISCUS_AUFTRAG_ID)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='Dorfkern-Hibiscus SEPA-Vormerkungen generisch (E.2/E.3)'
        """)


# Modul → Kurzpräfix für die EndToEndId (SEPA: ≤35 Zeichen,
# Zeichensatz hier bewusst auf [A-Z0-9-] beschränkt — manche Banken
# filtern Sonderzeichen).
_MODUL_KUERZEL = {'einkauf': 'EK'}


def _dorfkern_endtoendid(modul: str, referenz_id: int) -> str:
    """Dorfkern-genamespacte, eindeutige SEPA-EndToEndId.

    Schema ``DK-<KUERZEL><REF>-<RAND6>`` (≤35). Dient als
    deterministischer Korrelationsschlüssel für den späteren
    Bankumsatz-Abgleich (camt.05x trägt die EndToEndId zurück) und
    ist durch das ``DK-``-Präfix automatisch von Fremd-/Manuell-
    Aufträgen abgegrenzt.
    """
    import secrets
    kuerzel = _MODUL_KUERZEL.get(modul, modul[:4].upper() or 'XX')
    rand = secrets.token_hex(3).upper()          # 6 Hex-Zeichen
    return f"DK-{kuerzel}{int(referenz_id)}-{rand}"[:35]


# ZAHLART-Gate: nur Belege mit Zahlart „Überweisung Bank" dürfen
# vorgemerkt werden. WICHTIG (Praxis-Fehlerfall): bei Lastschrift
# zieht die Bank selbst ein — eine zusätzliche Überweisung wäre eine
# Doppelzahlung. ZAHLUNGSARTEN live verifiziert: id 2 = „Überweisung
# Bank", id 9 = „Lastschrift". ID NICHT hartkodiert → konfigurierbar,
# Default = 2.
def _ek_zahlart_ueberweisung_id() -> int:
    from common import konfig
    try:
        v = konfig.get('hibiscus.ek_zahlart_ueberweisung_id')
        return int(v) if v not in (None, '') else 2
    except (TypeError, ValueError):
        return 2


def vormerken_via_hibiscus(rec_id: int, *,
                            ma_id: int | None = None,
                            ma_name: str = '') -> dict[str, Any]:
    """Phase E.2: legt für eine offene EK-Rechnung eine SEPA-Über­
    weisung in Hibiscus an (Status „offen", **nicht** ausgeführt) und
    setzt ``JOURNAL.STADIUM=11`` (angewiesen).

    Bewusst getrennt: das **Signieren/Senden** (S-pushTAN) macht der
    Mensch in der Jameica-GUI — headless kann Jameica nicht signieren
    (TANDialog ist SWT-GUI-gebunden, siehe
    project_zahlungsmanagement_hibiscus). Hier wird der Auftrag nur in
    die Hibiscus-Warteschlange gelegt.

    Idempotenz (MyISAM, kein Rollback): ``STADIUM=11`` ist „sticky"
    UND es darf keine aktive ``XT_HIBISCUS_VORMERKUNG``-Zeile
    (STATUS='vorgemerkt') für den Beleg geben — sonst
    :class:`PermissionError` (keine Doppel-Überweisung). Es wird
    **keine** ``ZAHLUNGEN``-Zeile geschrieben (das passiert erst beim
    späteren Bank-Umsatz-Abgleich, Phase E.3). Persistiert die von
    Hibiscus zurückgegebene Auftrags-ID + eine Dorfkern-eigene
    EndToEndId in ``XT_HIBISCUS_VORMERKUNG`` (generisch, = Scoping-
    Grenze + Korrelationsschlüssel für den E.3-Reconciler).
    """
    from common import konfig
    from common.hibiscus_client import aus_konfig, HibiscusError

    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:50]
    _hibiscus_vormerkung_schema()

    with get_db() as cur:
        cur.execute(
            """SELECT j.QUELLE, j.STADIUM, j.BSUMME, j.VRENUM, j.ORGNUM,
                      j.ZAHLART,
                      COALESCE(a.NAME1, j.KUN_NAME1, '') AS lief_name,
                      COALESCE(a.IBAN, '')  AS lief_iban,
                      COALESCE(a.SWIFT, '') AS lief_bic
                 FROM JOURNAL j
            LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
                WHERE j.REC_ID = %s""",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            raise LookupError(f'Beleg {rec_id} nicht gefunden')
        if int(kopf.get('QUELLE') or 0) != 5:
            raise PermissionError(
                f"QUELLE={kopf.get('QUELLE')} — kein gebuchter Einkauf")
        # ZAHLART-Gate (Server-seitig, Defense-in-Depth gegen direkte
        # Route-Aufrufe / Lastschrift-Doppelzahlung).
        zahlart_soll = _ek_zahlart_ueberweisung_id()
        if int(kopf.get('ZAHLART') or -1) != zahlart_soll:
            raise PermissionError(
                'Zahlart ist nicht „Überweisung Bank" — keine '
                'Vormerkung (bei Lastschrift zieht die Bank selbst '
                'ein; eine Überweisung wäre eine Doppelzahlung).')
        st = int(kopf.get('STADIUM') or 0)
        if st == 11:
            raise PermissionError(
                'Beleg ist bereits vorgemerkt (angewiesen) — eine '
                'erneute Überweisung würde doppelt zahlen. In der '
                'Jameica-GUI senden bzw. den Auftrag dort löschen.')
        if st in (8, 9):
            raise PermissionError('Beleg ist bereits voll bezahlt')
        if st in (125, 126, 127):
            raise PermissionError('Beleg ist storniert')

        # Generischer Doppel-Schutz (unabhängig von STADIUM, damit der
        # Pfad auch für künftige Nicht-Einkauf-Module korrekt ist):
        # keine zweite Vormerkung solange eine aktive existiert.
        cur.execute(
            "SELECT REC_ID FROM XT_HIBISCUS_VORMERKUNG "
            "WHERE MODUL='einkauf' AND REFERENZ_ID=%s "
            "  AND STATUS='vorgemerkt' LIMIT 1",
            (rec_id,)
        )
        if cur.fetchone():
            raise PermissionError(
                'Für diesen Beleg existiert bereits eine aktive '
                'Hibiscus-Vormerkung. In der Jameica-GUI senden bzw. '
                'den Auftrag dort löschen.')

        bsumme = float(kopf.get('BSUMME') or 0)
        s_betrag, s_skonto = _zahlungssumme_und_skonto(cur, rec_id)
        offen = round(abs(bsumme) - s_betrag - s_skonto, 2)
        if offen <= 0.01:
            raise PermissionError(
                'Kein offener Betrag — nichts vorzumerken')

        lief_name = (kopf.get('lief_name') or '').strip()
        lief_iban = (kopf.get('lief_iban') or '').replace(' ', '').upper()
        lief_bic  = (kopf.get('lief_bic') or '').strip().upper()
        vrenum    = (kopf.get('VRENUM') or '').strip()
        orgnum    = (kopf.get('ORGNUM') or '').strip()
        if not lief_iban:
            raise ValueError(
                'Lieferant hat keine IBAN hinterlegt (ADRESSEN.IBAN) — '
                'Überweisung nicht möglich. IBAN in den Stammdaten '
                'ergänzen.')

    # Belastungskonto: Hibiscus-Konto-ID NICHT hartkodieren — aus der
    # Konfiguration. Wenn nicht gesetzt → klare, handlungsweisende
    # Fehlermeldung (Admin muss das einmalig festlegen).
    debit_raw = konfig.get('hibiscus.debit_konto_id')
    try:
        debit_konto_id = int(debit_raw) if debit_raw not in (None, '') else 0
    except (TypeError, ValueError):
        debit_konto_id = 0
    if debit_konto_id <= 0:
        raise ValueError(
            'Kein Belastungskonto konfiguriert. In Admin → System → '
            'Banking das Hibiscus-Konto für Überweisungen festlegen '
            "(DORFKERN_KONFIG 'hibiscus.debit_konto_id').")

    zweck = _verwendungszweck_ek(vrenum, orgnum, lief_name)
    endtoendid = _dorfkern_endtoendid('einkauf', rec_id)

    try:
        client = aus_konfig()
        hibiscus_id = client.sepa_ueberweisung_anlegen(
            debit_konto_id=debit_konto_id,
            iban=lief_iban, bic=lief_bic,
            name=lief_name or 'Lieferant',
            betrag=offen, zweck=zweck,
            endtoendid=endtoendid)
    except HibiscusError as e:
        raise RuntimeError(f'Hibiscus: {e}') from e

    # SEPA-Auftrag liegt jetzt in Hibiscus. Verknüpfung persistieren
    # (Scoping-Grenze + Korrelationsschlüssel), dann STADIUM=11 —
    # idempotent (nur 2→11, nie 11 überschreiben). Keine ZAHLUNGEN-
    # Zeile (kommt erst beim Bank-Umsatz-Abgleich, Phase E.3).
    with get_db_transaction() as cur:
        cur.execute(
            """INSERT INTO XT_HIBISCUS_VORMERKUNG
                 (MODUL, REFERENZ_ID, RICHTUNG, HIBISCUS_AUFTRAG_ID,
                  ENDTOENDID, IBAN, BIC, EMPFAENGER, BETRAG,
                  STATUS, ANGELEGT_VON)
               VALUES ('einkauf', %s, 'A', %s,
                       %s, %s, %s, %s, %s,
                       'vorgemerkt', %s)""",
            (rec_id, str(hibiscus_id)[:64], endtoendid,
             lief_iban[:34], lief_bic[:11],
             (lief_name or 'Lieferant')[:140], offen, ma_name_safe)
        )
        vormerkung_id = int(cur.lastrowid)
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=11 "
            "WHERE REC_ID=%s AND QUELLE=5 AND STADIUM<>11",
            (rec_id,)
        )
        _journal_op_rebuild_qu5(cur)

    logging.getLogger(__name__).info(
        'EK-Beleg %s via Hibiscus vorgemerkt (Auftrag %s, E2E %s, '
        '%.2f €, %s)', rec_id, hibiscus_id, endtoendid, offen,
        ma_name_safe)
    return {
        'ok': True,
        'rec_id': rec_id,
        'vormerkung_id': vormerkung_id,
        'hibiscus_id': str(hibiscus_id),
        'endtoendid': endtoendid,
        'betrag': offen,
        'stadium': 11,
        'hinweis': 'In Hibiscus vorgemerkt. Senden mit S-pushTAN '
                   'erfolgt manuell in der Jameica-GUI.',
    }


def vormerkung_zuruecknehmen(rec_id: int, *,
                              ma_id: int | None = None,
                              ma_name: str = '') -> dict[str, Any]:
    """Nimmt eine aktive SEPA-Vormerkung zurück: löscht den (noch
    nicht gesendeten) Auftrag in Hibiscus, setzt
    ``XT_HIBISCUS_VORMERKUNG.STATUS='zurueckgesetzt'`` und
    ``JOURNAL.STADIUM 11→2``.

    Sicherheitsklappe bis zum E.3-Reconciler. **Nur** anbieten/
    aufrufen, solange in Jameica noch nicht freigegeben/gesendet —
    das kann headless nicht zuverlässig erkannt werden, daher: keine
    verbuchte UB-Zahlung als Vorbedingung + UI-Warnung. Idempotent
    (kein aktiver Eintrag → LookupError).
    """
    from common.hibiscus_client import aus_konfig, HibiscusError

    rec_id = int(rec_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:50]
    _hibiscus_vormerkung_schema()

    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, HIBISCUS_AUFTRAG_ID, BETRAG "
            "  FROM XT_HIBISCUS_VORMERKUNG "
            " WHERE MODUL='einkauf' AND REFERENZ_ID=%s "
            "   AND STATUS='vorgemerkt' "
            " ORDER BY REC_ID DESC LIMIT 1",
            (rec_id,)
        )
        vm = cur.fetchone()
        if not vm:
            raise LookupError(
                'Keine aktive Vormerkung zu diesem Beleg.')
        # Bereits eine aktive (gebuchte, nicht stornierte) UB-Zahlung?
        # Dann ist Geld geflossen → NICHT zurücksetzen.
        cur.execute(
            "SELECT COUNT(*) AS n FROM ZAHLUNGEN "
            " WHERE JOURNAL_ID=%s AND QUELLE=5 AND ART='UB' "
            "   AND STORNO=0 AND GEBUCHT='Y'",
            (rec_id,)
        )
        if int((cur.fetchone() or {}).get('n') or 0) > 0:
            raise PermissionError(
                'Es ist bereits eine Bank-Zahlung verbucht — '
                'Vormerkung kann nicht zurückgenommen werden.')

    auftrag_id = (vm.get('HIBISCUS_AUFTRAG_ID') or '').strip()
    hibiscus_geloescht = False
    loesch_hinweis = ''
    if auftrag_id:
        try:
            aus_konfig().sepa_ueberweisung_loeschen(auftrag_id)
            hibiscus_geloescht = True
        except HibiscusError as e:
            # Auftrag evtl. schon weg/gesendet — Reset trotzdem
            # zulassen, aber transparent vermerken.
            loesch_hinweis = (f'Hibiscus-Auftrag {auftrag_id} nicht '
                              f'gelöscht ({e}). Bitte in Jameica '
                              f'prüfen.')
            logging.getLogger(__name__).warning(
                'Vormerkung %s: Hibiscus-delete fehlgeschlagen: %s',
                rec_id, e)

    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_HIBISCUS_VORMERKUNG "
            "   SET STATUS='zurueckgesetzt', "
            "       NOTIZ=CONCAT_WS(' | ', NOTIZ, %s) "
            " WHERE REC_ID=%s AND STATUS='vorgemerkt'",
            (f'zurückgenommen von {ma_name_safe}'
             + (f'; {loesch_hinweis}' if loesch_hinweis else ''),
             int(vm['REC_ID']))
        )
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=2 "
            " WHERE REC_ID=%s AND QUELLE=5 AND STADIUM=11",
            (rec_id,)
        )
        _journal_op_rebuild_qu5(cur)

    logging.getLogger(__name__).info(
        'Vormerkung Beleg %s zurückgenommen (Auftrag %s, Hibiscus-'
        'delete=%s, %s)', rec_id, auftrag_id or '–',
        hibiscus_geloescht, ma_name_safe)
    return {
        'ok': True,
        'rec_id': rec_id,
        'stadium': 2,
        'hibiscus_geloescht': hibiscus_geloescht,
        'hinweis': loesch_hinweis or
                   'Vormerkung zurückgenommen, Auftrag in Hibiscus '
                   'gelöscht.',
    }


# ── Phase E.3: Auto-Match Bankumsatz ↔ EK-Zahlung ────────────────


def _fibu_kto_zu_hibiscus_konto(cur, fibu_kto: int) -> int | None:
    """Mappt FIBU_KONTEN.KONTO (z.B. 1210) auf hibiscus.konto.id (z.B. 48)
    via IBAN-Gleichheit. None wenn nicht zuordenbar (Kasse, Schecks)."""
    if not fibu_kto or fibu_kto < 1:
        return None
    cur.execute(
        """SELECT k.id
             FROM FIBU_KONTEN fk
             JOIN konto k ON k.iban = fk.IBAN AND k.iban != ''
            WHERE fk.KONTORAHMEN = (
                  SELECT IFNULL(VAL_CHAR, 'SKR03') FROM REGISTRY
                   WHERE MAINKEY=%s AND NAME='KONTORAHMEN' LIMIT 1)
              AND fk.KONTO = %s
            LIMIT 1""",
        ('MAIN\\BELEGE', int(fibu_kto))
    )
    row = cur.fetchone()
    return int(row['id']) if row else None


def _name_token_match(adress_name: str, empf_name: str) -> bool:
    """True wenn ein "wichtiges" Wort des Lieferanten-Namens im
    Bankumsatz-Empfaenger vorkommt. Wir nehmen den ersten Token mit
    >= 4 Zeichen, der nicht in der Stoppwort-Liste steht.
    """
    stop = {'gmbh', 'ag', 'kg', 'ohg', 'co', 'mbh', 'haftungsbeschr',
             'lebensmittel', 'gruppe', 'group', 'firma', 'company'}
    a = (adress_name or '').lower()
    e = (empf_name or '').lower()
    if not a or not e:
        return False
    import re
    tokens = re.findall(r'[a-zA-ZäöüÄÖÜß]{4,}', a)
    relevant = [t for t in tokens if t.lower() not in stop]
    if not relevant:
        relevant = tokens   # Fallback wenn alles Stoppwort
    return any(t.lower() in e for t in relevant)


def _orgnum_im_zweck(orgnum: str, zweck: str) -> bool:
    """True wenn die externe Rechnungs-Nr (ORGNUM) in irgendeiner Form
    im Verwendungszweck auftaucht.

    ORGNUM-Formate variieren stark:
        UTZ:    "VR26-020729"   → Numerik-Kern "020729"
        Trunk:  "2026/661439"   → "661439"
        Schmid: "728261"        → "728261"
        Andere: "RE 12345"      → "12345"

    Wir extrahieren alle numerischen Sequenzen >= 5 Ziffern aus ORGNUM
    und suchen sie wortweise im Zweck. Mind. eine Sequenz muss matchen.
    """
    if not orgnum or not zweck:
        return False
    import re
    sequenzen = re.findall(r'\d{5,}', orgnum)
    if not sequenzen:
        return False
    z = zweck or ''
    return any(s in z for s in sequenzen)


def bankumsatz_kandidaten_fuer_einkauf(rec_id: int) -> list[dict[str, Any]]:
    """Sucht moegliche Hibiscus-Bankumsaetze fuer eine offene EK-Rechnung.

    Match-Score (capped bei 100):
      - empfaenger_konto = ADRESSEN.IBAN          → +50
      - ORGNUM (extern. Rechnungs-Nr) im zweck    → +30  (sehr eindeutig
                                                          bei Lastschrift)
      - |umsatz.betrag| = offener_Betrag (±1ct)   → +30  (Pflicht-Filter)
      - empfaenger_name enthaelt Lieferantenname  → +10
      - umsatz.datum innerhalb RDATUM ±60 Tage    → +10

    Liefert sortierte Liste von Kandidaten ab Score>=50, max 5.
    """
    rec_id = int(rec_id)
    with get_db() as cur:
        # Beleg-Header + Lieferanten-Daten
        cur.execute(
            """SELECT j.REC_ID, j.QUELLE, j.STADIUM, j.RDATUM, j.BSUMME,
                      j.ADDR_ID, j.VRENUM, j.ORGNUM, j.STADIUM,
                      a.NAME1 AS lief_name, a.IBAN AS lief_iban
                 FROM JOURNAL j
            LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
                WHERE j.REC_ID = %s""",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            return []
        if int(kopf.get('QUELLE') or 0) != 5:
            return []
        st = int(kopf.get('STADIUM') or 0)
        if st not in (2, 7, 11):
            return []   # nur offene/Teil/angewiesen
        bsumme = float(kopf.get('BSUMME') or 0)
        rdatum = kopf.get('RDATUM')
        lief_name = (kopf.get('lief_name') or '').strip()
        lief_iban = (kopf.get('lief_iban') or '').strip()
        orgnum    = (kopf.get('ORGNUM') or '').strip()

        # Offener Betrag = BSUMME minus aktive Zahlungen
        cur.execute(
            "SELECT COALESCE(SUM(ABS(BETRAG))+SUM(ABS(SKONTO_BETRAG)),0) AS s "
            "  FROM ZAHLUNGEN "
            " WHERE JOURNAL_ID=%s AND QUELLE=5 AND STORNO=0 AND GEBUCHT='Y'",
            (rec_id,)
        )
        s_aktiv = float((cur.fetchone() or {}).get('s') or 0)
        offen = abs(bsumme) - s_aktiv
        if offen <= 0.01:
            return []   # eigentlich voll bezahlt — kein Kandidat noetig

        # Bereits verlinkte umsatz-IDs (UW_NUM > 0 bei ART='UB' = SEPA aus Banking)
        cur.execute(
            "SELECT DISTINCT UW_NUM FROM ZAHLUNGEN "
            " WHERE QUELLE=5 AND ART='UB' AND UW_NUM > 0"
        )
        verbraucht = {int(r['UW_NUM']) for r in cur.fetchall() or []
                       if r.get('UW_NUM')}

        if not rdatum:
            return []
        rd = rdatum.date() if hasattr(rdatum, 'date') else rdatum
        from datetime import timedelta
        von = rd - timedelta(days=60)
        bis = rd + timedelta(days=60)

        # Kandidaten suchen: gleicher Betrag (±1ct), gleiches Datums-Fenster
        # — gefiltert nach Konten, deren IBAN NICHT NULL ist (Hibiscus
        # hat dann Online-Zugang).
        cur.execute(
            """SELECT u.id AS umsatz_id, u.konto_id, u.datum, u.valuta,
                      u.betrag, u.empfaenger_name, u.empfaenger_konto,
                      u.zweck, u.zweck2, u.zweck3, u.art, u.umsatztyp_id,
                      k.bezeichnung AS konto_bez, k.iban AS konto_iban
                 FROM umsatz u
                 JOIN konto k ON k.id = u.konto_id
                WHERE u.datum BETWEEN %s AND %s
                  AND ABS(ABS(u.betrag) - %s) < 0.02
                ORDER BY u.datum DESC""",
            (von, bis, offen)
        )
        rohe = cur.fetchall()

    out: list[dict[str, Any]] = []
    for u in rohe:
        if int(u['umsatz_id']) in verbraucht:
            continue
        score = 0
        gruende: list[str] = []
        # Betrag (Pflicht — schon im SQL gefiltert, also immer +30)
        score += 30
        gruende.append('Betrag passt')
        # Datum +10 (auch schon im SQL — aber der Score zeigt es)
        score += 10
        # IBAN-Match
        empf_iban = (u.get('empfaenger_konto') or '').strip()
        if lief_iban and empf_iban and lief_iban == empf_iban:
            score += 50
            gruende.append('Lieferanten-IBAN exakt')
        # ORGNUM (externe Eingangsrechnungs-Nr) im zweck
        zweck_kombiniert = ((u.get('zweck') or '') + ' '
                            + (u.get('zweck2') or '') + ' '
                            + (u.get('zweck3') or ''))
        if orgnum and _orgnum_im_zweck(orgnum, zweck_kombiniert):
            score += 30
            gruende.append(f'Eingangsrechnung "{orgnum}" im Zweck')
        # Name-Token-Match
        if _name_token_match(lief_name, u.get('empfaenger_name') or ''):
            score += 10
            gruende.append('Name passt')
        # Cap bei 100
        if score > 100:
            score = 100
        if score < 50:
            continue
        out.append({
            'umsatz_id':       int(u['umsatz_id']),
            'konto_id':        int(u['konto_id']),
            'konto_bez':       u['konto_bez'],
            'konto_iban':      u['konto_iban'],
            'datum':           u['datum'],
            'valuta':          u['valuta'],
            'betrag':          float(u['betrag']),
            'empfaenger_name': u['empfaenger_name'] or '',
            'empfaenger_konto': u['empfaenger_konto'] or '',
            'zweck':           ((u['zweck'] or '') + ' '
                                + (u['zweck2'] or '') + ' '
                                + (u['zweck3'] or '')).strip(),
            'art':             u['art'] or '',
            'score':           score,
            'gruende':         gruende,
        })
    out.sort(key=lambda x: -x['score'])
    return out[:5]


def bankumsatz_uebernehmen(rec_id: int, umsatz_id: int, *,
                            ma_id: int | None = None,
                            ma_name: str = '') -> dict[str, Any]:
    """Uebernimmt einen Hibiscus-Bankumsatz als ZAHLUNGEN-Eintrag.

    - ZAHLUNGEN-Eintrag mit ART='UB' (Ueberweisung), UW_NUM=umsatz_id
    - Betrag/Datum aus dem Hibiscus-Umsatz (NICHT geflippt — der ist
      schon mit dem richtigen CAO-Vorzeichen, weil EK = Geld-Ausgang
      = umsatz.betrag negativ).
    - FIBU_KTO = das CAO-Konto, das zum Hibiscus-Konto gehoert
    - VERW_ZWECK = das ist der zweck aus Hibiscus
    - JOURNAL.STADIUM neu berechnen (analog manueller Erfassung)
    - JOURNAL_OP-Rebuild
    - Hibiscus-umsatz wird gleichzeitig als FLAG_GEPRUEFT markiert
      (Reconciliation-Spur).

    Returns: ``{ok, zahlung_id, stadium}``.
    """
    rec_id = int(rec_id)
    umsatz_id = int(umsatz_id)
    ma_name_safe = (ma_name or 'CAO-XT')[:50]

    with get_db_transaction() as cur:
        # Hibiscus-Umsatz lesen
        cur.execute(
            """SELECT u.id, u.konto_id, u.datum, u.valuta, u.betrag,
                      u.empfaenger_name, u.empfaenger_konto, u.empfaenger_blz,
                      u.zweck, u.zweck2, u.zweck3,
                      k.iban AS konto_iban, k.bezeichnung AS konto_bez
                 FROM umsatz u
                 JOIN konto k ON k.id = u.konto_id
                WHERE u.id = %s""",
            (umsatz_id,)
        )
        u = cur.fetchone()
        if not u:
            raise LookupError(f'Hibiscus-Umsatz {umsatz_id} nicht gefunden')

        # FIBU_KTO ermitteln (umgekehrtes Mapping zu _fibu_kto_zu_hibiscus_konto)
        cur.execute(
            r"""SELECT fk.KONTO FROM FIBU_KONTEN fk
                 WHERE fk.KONTORAHMEN = (
                       SELECT IFNULL(VAL_CHAR, 'SKR03') FROM REGISTRY
                        WHERE MAINKEY='MAIN\\BELEGE' AND NAME='KONTORAHMEN' LIMIT 1)
                   AND fk.IBAN = %s
                 LIMIT 1""",
            (u['konto_iban'],)
        )
        fk_row = cur.fetchone()
        fibu_kto = int(fk_row['KONTO']) if fk_row else 0

        # JOURNAL-Header
        cur.execute(
            "SELECT QUELLE, STADIUM, BSUMME, ADDR_ID, GEGENKONTO, VRENUM "
            "  FROM JOURNAL WHERE REC_ID=%s",
            (rec_id,)
        )
        kopf = cur.fetchone()
        if not kopf:
            raise LookupError(f'Beleg {rec_id} nicht gefunden')
        if int(kopf.get('QUELLE') or 0) != 5:
            raise PermissionError('Kein gebuchter EK-Beleg')
        st_alt = int(kopf.get('STADIUM') or 0)
        if st_alt in (8, 9, 125, 126, 127):
            raise PermissionError(
                f'Beleg STADIUM={st_alt} — Zahlung nicht uebernehmbar'
            )
        addr_id = int(kopf.get('ADDR_ID') or -1)
        fibu_gegenkto = int(kopf.get('GEGENKONTO') or 0)
        bsumme = float(kopf.get('BSUMME') or 0)

        # Vorzeichen & Beträge: Hibiscus-Betrag ist schon negativ bei EK
        # (Geld-Aus). Wir uebernehmen 1:1.
        u_betrag = float(u['betrag'] or 0)
        verw_zweck = ((u['zweck'] or '') + ' '
                       + (u['zweck2'] or '') + ' '
                       + (u['zweck3'] or '')).strip()[:1000]
        belegnum = (kopf.get('VRENUM') or '').strip()

        # Stadium-Vorhersage (mit ABS-Logik fuer Gutschriften)
        cur.execute(
            "SELECT COALESCE(SUM(ABS(BETRAG))+SUM(ABS(SKONTO_BETRAG)),0) AS s "
            "  FROM ZAHLUNGEN "
            " WHERE JOURNAL_ID=%s AND QUELLE=5 AND STORNO=0 AND GEBUCHT='Y'",
            (rec_id,)
        )
        s_alt = float((cur.fetchone() or {}).get('s') or 0)
        s_neu = s_alt + abs(u_betrag)
        if s_neu >= abs(bsumme) - 0.01:
            neues_stadium = 9
        else:
            neues_stadium = 7
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=%s, BEZAHLT_KASSE='N' "
            "WHERE REC_ID=%s",
            (neues_stadium, rec_id)
        )

        # ZAHLUNGEN-Insert: ART='UB' (= Ueberweisung aus Banking),
        # UW_NUM=umsatz_id (= Verlinkung)
        cur.execute(
            """INSERT INTO ZAHLUNGEN
               (FIBU_KTO, FIBU_GEGENKTO, MA_ID, ADDR_ID,
                QUELLE, JOURNAL_ID, KASSEN_ID, KA_ID,
                ZAHLART, ART, AUSZUG, UW_NUM,
                DATUM, VALUTA, BELEGNUM,
                BETRAG, SKONTO_PROZ, SKONTO_BETRAG, WAEHRUNG,
                TEXTSCHLUESSEL, VERW_ZWECK,
                GEBUCHT, STORNO, LFD_NUMMMER,
                ERSTELLT_AM, ERSTELLT_NAME,
                ZAHLART_NAME, SIG_AUSGEFALLEN, Z_ID, BEREINIGT,
                REFERENZ_ID, SUB_QUELLE, MWST)
               VALUES (%s, %s, %s, %s,
                       5, %s, -1, -2,
                       -1, 'UB', 0, %s,
                       %s, %s, %s,
                       %s, 0, 0, '€',
                       0, %s,
                       'Y', 0, -1,
                       NOW(), %s,
                       'Überweisung Bank', 'N', -1, 'N',
                       -1, -1, 0)""",
            (
                fibu_kto, fibu_gegenkto, int(ma_id or 0), addr_id,
                rec_id, umsatz_id,
                u['datum'], u['valuta'] or u['datum'], belegnum[:100],
                u_betrag,
                verw_zweck,
                ma_name_safe,
            )
        )
        new_zahlung_id = int(cur.lastrowid)

        # Hibiscus-Umsatz: FLAG_GEPRUEFT setzen + Notiz mit VRENUM-Bezug.
        # Notiz schreiben wir nur wenn noch leer (User-Notizen nicht
        # ueberschreiben). Format: "Dorfkern EK <vrenum>"
        kommentar_neu = f'Dorfkern EK {belegnum}' if belegnum else 'Dorfkern EK'
        cur.execute(
            "UPDATE umsatz "
            "SET flags = IFNULL(flags,0) | 1, "
            "    kommentar = CASE "
            "      WHEN kommentar IS NULL OR TRIM(kommentar) = '' THEN %s "
            "      WHEN kommentar LIKE %s THEN kommentar "
            "      ELSE CONCAT(kommentar, ' · ', %s) END "
            "WHERE id = %s",
            (kommentar_neu, f'%{kommentar_neu}%', kommentar_neu, umsatz_id)
        )

        # JOURNAL_OP rebuild
        _journal_op_rebuild_qu5(cur)

    return {'ok': True, 'zahlung_id': new_zahlung_id,
            'stadium': neues_stadium}


def einkauf_zahlung_stornieren(zahlung_rec_id: int, *,
                                 grund: str,
                                 ma_id: int | None = None,
                                 ma_name: str = '') -> dict[str, Any]:
    """Storniert eine Zahlung (XT-eigene, nicht aus CAO-SEPA-Lauf).

    Pre-Check: Zahlungen mit ``ART='UB'`` oder ``UW_NUM > 0`` stammen
    aus einem CAO-SEPA-Ueberweisungs-Lauf — die muss der User in CAO
    unter Finanzen/Ueberweisungen ruecknehmen, weil dort die FIBU-
    Konto-Auswirkung sauber rueckgaengig gemacht wird. PermissionError.

    Effekt: STORNO=1, GEBUCHT='S', STORNOGRUND, plus
    JOURNAL.STADIUM-Neuberechnung.
    """
    grund = (grund or '').strip()
    if not grund:
        raise ValueError('Storno-Grund ist Pflicht')
    if len(grund) > 250:
        grund = grund[:250]

    with get_db_transaction() as cur:
        cur.execute(
            """SELECT z.REC_ID, z.JOURNAL_ID, z.QUELLE, z.STORNO,
                      z.GEBUCHT, z.ART, z.UW_NUM, z.BETRAG
                 FROM ZAHLUNGEN z
                WHERE z.REC_ID = %s""",
            (int(zahlung_rec_id),)
        )
        z = cur.fetchone()
        if not z:
            raise LookupError(f'Zahlung {zahlung_rec_id} nicht gefunden')
        if int(z.get('STORNO') or 0) > 0 or (z.get('GEBUCHT') or '') == 'S':
            return {'ok': True, 'rec_id': int(zahlung_rec_id),
                    'idempotent': True}
        if _zahlung_aus_cao_sepa(z):
            raise PermissionError(
                'Diese Zahlung stammt aus einem CAO-SEPA-Überweisungs-'
                'Lauf (ART=UB / UW_NUM>0) — Storno bitte in CAO unter '
                'Finanzen / Überweisungen.'
            )
        # CAO-Mimik (Trace 2026-05-10): STORNO=1, STORNOGRUND, VERW_ZWECK
        # bekommt '\n--STORNO--'-Suffix. GEBUCHT bleibt unveraendert
        # ('Y'), nicht auf 'S' setzen — das macht CAO bei diesem Storno-
        # Pfad nicht.
        cur.execute(
            """UPDATE ZAHLUNGEN
                  SET STORNO       = 1,
                      STORNOGRUND  = %s,
                      VERW_ZWECK   = CONCAT(IFNULL(VERW_ZWECK,''),
                                            '\n--STORNO--')
                WHERE REC_ID = %s""",
            (grund, int(zahlung_rec_id))
        )
        rec_id = int(z.get('JOURNAL_ID') or 0)
        neues_stadium = None
        if rec_id > 0:
            neues_stadium = _stadium_neuberechnen(cur, rec_id)
            # CAO setzt zusaetzlich JOURNAL.INFO=NULL, Z_ID=-1,
            # PROJEKT_ID=-1 wenn der Beleg wieder komplett offen ist
            # (STADIUM=2). Bei Teilzahlung (STADIUM=7) belassen wir die
            # Felder.
            if neues_stadium == 2:
                cur.execute(
                    """UPDATE JOURNAL
                          SET INFO       = NULL,
                              Z_ID       = -1,
                              PROJEKT_ID = -1
                        WHERE REC_ID = %s""",
                    (rec_id,)
                )
        # JOURNAL_OP fuer QUELLE=5 neu aufbauen (CAO-Mimik)
        _journal_op_rebuild_qu5(cur)
    return {'ok': True, 'rec_id': int(zahlung_rec_id),
            'journal_stadium': neues_stadium}
