"""Artikel-Stammdaten lesen + einzelne Felder ändern (Artikelpflege).

ARTIKEL hat — anders als ADRESSEN — KEINE HASHSUM und CAO schreibt kein
verpflichtendes *_LOG beim Stammdaten-Edit (vgl. bestehende
``modules.orga.models.artikel_vk5_setzen``: direktes ``UPDATE ARTIKEL``).
Daher hier ebenso: direktes Whitelist-UPDATE + GEAEND/GEAEND_NAME-Bump,
kein Log/HMAC-Mimik. Preise (VK/EK) werden NICHT hier, sondern in der
Preispflege gepflegt → in der Artikelpflege read-only.
"""
from __future__ import annotations

from typing import Any

from common.db import get_db, get_db_transaction

# Inline editierbare Stammdatenfelder (Preise/Bestand/Keys bewusst NICHT).
EDITIERBAR: set[str] = {
    'MATCHCODE', 'KURZNAME', 'LANGNAME', 'KAS_NAME', 'INFO', 'FREITEXT',
    'ERSATZ_ARTNUM', 'BARCODE', 'BARCODE2', 'BARCODE3',
    'ARTIKELTYP', 'WARENGRUPPE', 'ME_ID', 'STEUER_CODE',
    'VPE', 'VPE_EK', 'PR_EINHEIT', 'GEWICHT', 'LAENGE', 'BREITE', 'HOEHE',
    'GROESSE', 'BASISPR_FAKTOR', 'BASISPR_ME_ID',
    'HERSTELLER_ID', 'HERST_ARTNUM', 'HERKUNFTSLAND', 'ZOLLNUMMER',
    'LAGERORT', 'MENGE_MIN', 'MENGE_BVOR', 'MENGE_WARN', 'LAGER_ID',
    'NO_RABATT_FLAG', 'NO_VK_FLAG', 'NO_EK_FLAG', 'FSK18_FLAG', 'SN_FLAG',
    'USERFELD_01', 'USERFELD_02', 'USERFELD_03', 'USERFELD_04',
    'USERFELD_05', 'USERFELD_06', 'USERFELD_07', 'USERFELD_08',
    'USERFELD_09', 'USERFELD_10',
}

# Spalten, die in ein numerisches Feld geschrieben werden (leer → 0).
_NUM_COLS = {
    'VPE', 'VPE_EK', 'PR_EINHEIT', 'GEWICHT', 'LAENGE', 'BREITE', 'HOEHE',
    'BASISPR_FAKTOR', 'MENGE_MIN', 'MENGE_BVOR', 'MENGE_WARN',
    'ME_ID', 'BASISPR_ME_ID', 'WARENGRUPPE', 'STEUER_CODE',
    'HERSTELLER_ID', 'LAGER_ID',
}


# ── Lesen ──────────────────────────────────────────────────────────────

def artikel_holen(rec_id: int) -> dict[str, Any] | None:
    """Vollständige ARTIKEL-Zeile + aufgelöste Namen (WG, Einheit, Hersteller)."""
    sql = """SELECT a.*, wg.NAME AS WGR_NAME,
                    me.BEZEICHNUNG AS ME_NAME,
                    bme.BEZEICHNUNG AS BASIS_ME_NAME,
                    h.HERSTELLER_NAME AS HERSTELLER_NAME,
                    lg.BEZEICHNUNG AS LAGER_NAME
               FROM ARTIKEL a
               LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
               LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
               LEFT JOIN MENGENEINHEIT bme ON bme.REC_ID = a.BASISPR_ME_ID
               LEFT JOIN HERSTELLER h ON h.HERSTELLER_ID = a.HERSTELLER_ID
               LEFT JOIN LAGER lg ON lg.LAGER_ID = a.LAGER_ID
              WHERE a.REC_ID = %s"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id),))
        return cur.fetchone()


def artikel_liste(suche: str = '', *, wg_id: int | None = None,
                  sort: str = 'KURZNAME', sort_dir: str = 'asc',
                  limit: int | None = None) -> list[dict[str, Any]]:
    """Artikel einer Warengruppe (inkl. Untergruppen) bzw. Volltextsuche."""
    sort_map = {
        'ARTNUM': 'a.ARTNUM', 'KURZNAME': 'a.KURZNAME',
        'MATCHCODE': 'a.MATCHCODE', 'WGR_NAME': 'wg.NAME',
        'ARTIKELTYP': 'a.ARTIKELTYP', 'EK_PREIS': 'a.EK_PREIS',
        'VK5B': 'a.VK5B', 'MENGE_AKT': 'a.MENGE_AKT', 'ME_NAME': 'me.BEZEICHNUNG',
    }
    order = sort_map.get(sort, 'a.KURZNAME')
    direction = 'DESC' if str(sort_dir).lower() == 'desc' else 'ASC'
    where = ['1=1']
    params: list[Any] = []
    suche = (suche or '').strip()
    if suche:
        where.append("(a.ARTNUM LIKE %s OR a.KURZNAME LIKE %s "
                      "OR a.MATCHCODE LIKE %s OR a.BARCODE LIKE %s "
                      "OR a.KAS_NAME LIKE %s)")
        like = f'%{suche}%'
        params += [like, like, like, like, like]
    join_wg = ''
    if wg_id:
        join_wg = ("JOIN (WITH RECURSIVE t AS ("
                   "SELECT ID FROM WARENGRUPPEN WHERE ID=%s "
                   "UNION ALL SELECT w.ID FROM WARENGRUPPEN w "
                   "JOIN t ON w.TOP_ID=t.ID) SELECT ID FROM t) wt "
                   "ON wt.ID = a.WARENGRUPPE")
        params.insert(0, int(wg_id))
    lim = f' LIMIT {int(limit)}' if limit else ''
    sql = f"""SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KURZNAME, a.KAS_NAME,
                     a.BARCODE, a.ARTIKELTYP, a.EK_PREIS, a.VK5B, a.MENGE_AKT,
                     a.WARENGRUPPE AS WGR_ID, wg.NAME AS WGR_NAME,
                     me.BEZEICHNUNG AS ME_NAME
                FROM ARTIKEL a
                {join_wg}
                LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE
                LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
               WHERE {' AND '.join(where)}
               ORDER BY {order} {direction}{lim}"""
    with get_db() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def merkmale(rec_id: int) -> list[dict[str, Any]]:
    sql = """SELECT m.MERKMAL_ID, m.NAME
               FROM ARTIKEL_TO_MERK tm
               JOIN ARTIKEL_MERK m ON m.MERKMAL_ID = tm.MERKMAL_ID
              WHERE tm.ARTIKEL_ID = %s ORDER BY m.NAME"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id),))
        return list(cur.fetchall() or [])


def _partner_preise(rec_id: int, preis_typ: int) -> list[dict[str, Any]]:
    """Partner-bezogene Preise (CAO-Trace: PREIS_TYP 5=Lief, 3=Kunde),
    nur ADRESS_ID>0, sortiert nach Ku-Nr beim Lieferanten (KUNNUM2)."""
    sql = """SELECT ap.ADRESS_ID, ap.BESTNUM, ap.VPE, ap.PREIS, ap.RABATT,
                    ap.GEAEND, ap.GEAEND_NAME,
                    TRIM(CONCAT_WS(' ', ad.NAME1, ad.NAME2)) AS PARTNER,
                    ad.KUNNUM1, ad.KUNNUM2
               FROM ARTIKEL_PREIS ap
               LEFT JOIN ADRESSEN ad ON ad.REC_ID = ap.ADRESS_ID
              WHERE ap.ARTIKEL_ID = %s AND ap.PREIS_TYP = %s
                AND ap.ADRESS_ID > 0
              ORDER BY ad.KUNNUM2"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id), int(preis_typ)))
        return list(cur.fetchall() or [])


def lieferantenpreise(rec_id: int) -> list[dict[str, Any]]:
    """EK-Preise je Lieferant (ARTIKEL_PREIS PREIS_TYP=5, ADRESS_ID>0)."""
    return _partner_preise(rec_id, 5)


def kundenpreise(rec_id: int) -> list[dict[str, Any]]:
    """Kundenspezifische VK-Preise (ARTIKEL_PREIS PREIS_TYP=3)."""
    return _partner_preise(rec_id, 3)


def aktionspreis(rec_id: int) -> dict[str, Any] | None:
    """Aktions-/Standard-Preiszeile (PREIS_TYP=6, ADRESS_ID=-99):
    PREIS..PREIS5 = VK1..VK5-Aktionspreis + Gültigkeit."""
    sql = """SELECT PREIS, PREIS2, PREIS3, PREIS4, PREIS5,
                    GUELTIG_VON, GUELTIG_BIS, RABATT
               FROM ARTIKEL_PREIS
              WHERE ARTIKEL_ID = %s AND PREIS_TYP = 6 AND ADRESS_ID = -99"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id),))
        return cur.fetchone()


def lagerbestaende(rec_id: int) -> list[dict[str, Any]]:
    """Bestand je Lager — CAO-Trace: Standardlager aus ARTIKEL.MENGE_AKT
    ∪ LAGER_MENGEN (LAGER_ID -2=Standard, -3=Produktion)."""
    sql = """
        (SELECT -99 AS LAGER_ID, A.MENGE_AKT AS MENGE, A.MENGE_MIN,
                A.MENGE_BVOR, 'Standardlager' AS LAGER_NAME
           FROM ARTIKEL A WHERE A.REC_ID=%s)
        UNION
        (SELECT LM.LAGER_ID, SUM(IFNULL(LM.MENGE, A.MENGE_AKT)) AS MENGE,
                LM.MENGE_MIN, LM.MENGE_BVOR,
                CASE WHEN LM.LAGER_ID IS NULL THEN 'Standardlager'
                     WHEN LM.LAGER_ID=-2 THEN 'Standardlager'
                     WHEN LM.LAGER_ID=-3 THEN 'Produktionslager'
                     ELSE LA.BEZEICHNUNG END AS LAGER_NAME
           FROM ARTIKEL A
           LEFT JOIN LAGER_MENGEN LM ON LM.ARTIKEL_ID=A.REC_ID
           LEFT JOIN LAGER LA ON LA.LAGER_ID=LM.LAGER_ID
          WHERE A.REC_ID=%s AND LM.LAGER_ID IS NOT NULL
          GROUP BY LM.LAGER_ID)"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id), int(rec_id)))
        return list(cur.fetchall() or [])


def bestand_historie(rec_id: int, limit: int = 300) -> list[dict[str, Any]]:
    """Lagerbewegungen (ARTIKEL_HISTORIE). QUELLE_STR ist Klartext;
    Partnername je QUELLE aufgelöst (CAO-Trace)."""
    sql = """SELECT H.GEAND AS DATUM, H.QUELLE_STR, H.JID, H.MENGE_GEBUCHT,
                    H.MENGE_LAGER, H.GEAND_NAME, H.INFO, H.PROJEKT, H.ORGNUM,
                    CASE
                      WHEN H.QUELLE IN (3,4,5,31,41) THEN
                        (SELECT CONCAT_WS(' ',TRIM(KUN_NAME1),TRIM(KUN_NAME2))
                           FROM JOURNAL WHERE REC_ID=H.JID)
                      WHEN H.QUELLE IN (2,20) THEN
                        (SELECT CONCAT_WS(' ',TRIM(KUN_NAME1),TRIM(KUN_NAME2))
                           FROM LIEFERSCHEIN WHERE REC_ID=H.JID)
                      WHEN H.QUELLE IN (9,91) THEN
                        (SELECT CONCAT_WS(' ',TRIM(KUN_NAME1),TRIM(KUN_NAME2))
                           FROM EKEINGANG WHERE REC_ID=H.JID)
                      ELSE '' END AS PARTNER
               FROM ARTIKEL_HISTORIE H
              WHERE H.ARTIKEL_ID = %s
              ORDER BY H.REC_ID DESC
              LIMIT %s"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id), int(limit)))
        return list(cur.fetchall() or [])


# QUELLE-Labels für die Artikel-Vorgangshistorie (positionsbasiert, CAO).
QUELLE_LABEL = {
    1: 'Angebot', 11: 'Angebot (Entwurf)',
    2: 'Lieferschein', 12: 'EDI-Lieferschein',
    3: 'VK-Rechnung', 13: 'VK-Rechnung (Entwurf)',
    4: 'VK-Gutschrift', 14: 'VK-Gutschrift (Entwurf)',
    5: 'EK-Rechnung', 15: 'EK-Rechnung (Entwurf)',
    6: 'EK-Bestellung', 16: 'EK-Bestellung (offen)',
    7: 'Preisanfrage', 17: 'Preisanfrage (offen)',
    8: 'Auftrag', 18: 'Auftrag (Entwurf)',
    9: 'Wareneingang', 19: 'Wareneingang (EK)',
    23: 'Vertrag',
}


def vorgangs_historie(rec_id: int, jahr_ab: int | None = None,
                      limit: int = 500) -> list[dict[str, Any]]:
    """Positionsbasierte Vorgangshistorie des Artikels (CAO-Trace-UNION:
    JOURNALPOS VK+EK, LIEFERSCHEIN_POS, VERTRAGPOS, EKBESTELL_POS
    Bestellung+Preisanfrage, EKEINGANG_POS)."""
    aid = int(rec_id)
    cols = ("QUELLE, BELEGDATUM, BELEGNUM, NAME, BEZEICHNUNG, MENGE, "
            "ME_EINHEIT, VPE, PR_EINHEIT, EPREIS, RABATT, GPREIS, "
            "STEUER_PROZ, STADIUM, WAEHRUNG, PROJEKT")
    parts = [
        # VK-Journal (Rechnung/Gutschrift/Angebot/Auftrag + Entwürfe)
        f"""SELECT ROUND(JP.QUELLE,0) AS QUELLE, DATE(J.RDATUM) AS BELEGDATUM,
              J.VRENUM AS BELEGNUM,
              TRIM(CONCAT_WS(' ',J.KUN_NAME1,J.KUN_NAME2,J.KUN_NAME3)) AS NAME,
              JP.BEZEICHNUNG, JP.MENGE, JP.ME_EINHEIT, JP.VPE, JP.PR_EINHEIT,
              JP.EPREIS, JP.RABATT, JP.GPREIS,
              CASE JP.STEUER_CODE WHEN 1 THEN J.MWST_1 WHEN 2 THEN J.MWST_2
                   WHEN 3 THEN J.MWST_3 ELSE J.MWST_0 END AS STEUER_PROZ,
              J.STADIUM, J.WAEHRUNG, J.PROJEKT
            FROM JOURNALPOS JP JOIN JOURNAL J ON J.REC_ID=JP.JOURNAL_ID
           WHERE J.STADIUM<>120 AND J.TERM_ID<>99999 AND J.QUELLE>0
             AND JP.QUELLE>0 AND JP.ARTIKEL_ID={aid}
             AND JP.QUELLE IN (1,11,8,18,3,4,13,14,5,15)""",
        # Lieferschein
        f"""SELECT ROUND(CASE WHEN J.EDI_FLAG='Y' THEN 12 ELSE 2 END,0) AS QUELLE,
              J.LDATUM AS BELEGDATUM, JP.VLSNUM AS BELEGNUM,
              TRIM(CONCAT_WS(' ',J.KUN_NAME1,J.KUN_NAME2,J.KUN_NAME3)) AS NAME,
              JP.BEZEICHNUNG, JP.MENGE, JP.ME_EINHEIT, JP.VPE, JP.PR_EINHEIT,
              JP.EPREIS, JP.RABATT, JP.GPREIS,
              CASE JP.STEUER_CODE WHEN 1 THEN J.MWST_1 WHEN 2 THEN J.MWST_2
                   WHEN 3 THEN J.MWST_3 ELSE J.MWST_0 END AS STEUER_PROZ,
              CASE WHEN J.STORNO_FLAG='Y' THEN 127 ELSE 0 END AS STADIUM,
              J.WAEHRUNG, J.PROJEKT
            FROM LIEFERSCHEIN_POS JP JOIN LIEFERSCHEIN J
              ON J.REC_ID=JP.LIEFERSCHEIN_ID
           WHERE JP.ARTIKEL_ID={aid}""",
        # EK-Bestellung (Bestellung + Preisanfrage)
        f"""SELECT ROUND(CASE WHEN J.STADIUM=0 THEN 16 ELSE 6 END,0) AS QUELLE,
              J.BELEGDATUM, JP.BELEGNUM,
              TRIM(CONCAT_WS(' ',J.KUN_NAME1,J.KUN_NAME2,J.KUN_NAME3)) AS NAME,
              JP.BEZEICHNUNG, JP.MENGE, JP.ME_EINHEIT, JP.VPE, JP.PR_EINHEIT,
              JP.EPREIS, JP.RABATT1 AS RABATT, JP.GPREIS,
              CASE JP.STEUER_CODE WHEN 1 THEN J.MWST_1 WHEN 2 THEN J.MWST_2
                   WHEN 3 THEN J.MWST_3 ELSE J.MWST_0 END AS STEUER_PROZ,
              J.STADIUM, J.WAEHRUNG, J.PROJEKT
            FROM EKBESTELL_POS JP JOIN EKBESTELL J ON J.REC_ID=JP.EKBESTELL_ID
           WHERE J.PREISANFRAGE='N' AND JP.ARTIKEL_ID={aid}""",
        f"""SELECT ROUND(CASE WHEN J.STADIUM=0 THEN 17 ELSE 7 END,0) AS QUELLE,
              J.BELEGDATUM, JP.BELEGNUM,
              TRIM(CONCAT_WS(' ',J.KUN_NAME1,J.KUN_NAME2,J.KUN_NAME3)) AS NAME,
              JP.BEZEICHNUNG, JP.MENGE, JP.ME_EINHEIT, JP.VPE, JP.PR_EINHEIT,
              JP.EPREIS, JP.RABATT1 AS RABATT, JP.GPREIS,
              CASE JP.STEUER_CODE WHEN 1 THEN J.MWST_1 WHEN 2 THEN J.MWST_2
                   WHEN 3 THEN J.MWST_3 ELSE J.MWST_0 END AS STEUER_PROZ,
              J.STADIUM, J.WAEHRUNG, J.PROJEKT
            FROM EKBESTELL_POS JP JOIN EKBESTELL J ON J.REC_ID=JP.EKBESTELL_ID
           WHERE J.PREISANFRAGE='Y' AND JP.ARTIKEL_ID={aid}""",
        # Wareneingang
        f"""SELECT ROUND(CASE WHEN J.QUELLE=19 THEN 19 ELSE 9 END,0) AS QUELLE,
              J.BELEGDATUM, JP.BELEGNUM,
              TRIM(CONCAT_WS(' ',J.KUN_NAME1,J.KUN_NAME2,J.KUN_NAME3)) AS NAME,
              JP.BEZEICHNUNG, JP.MENGE, JP.ME_EINHEIT, JP.VPE, JP.PR_EINHEIT,
              0 AS EPREIS, 0 AS RABATT, 0 AS GPREIS, 0 AS STEUER_PROZ,
              J.STADIUM, '€' AS WAEHRUNG, J.PROJEKT
            FROM EKEINGANG_POS JP JOIN EKEINGANG J ON J.REC_ID=JP.EKEINGANG_ID
           WHERE JP.ARTIKEL_ID={aid}""",
    ]
    sql = ('SELECT ' + cols + ' FROM (\n'
           + '\nUNION ALL\n'.join(f'({p})' for p in parts)
           + f'\n) v ORDER BY BELEGDATUM DESC LIMIT {int(limit)}')
    with get_db() as cur:
        cur.execute(sql)
        return list(cur.fetchall() or [])


def dateien(rec_id: int) -> list[dict[str, Any]]:
    """Verknüpfte Dateien (LINK, MODUL_ID=2 = Artikel)."""
    sql = """SELECT * FROM LINK WHERE MODUL_ID = 2 AND REC_ID = %s
              ORDER BY DATEI, PFAD"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id),))
        return list(cur.fetchall() or [])


# ── Lookups (Dropdowns/Klartext) ───────────────────────────────────────

def einheiten() -> list[dict[str, Any]]:
    with get_db() as cur:
        cur.execute("SELECT REC_ID AS id, BEZEICHNUNG AS name "
                    "FROM MENGENEINHEIT ORDER BY BEZEICHNUNG")
        return list(cur.fetchall() or [])


def warengruppen() -> list[dict[str, Any]]:
    with get_db() as cur:
        cur.execute("SELECT ID AS id, NAME AS name FROM WARENGRUPPEN "
                    "ORDER BY NAME")
        return list(cur.fetchall() or [])


def hersteller() -> list[dict[str, Any]]:
    with get_db() as cur:
        cur.execute("SELECT HERSTELLER_ID AS id, HERSTELLER_NAME AS name "
                    "FROM HERSTELLER ORDER BY HERSTELLER_NAME")
        return list(cur.fetchall() or [])


def lager() -> list[dict[str, Any]]:
    with get_db() as cur:
        cur.execute("SELECT LAGER_ID AS id, BEZEICHNUNG AS name FROM LAGER "
                    "ORDER BY BEZEICHNUNG")
        return list(cur.fetchall() or [])


# ── Schreiben (ein Feld, direktes UPDATE) ──────────────────────────────

def artikel_feld_aendern(rec_id: int, feld: str, wert: Any, *,
                         ma_name: str = 'CAO-XT') -> None:
    """Ändert ein Whitelist-Feld direkt in ARTIKEL (+ GEAEND-Bump).

    Kein Lock/Log (CAO-Konvention für ARTIKEL-Stammdaten, vgl.
    artikel_vk5_setzen). Wirft ValueError bei nicht erlaubtem Feld."""
    col = (feld or '').strip().upper()
    if col not in EDITIERBAR:
        raise ValueError(f'Feld {col!r} ist nicht editierbar')
    if col in _NUM_COLS:
        wert = (str(wert).strip() or '0').replace(',', '.')
        wert = float(wert) if '.' in wert else int(wert)
    with get_db_transaction() as cur:
        cur.execute(
            f"UPDATE ARTIKEL SET {col}=%s, GEAEND=NOW(), GEAEND_NAME=%s "
            f"WHERE REC_ID=%s",
            (wert, (ma_name or 'CAO-XT')[:50], int(rec_id)))
