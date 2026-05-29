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
from common.cao_lock import cao_record_lock
from common.binaerdaten import MODUL_ID_ARTIKEL

# Inline editierbare Stammdatenfelder (Preise/Bestand/Keys bewusst NICHT).
EDITIERBAR: set[str] = {
    'MATCHCODE', 'KURZNAME', 'LANGNAME', 'KAS_NAME', 'INFO', 'FREITEXT',
    'ERSATZ_ARTNUM', 'BARCODE', 'BARCODE2', 'BARCODE3',
    'ARTIKELTYP', 'WARENGRUPPE', 'ME_ID', 'STEUER_CODE',
    'VPE', 'VPE_EK', 'PR_EINHEIT', 'GEWICHT', 'LAENGE', 'BREITE', 'HOEHE',
    'GROESSE', 'BASISPR_FAKTOR', 'BASISPR_ME_ID',
    'HERSTELLER_ID', 'HERST_ARTNUM', 'HERKUNFTSLAND', 'ZOLLNUMMER',
    'LAGERORT', 'MENGE_MIN', 'MENGE_BVOR', 'MENGE_WARN', 'LAGER_ID',
    'RABGRP_ID', 'ERLOES_KTO', 'AUFW_KTO', 'INVENTUR_WERT', 'DIMENSION',
    'MAXRABATT', 'MINGEWINN', 'PROVIS_PROZ',
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
    'HERSTELLER_ID', 'LAGER_ID', 'RABGRP_ID', 'INVENTUR_WERT',
    'MAXRABATT', 'MINGEWINN', 'PROVIS_PROZ',
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


# ── Listen-Spaltenregister (für konfigurierbare Artikel-Tabelle) ──────
# key → (Label, SQL-Ausdruck, Typ text|num|int, Default-sichtbar)
LISTE_SPALTEN: list[tuple] = [
    ('WGR_ID',     'WG',            'a.WARENGRUPPE',                 'int',  True),
    ('ARTIKELTYP', 'Typ',           'a.ARTIKELTYP',                  'text', True),
    ('BEZ',        'Suchbegriff',   "COALESCE(NULLIF(a.KAS_NAME,''),a.KURZNAME,a.MATCHCODE)", 'text', True),
    ('ARTNUM',     'Art-Nr',        'a.ARTNUM',                      'text', True),
    ('BARCODE',    'Barcode',       'a.BARCODE',                     'text', True),
    ('KURZNAME',   'Kurzname',      'a.KURZNAME',                    'text', False),
    ('MATCHCODE',  'Matchcode',     'a.MATCHCODE',                   'text', False),
    ('ERSATZ',     'Ersatz-Nr',     'a.ERSATZ_ARTNUM',               'text', False),
    ('HERST_ARTNUM','Herst-Art-Nr', 'a.HERST_ARTNUM',                'text', False),
    ('ME_NAME',    'ME',            'me.BEZEICHNUNG',                'text', True),
    ('VPE',        'VPE VK',        'a.VPE',                         'num',  False),
    ('VPE_EK',     'VPE EK',        'a.VPE_EK',                      'num',  False),
    ('PR_EINHEIT', 'Preis-Einh.',   'a.PR_EINHEIT',                  'num',  False),
    ('EK_PREIS',   'EK-Preis',      'a.EK_PREIS',                    'num',  True),
    ('VK1',        'VK1 netto',     'a.VK1',                         'num',  False),
    ('VK1B',       'VK1 brutto',    'a.VK1B',                        'num',  False),
    ('VK2',        'VK2 netto',     'a.VK2',                         'num',  False),
    ('VK2B',       'VK2 brutto',    'a.VK2B',                        'num',  False),
    ('VK3',        'VK3 netto',     'a.VK3',                         'num',  False),
    ('VK3B',       'VK3 brutto',    'a.VK3B',                        'num',  False),
    ('VK4',        'VK4 netto',     'a.VK4',                         'num',  False),
    ('VK4B',       'VK4 brutto',    'a.VK4B',                        'num',  False),
    ('VK5',        'VK5 netto',     'a.VK5',                         'num',  False),
    ('VK5B',       'VK5 brutto',    'a.VK5B',                        'num',  True),
    ('AKT_VK5',    'Aktion VK5',    'ap6.PREIS5',                    'num',  False),
    ('AKT_VON',    'Aktion von',    'ap6.GUELTIG_VON',               'date', False),
    ('AKT_BIS',    'Aktion bis',    'ap6.GUELTIG_BIS',               'date', False),
    ('MENGE_AKT',  'Menge',         'a.MENGE_AKT',                   'num',  True),
    ('WGR_NAME',   'Warengruppe',   'wg.NAME',                       'text', False),
    ('HERSTELLER', 'Hersteller',    'h.HERSTELLER_NAME',             'text', False),
    ('HERKUNFT',   'Herk.-Land',    'a.HERKUNFTSLAND',               'text', False),
    ('LAGERORT',   'Lagerort',      'a.LAGERORT',                    'text', False),
    ('VARARTNUM',  'Variant Art-Nr','a.VARARTNUM',                   'text', False),
    ('BREITE',     'Breite',        'a.BREITE',                      'num',  False),
    ('HOEHE',      'Höhe',          'a.HOEHE',                       'num',  False),
    ('GROESSE',    'Größe',         'a.GROESSE',                     'text', False),
    ('DIMENSION',  'Dimension',     'a.DIMENSION',                   'text', False),
    ('GEWICHT',    'Gewicht',       'a.GEWICHT',                     'num',  False),
    ('INVENTUR_WERT','I-Wert',      'a.INVENTUR_WERT',               'num',  False),
    ('RABGRP_ID',  'Rab.-Gr.',      'a.RABGRP_ID',                   'int',  False),
    ('SORTIERUNG', 'Sortierung',    'a.USERFELD_01',                 'text', False),
    ('PLU',        'PLU',           'a.USERFELD_04',                 'text', False),
    ('PLU2',       'PLU-2',         'a.USERFELD_05',                 'text', False),
    ('ERLEDIGT',   'erledigt',      'a.USERFELD_02',                 'text', False),
    ('LOESCH',     'Löschvermerk',  'a.USERFELD_03',                 'text', False),
    ('UF06',       'Feld 06',       'a.USERFELD_06',                 'text', False),
    ('UF07',       'Feld 07',       'a.USERFELD_07',                 'text', False),
    ('UF08',       'Feld 08',       'a.USERFELD_08',                 'text', False),
    ('UF09',       'Feld 09',       'a.USERFELD_09',                 'text', False),
    ('UF10',       'Feld 10',       'a.USERFELD_10',                 'text', False),
    ('ERLOES_KTO', 'E-KTO',         'a.ERLOES_KTO',                  'text', False),
    ('AUFW_KTO',   'A-KTO',         'a.AUFW_KTO',                    'text', False),
    ('ERSTELLT',   'erstellt',      'a.ERSTELLT',                    'date', False),
    ('ERST_NAME',  'erstellt von',  'a.ERST_NAME',                   'text', False),
    ('GEAEND',     'le. Änderung',  'a.GEAEND',                      'date', False),
    ('GEAEND_NAME','geändert von',  'a.GEAEND_NAME',                 'text', False),
]
_SORT_WHITELIST = {k for k, *_ in LISTE_SPALTEN}


def liste_spalten_meta() -> list[dict[str, Any]]:
    return [{'key': k, 'label': lbl, 'typ': typ, 'default': dflt}
            for k, lbl, _sql, typ, dflt in LISTE_SPALTEN]


def artikel_liste(suche: str = '', *, wg_id: int | None = None,
                  merk_id: int | None = None, nur_aktion: bool = False,
                  sort: str = 'BEZ', sort_dir: str = 'asc',
                  limit: int | None = 1000) -> list[dict[str, Any]]:
    """Artikel nach Warengruppe (rekursiv), Merkmal, Aktionspreis oder
    Volltext. Liefert alle Register-Spalten (für konfigurierbare Tabelle)."""
    cols = ',\n'.join(f'{sql} AS {k}' for k, _l, sql, _t, _d in LISTE_SPALTEN)
    order = sort if sort in _SORT_WHITELIST else 'BEZ'
    direction = 'DESC' if str(sort_dir).lower() == 'desc' else 'ASC'
    where = ['1=1']
    params: list[Any] = []
    suche = (suche or '').strip()
    if suche:
        where.append("(a.ARTNUM LIKE %s OR a.KURZNAME LIKE %s "
                      "OR a.MATCHCODE LIKE %s OR a.BARCODE LIKE %s "
                      "OR a.KAS_NAME LIKE %s)")
        like = f'%{suche}%'
        params += [like] * 5
    join = ("LEFT JOIN WARENGRUPPEN wg ON wg.ID = a.WARENGRUPPE\n"
            "LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID\n"
            "LEFT JOIN HERSTELLER h ON h.HERSTELLER_ID = a.HERSTELLER_ID\n"
            "LEFT JOIN ARTIKEL_PREIS ap6 ON ap6.ARTIKEL_ID=a.REC_ID "
            "AND ap6.ADRESS_ID=-99 AND ap6.PREIS_TYP=6")
    if nur_aktion:
        where.append("ap6.ARTIKEL_ID IS NOT NULL")
    if merk_id:
        join += ("\nJOIN ARTIKEL_TO_MERK tm ON tm.ARTIKEL_ID=a.REC_ID "
                 "AND tm.MERKMAL_ID=%s")
        params.insert(0, int(merk_id))
    elif wg_id:
        join += ("\nJOIN (WITH RECURSIVE t AS ("
                 "SELECT ID FROM WARENGRUPPEN WHERE ID=%s "
                 "UNION ALL SELECT w.ID FROM WARENGRUPPEN w "
                 "JOIN t ON w.TOP_ID=t.ID) SELECT ID FROM t) wt "
                 "ON wt.ID = a.WARENGRUPPE")
        params.insert(0, int(wg_id))
    lim = f' LIMIT {int(limit)}' if limit else ''
    sql = (f"SELECT a.REC_ID, {cols}\n  FROM ARTIKEL a\n  {join}\n"
           f" WHERE {' AND '.join(where)}\n"
           f" ORDER BY {order} {direction}{lim}")
    with get_db() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def warengruppen_tree() -> list[dict[str, Any]]:
    """Flacher Warengruppen-Baum mit Nummer (=ID, 3-stellig) + direkter
    Artikel-Anzahl, sortiert wie CAO (SORT, ID)."""
    sql = """SELECT wg.ID AS id, wg.TOP_ID AS parent_id, wg.NAME AS name,
                    wg.SORT AS sort,
                    (SELECT COUNT(*) FROM ARTIKEL a WHERE a.WARENGRUPPE=wg.ID) AS direkt
               FROM WARENGRUPPEN wg
              ORDER BY wg.SORT, wg.ID"""
    with get_db() as cur:
        cur.execute(sql)
        rows = list(cur.fetchall() or [])
    for r in rows:
        if r['parent_id'] in (-1, 0, '-1', '0', None):
            r['parent_id'] = None
        r['nummer'] = f"{int(r['id']):03d}"
    return rows


def aktionspreise_anzahl() -> int:
    """Anzahl Artikel mit hinterlegtem Aktionspreis (PREIS_TYP=6)."""
    with get_db() as cur:
        cur.execute("SELECT COUNT(*) c FROM ARTIKEL_PREIS "
                    "WHERE ADRESS_ID=-99 AND PREIS_TYP=6")
        return int((cur.fetchone() or {}).get('c') or 0)


def merkmale_liste() -> list[dict[str, Any]]:
    """Alle Merkmale mit Artikel-Anzahl (ARTIKEL_MERK + ARTIKEL_TO_MERK)."""
    sql = """SELECT m.MERKMAL_ID AS id, m.NAME AS name,
                    (SELECT COUNT(*) FROM ARTIKEL_TO_MERK tm
                      WHERE tm.MERKMAL_ID=m.MERKMAL_ID) AS anzahl
               FROM ARTIKEL_MERK m ORDER BY m.NAME"""
    with get_db() as cur:
        cur.execute(sql)
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


def aktionspreis_speichern(rec_id: int, vk: list, von=None, bis=None, *,
                           ma_name: str = 'CAO-XT') -> None:
    """Aktionspreis setzen/ändern/löschen (ARTIKEL_PREIS PREIS_TYP=6,
    ADRESS_ID=-99) — CAO-Trace: Record-Lock (MOD 1020), DELETE+INSERT,
    GEAEND-Bump. Leere Werte (alle VK=0 und kein Zeitraum) → nur löschen.

    Hinweis: CAO schreibt zusätzlich einen ARTIKEL_LOG-Eintrag mit
    (nicht reproduzierbarer) HASHSUM; das lassen wir — wie die übrigen
    ARTIKEL-Stammdaten-Writes des Projekts — weg.
    """
    rec_id = int(rec_id)
    vals = [float(str(x).replace(',', '.') or 0) if x not in (None, '') else 0.0
            for x in (list(vk) + [0] * 5)[:5]]
    von = von or None
    bis = bis or None
    hat = any(vals) or (von and bis)
    ma = (ma_name or 'CAO-XT')[:50]
    with get_db_transaction() as cur:
        with cao_record_lock(cur, MODUL_ID_ARTIKEL, rec_id):
            cur.execute("DELETE FROM ARTIKEL_PREIS WHERE ARTIKEL_ID=%s "
                        "AND ADRESS_ID=-99 AND PREIS_TYP=6", (rec_id,))
            if hat:
                cur.execute(
                    """INSERT INTO ARTIKEL_PREIS
                       (ARTIKEL_ID, ADRESS_ID, PREIS_TYP, PT2, BESTNUM,
                        LIEFERZEIT_ID, VPE, PREIS, RABATT,
                        MENGE2, PREIS2, PREIS2_AUTO, FAKTOR2,
                        MENGE3, PREIS3, PREIS3_AUTO, FAKTOR3,
                        MENGE4, PREIS4, PREIS4_AUTO, FAKTOR4,
                        MENGE5, PREIS5, PREIS5_AUTO, FAKTOR5,
                        GUELTIG_VON, GUELTIG_BIS, INFO, GEAEND, GEAEND_NAME,
                        RABATT2, RABATT3, RABATT4, RABATT5, URL)
                       VALUES (%s,-99,6,'EK','',1,0,%s,0,
                               0,%s,'Y',0, 0,%s,'Y',0, 0,%s,'Y',0, 0,%s,'Y',0,
                               %s,%s,'',NOW(),%s, 0,0,0,0,'')""",
                    (rec_id, vals[0], vals[1], vals[2], vals[3], vals[4],
                     von, bis, ma))
            cur.execute("UPDATE ARTIKEL SET GEAEND=NOW(), GEAEND_NAME=%s "
                        "WHERE REC_ID=%s", (ma, rec_id))


def lieferantenpreis_speichern(rec_id: int, adress_id: int, *,
                               bestnum: str = '', vpe=0, preis=0,
                               als_standard: bool = False,
                               ma_name: str = 'CAO-XT') -> None:
    """Lieferantenpreis anlegen/ändern (ARTIKEL_PREIS PREIS_TYP=5,
    ADRESS_ID=Lieferant). CAO-Trace: Upsert + Record-Lock; ``als_standard``
    setzt ARTIKEL.DEFAULT_LIEF_ID."""
    rec_id, adress_id = int(rec_id), int(adress_id)
    vpe = float(str(vpe).replace(',', '.') or 0)
    preis = float(str(preis).replace(',', '.') or 0)
    bestnum = (bestnum or '')[:30]
    ma = (ma_name or 'CAO-XT')[:50]
    with get_db_transaction() as cur:
        with cao_record_lock(cur, MODUL_ID_ARTIKEL, rec_id):
            cur.execute(
                "UPDATE ARTIKEL_PREIS SET PT2='EK', BESTNUM=%s, VPE=%s, "
                "PREIS=%s, GEAEND=NOW(), GEAEND_NAME=%s "
                "WHERE ARTIKEL_ID=%s AND ADRESS_ID=%s AND PREIS_TYP=5",
                (bestnum, vpe, preis, ma, rec_id, adress_id))
            if cur.rowcount == 0:
                cur.execute(
                    """INSERT INTO ARTIKEL_PREIS
                       (ARTIKEL_ID, ADRESS_ID, PREIS_TYP, PT2, BESTNUM,
                        LIEFERZEIT_ID, VPE, PREIS, RABATT,
                        MENGE2, PREIS2, PREIS2_AUTO, FAKTOR2,
                        MENGE3, PREIS3, PREIS3_AUTO, FAKTOR3,
                        MENGE4, PREIS4, PREIS4_AUTO, FAKTOR4,
                        MENGE5, PREIS5, PREIS5_AUTO, FAKTOR5,
                        GUELTIG_VON, GUELTIG_BIS, INFO, GEAEND, GEAEND_NAME,
                        RABATT2, RABATT3, RABATT4, RABATT5, URL)
                       VALUES (%s,%s,5,'EK',%s,1,%s,%s,0,
                               0,0,'Y',0, 0,0,'Y',0, 0,0,'Y',0, 0,0,'Y',0,
                               NULL,NULL,'',NOW(),%s, 0,0,0,0,'')""",
                    (rec_id, adress_id, bestnum, vpe, preis, ma))
            if als_standard:
                cur.execute("UPDATE ARTIKEL SET DEFAULT_LIEF_ID=%s, "
                            "GEAEND=NOW(), GEAEND_NAME=%s WHERE REC_ID=%s",
                            (adress_id, ma, rec_id))
            else:
                cur.execute("UPDATE ARTIKEL SET GEAEND=NOW(), GEAEND_NAME=%s "
                            "WHERE REC_ID=%s", (ma, rec_id))


def lieferantenpreis_loeschen(rec_id: int, adress_id: int, *,
                              ma_name: str = 'CAO-XT') -> None:
    """Lieferantenpreis löschen; war es der Standard-Lieferant, wird
    ARTIKEL.DEFAULT_LIEF_ID auf -1 gesetzt (CAO-Trace)."""
    rec_id, adress_id = int(rec_id), int(adress_id)
    ma = (ma_name or 'CAO-XT')[:50]
    with get_db_transaction() as cur:
        with cao_record_lock(cur, MODUL_ID_ARTIKEL, rec_id):
            cur.execute(
                "UPDATE ARTIKEL SET DEFAULT_LIEF_ID="
                "IF(DEFAULT_LIEF_ID=%s,-1,DEFAULT_LIEF_ID), "
                "GEAEND=NOW(), GEAEND_NAME=%s WHERE REC_ID=%s",
                (adress_id, ma, rec_id))
            cur.execute("DELETE FROM ARTIKEL_PREIS WHERE ARTIKEL_ID=%s "
                        "AND ADRESS_ID=%s AND PREIS_TYP=5",
                        (rec_id, adress_id))


def lieferanten_suche(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Adress-Suche für den Lieferanten-Picker (ARTIKEL_PREIS PREIS_TYP=5)."""
    q = (q or '').strip()
    if not q:
        return []
    like = f'%{q}%'
    sql = """SELECT REC_ID AS id,
                    TRIM(CONCAT_WS(' ', NAME1, NAME2)) AS name,
                    KUNNUM1, KUNNUM2
               FROM ADRESSEN
              WHERE NAME1 LIKE %s OR NAME2 LIKE %s OR MATCHCODE LIKE %s
                    OR KUNNUM1 LIKE %s
              ORDER BY NAME1 LIMIT %s"""
    with get_db() as cur:
        cur.execute(sql, (like, like, like, like, int(limit)))
        return list(cur.fetchall() or [])
