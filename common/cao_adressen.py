"""
CAO-Adressen anlegen/ändern — perfekte CAO-Mimik.

Reverse-engineered aus dem cao_faktura.exe-SQL-Trace (2026-05-17):
``INSERT INTO ADRESSEN`` (alle Spalten + Defaults) → ``INSERT INTO
ADRESSEN_LOG`` (Snapshot, HASHSUM zunächst leer) → XT-HASHSUM
berechnen (``cao_log_hashsum``; CAO-``*_LOG``-Algo ist NICHT
reproduzierbar und wird von CAO NICHT laufzeit-validiert → Projekt-
Konvention XT-HMAC) → ``UPDATE ADRESSEN_LOG SET HASHSUM``.

Lock: CAO nimmt ``GET_LOCK('cao_<db>_MOD_1010_RECID_<id>')``. Das ist
ein Record-Mutex gegen gleichzeitiges *Bearbeiten* desselben
Datensatzes → nur beim **Ändern** sinnvoll (beim Anlegen ist die
REC_ID neu, niemand sonst referenziert sie). Daher Lock nur in
:func:`adresse_aendern`, auf DERSELBEN Connection.

MODUL_ID 1010 = ADRESSEN.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from common.db import get_db, get_db_transaction
from common import cao_hashsum as _cao_hashsum
from common import cao_log_hashsum as _cao_log_hashsum
from common.cao_lock import cao_record_lock, CaoLockBelegt
from common.binaerdaten import MODUL_ID_ADRESSEN

# ── ADRESSEN: Spalten + CAO-Defaults (exakt aus dem Trace) ──────────
# Wert = Default; vom Aufrufer via ``felder`` überschreibbar.
_ADRESSEN_DEFAULTS: dict[str, Any] = {
    'MATCHCODE': '', 'KUNDENGRUPPE': 999, 'SPRACH_ID': 2,
    'GESCHLECHT': '-', 'KUNNUM1': '', 'KUNNUM2': '', 'NAME1': '',
    'PLZ': '', 'ORT': '', 'LAND': 'DE', 'NAME2': '', 'NAME3': '',
    'ABTEILUNG': '', 'ANREDE': '', 'STRASSE': '', 'POSTFACH': '',
    'PF_PLZ': '', 'DEFAULT_LIEFANSCHRIFT_ID': -1, 'GRUPPE': '',
    'TELE1': '', 'TELE2': '', 'FAX': '', 'FUNK': '', 'EMAIL': '',
    'EMAIL2': '', 'INTERNET': '', 'DIVERSES': '', 'BRIEFANREDE': '',
    'BLZ': '', 'KTO': '', 'BANK': '', 'IBAN': '', 'SWIFT': '',
    'KTO_INHABER': '', 'SEPA_MANDAT_ID': '', 'SEPA_LART': '',
    'SEPA_STYP': 0, 'WAEHRUNG': '€', 'UST_NUM': '', 'UID': '',
    'VERTRETER_ID': 0, 'PROVIS_PROZ': 0, 'KUN_LIEFART': -1,
    'KUN_ZAHLART': -1, 'KUN_PRLISTE': 'N', 'KUN_LIEFSPERRE': 'N',
    'LIEF_LIEFART': -1, 'LIEF_ZAHLART': -1, 'LIEF_PRLISTE': 'N',
    'LIEF_TKOSTEN': 0, 'LIEF_MBWERT': 0, 'PR_EBENE': 5,
    'BRUTTO_FLAG': 'N', 'MWST_FREI_FLAG': 'N', 'MWST_LAND_FLAG': 0,
    'KUNDENKARTE': 'N', 'SHOP_ID': -1, 'SHOP_KUNDE_ID': -1,
    'SHOP_CHANGE_FLAG': 0, 'SHOP_DEL_FLAG': 'N', 'SHOP_PASSWORD': '',
    'USERFELD_10': '', 'HAUSNR': '', 'ADRESSZUSATZ': '',
    'WERBUNG_FLAG': 'Y', 'BEREINIGEN_FLAG': 'Y', 'ENDS_FLAG': 'N',
    'EMAIL_FLAG': 1, 'EMAIL2_FLAG': 0, 'LEITWEG_ID': '',
    'E_RECHNUNG': 0, 'VOLUMEN_FLAG': 'N', 'MA_ID': -1,
    'LIEF_LIEFERSPERRE': 'N',
}
# Diese Spalten sind „voller Stamm" — vom Formular editierbar. Rest =
# CAO-Defaults (intern/Shop/Flags).
EDITIERBAR = (
    'NAME1', 'NAME2', 'NAME3', 'ANREDE', 'ABTEILUNG', 'BRIEFANREDE',
    'STRASSE', 'HAUSNR', 'ADRESSZUSATZ', 'PLZ', 'ORT', 'LAND',
    'POSTFACH', 'PF_PLZ', 'KUNNUM1', 'KUNNUM2',
    'TELE1', 'TELE2', 'FAX', 'FUNK', 'EMAIL', 'EMAIL2', 'INTERNET',
    'BLZ', 'KTO', 'BANK', 'IBAN', 'SWIFT', 'KTO_INHABER',
    'UST_NUM', 'UID', 'WAEHRUNG',
    'KUN_LIEFART', 'KUN_ZAHLART', 'KUN_PRLISTE',
    'LIEF_LIEFART', 'LIEF_ZAHLART', 'LIEF_PRLISTE',
    'LIEF_TKOSTEN', 'LIEF_MBWERT', 'PR_EBENE',
    'BRUTTO_FLAG', 'DIVERSES',
)

# ADRESSEN_LOG-Spalten (Trace-Reihenfolge, ohne HASHSUM). Wert: SQL-
# Ausdruck relativ zur ADRESSEN-Zeile ``a`` bzw. Literal/Parameter.
# LOG-only-Felder (DEB_NUM …) gibt es in ADRESSEN nicht → Literale.
_LOG_COLS = [
    'ID', 'SPRACH_ID', 'KUNNUM1', 'KUNNUM2', 'ANREDE', 'NAME1',
    'NAME2', 'NAME3', 'ABTEILUNG', 'STRASSE', 'PLZ', 'ORT', 'LAND',
    'BLZ', 'KTO', 'BANK', 'IBAN', 'SWIFT', 'KTO_INHABER',
    'SEPA_MANDAT_ID', 'SEPA_MANDAT_ERTEILT', 'SEPA_LART', 'SEPA_STYP',
    'DEB_NUM', 'KRD_NUM', 'NET_SKONTO', 'NET_TAGE', 'BRT_TAGE',
    'WAEHRUNG', 'UST_NUM', 'UID', 'PROVIS_PROZ', 'GRABATT',
    'KUN_KRDLIMIT', 'KUN_LIEFART', 'KUN_ZAHLART', 'KUN_LIEFSPERRE',
    'KUN_EORI', 'LIEF_LIEFART', 'PR_EBENE', 'BRUTTO_FLAG',
    'MWST_FREI_FLAG', 'MWST_LAND_FLAG', 'KUNDENKARTE', 'HAUSNR',
    'ADRESSZUSATZ', 'INFO', 'GEAEND', 'GEAEND_NAME',
]
# LOG-Spalte → SELECT-Ausdruck aus ADRESSEN ``a`` (oder Literal).
_LOG_SELECT = {
    'ID': 'a.REC_ID', 'SEPA_MANDAT_ERTEILT': "'1899-12-30'",
    'DEB_NUM': '0', 'KRD_NUM': '0', 'NET_SKONTO': '0',
    'NET_TAGE': '0', 'BRT_TAGE': '0', 'GRABATT': '0',
    'KUN_KRDLIMIT': '0', 'KUN_EORI': "''",
    'INFO': '%s', 'GEAEND': 'NOW()', 'GEAEND_NAME': '%s',
}


def _log_hashstring_sql() -> str:
    felder = ', '.join(
        f'IFNULL({c},0)' if c in (
            'SPRACH_ID', 'SEPA_STYP', 'DEB_NUM', 'KRD_NUM',
            'NET_SKONTO', 'NET_TAGE', 'BRT_TAGE', 'PROVIS_PROZ',
            'GRABATT', 'KUN_KRDLIMIT', 'KUN_LIEFART', 'KUN_ZAHLART',
            'LIEF_LIEFART', 'PR_EBENE', 'MWST_LAND_FLAG')
        else f"IFNULL({c},'')"
        for c in _LOG_COLS)
    return (f"SELECT CONCAT_WS('|','V1', REC_ID, {felder}) "
            f"AS HASHSTRING FROM ADRESSEN_LOG WHERE REC_ID=%s")


def _salt_pruefen() -> None:
    # Bricht klar ab statt einen LOG ohne valide HASHSUM zu schreiben.
    _cao_hashsum.get_salt(_cao_hashsum.KEY_ADRESSEN_LOG)


def _log_schreiben(cur, addr_id: int, info: str, ma_name: str) -> None:
    """ADRESSEN_LOG-Snapshot der ADRESSEN-Zeile + XT-HASHSUM
    (gekettet an den letzten ADRESSEN_LOG-Eintrag)."""
    sel = ', '.join(_LOG_SELECT.get(c, f'a.{c}') for c in _LOG_COLS)
    cur.execute(
        f"INSERT INTO ADRESSEN_LOG "
        f"  ({', '.join(_LOG_COLS)}, HASHSUM) "
        f"SELECT {sel}, '' FROM ADRESSEN a WHERE a.REC_ID=%s",
        (info[:50], (ma_name or 'CAO-XT')[:50], int(addr_id))
    )
    log_rec_id = int(cur.lastrowid)
    cur.execute(_log_hashstring_sql(), (log_rec_id,))
    hashstring = (cur.fetchone() or {}).get('HASHSTRING') or ''
    cur.execute(
        "SELECT HASHSUM FROM ADRESSEN_LOG WHERE REC_ID<%s "
        "ORDER BY REC_ID DESC LIMIT 1", (log_rec_id,))
    prev = (cur.fetchone() or {}).get('HASHSUM')
    hs = _cao_log_hashsum.compute(
        table_name='ADRESSEN_LOG', hashstring=hashstring,
        previous_hashsum=prev)
    cur.execute("UPDATE ADRESSEN_LOG SET HASHSUM=%s WHERE REC_ID=%s",
                (hs, log_rec_id))


def _werte(felder: dict[str, Any]) -> dict[str, Any]:
    """Defaults + nur erlaubte Override-Felder (Whitelist)."""
    w = dict(_ADRESSEN_DEFAULTS)
    for k, v in (felder or {}).items():
        ku = k.upper()
        if ku in _ADRESSEN_DEFAULTS and ku in EDITIERBAR:
            w[ku] = v
    return w


def adresse_anlegen(felder: dict[str, Any], *,
                     ma_name: str = 'CAO-XT') -> int:
    """Legt eine CAO-Adresse an (ADRESSEN + ADRESSEN_LOG + XT-HASHSUM).
    Returns die neue ``ADRESSEN.REC_ID``. Kein Lock (neue REC_ID)."""
    _salt_pruefen()
    w = _werte(felder)
    heute = date.today()
    w.update({'ERSTELLT': heute, 'ERST_NAME': (ma_name or 'CAO-XT')[:50],
              'GEAEND': heute, 'GEAEND_NAME': (ma_name or 'CAO-XT')[:50]})
    spalten = list(w.keys())
    with get_db_transaction() as cur:
        cur.execute(
            f"INSERT INTO ADRESSEN ({', '.join(spalten)}) "
            f"VALUES ({', '.join(['%s'] * len(spalten))})",
            [w[c] for c in spalten])
        addr_id = int(cur.lastrowid)
        _log_schreiben(cur, addr_id, 'Adresse angelegt', ma_name)
    return addr_id


def adresse_holen(rec_id: int) -> dict[str, Any] | None:
    with get_db() as cur:
        cur.execute("SELECT * FROM ADRESSEN WHERE REC_ID=%s",
                    (int(rec_id),))
        return cur.fetchone()


def adresse_aendern(rec_id: int, felder: dict[str, Any], *,
                     ma_name: str = 'CAO-XT') -> dict[str, Any]:
    """Ändert eine bestehende CAO-Adresse (nur Whitelist-Felder) +
    ADRESSEN_LOG-Snapshot + XT-HASHSUM. Record-Lock wie CAO
    (``GET_LOCK`` auf derselben Connection)."""
    _salt_pruefen()
    rec_id = int(rec_id)
    updates = {k.upper(): v for k, v in (felder or {}).items()
               if k.upper() in _ADRESSEN_DEFAULTS
               and k.upper() in EDITIERBAR}
    if not updates:
        raise ValueError('Keine änderbaren Felder übergeben.')
    with get_db_transaction() as cur:
        with cao_record_lock(cur, MODUL_ID_ADRESSEN, rec_id):
            cur.execute("SELECT REC_ID FROM ADRESSEN WHERE REC_ID=%s",
                        (rec_id,))
            if not cur.fetchone():
                raise LookupError(f'Adresse {rec_id} nicht gefunden')
            updates['GEAEND'] = date.today()
            updates['GEAEND_NAME'] = (ma_name or 'CAO-XT')[:50]
            sets = ', '.join(f'{c}=%s' for c in updates)
            cur.execute(
                f"UPDATE ADRESSEN SET {sets} WHERE REC_ID=%s",
                list(updates.values()) + [rec_id])
            _log_schreiben(cur, rec_id, 'Adresse geändert', ma_name)
    return {'ok': True, 'rec_id': rec_id}


def plz_orte(land: str, plz: str) -> list[dict[str, Any]]:
    """Ort-Vorschlag aus der CAO-``PLZ``-Tabelle (wie im Trace)."""
    with get_db() as cur:
        cur.execute(
            "SELECT LAND, PLZ, NAME, VORWAHL, BUNDESLAND "
            "  FROM PLZ WHERE LAND=%s AND PLZ=%s LIMIT 2",
            ((land or 'DE')[:2], (plz or '')[:10]))
        return list(cur.fetchall() or [])


# ── Liste + Detail-Hilfen für die Orga-Stammdaten-UI ────────────────
#
# Read-only-Queries, gebündelt hier statt verstreut in der UI, damit
# die SQLs (1:1 aus dem CAO-Trace) in einem Modul prüfbar bleiben.

_LIST_COLS = (
    'REC_ID', 'KUNNUM1', 'KUNNUM2', 'NAME1', 'NAME2', 'STRASSE',
    'PLZ', 'ORT', 'LAND', 'GRUPPE', 'TELE1', 'EMAIL')
_SORTABLE = {'NAME1', 'KUNNUM1', 'KUNNUM2', 'ORT', 'PLZ', 'REC_ID'}


def _liste_where(suche: str, gruppe_id: int | None) -> tuple[str, list[Any]]:
    """Baut WHERE-Klausel + Args fuer Suche und Gruppen-Filter."""
    teile: list[str] = []
    args: list[Any] = []
    s = (suche or '').strip()
    if s:
        like = f"%{s}%"
        teile.append("(NAME1 LIKE %s OR NAME2 LIKE %s OR KUNNUM1 LIKE %s "
                     "OR KUNNUM2 LIKE %s OR PLZ LIKE %s OR ORT LIKE %s "
                     "OR MATCHCODE LIKE %s)")
        args += [like]*7
    if gruppe_id is not None:
        teile.append("KUNDENGRUPPE=%s")
        args.append(int(gruppe_id))
    where = ('WHERE ' + ' AND '.join(teile)) if teile else ''
    return where, args


def adressen_liste(suche: str = '', *,
                   gruppe_id: int | None = None,
                   sort: str = 'NAME1', sort_dir: str = 'asc',
                   limit: int | None = None,
                   offset: int = 0) -> list[dict[str, Any]]:
    """Adressliste mit Volltext-Suche und optionalem Gruppen-Filter.

    Sortierschlüssel: ``NAME1`` (Default), ``KUNNUM1``, ``KUNNUM2``,
    ``ORT``, ``PLZ``, ``REC_ID``. Andere Werte → Fallback auf NAME1.
    ``limit=None`` heißt: kein LIMIT (alle Treffer).
    """
    if sort not in _SORTABLE:
        sort = 'NAME1'
    direction = 'DESC' if str(sort_dir).lower() == 'desc' else 'ASC'
    where, args = _liste_where(suche, gruppe_id)
    sql = (f"SELECT {', '.join(_LIST_COLS)} FROM ADRESSEN "
           f"{where} ORDER BY {sort} {direction}")
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        args += [int(limit), int(offset)]
    with get_db() as cur:
        cur.execute(sql, args)
        return list(cur.fetchall() or [])


def adressen_zaehlen(suche: str = '', *,
                     gruppe_id: int | None = None) -> int:
    where, args = _liste_where(suche, gruppe_id)
    with get_db() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM ADRESSEN {where}", args)
        row = cur.fetchone() or {'n': 0}
        return int(row.get('n', 0))


def merkmale_zu_adresse(addr_id: int) -> list[dict[str, Any]]:
    """Alle Merkmale + Flag ob die Adresse sie hat (zugewiesene zuerst)."""
    sql = """SELECT AM.MERKMAL_ID, AM.NAME,
                    CASE WHEN ATM.MERKMAL_ID=AM.MERKMAL_ID
                         THEN 1 ELSE 0 END AS FLAG
               FROM ADRESSEN_MERK AM
               LEFT OUTER JOIN ADRESSEN_TO_MERK ATM
                 ON ATM.ADDR_ID=%s AND ATM.MERKMAL_ID=AM.MERKMAL_ID
              ORDER BY FLAG DESC, AM.NAME ASC"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id),))
        return list(cur.fetchall() or [])


def lieferadressen(addr_id: int) -> list[dict[str, Any]]:
    """Liefer-/Standort-Adressen + USt-IdNr-Prüf-Flag."""
    sql = """SELECT AL.*,
                    TRIM(CONCAT_WS(' ', AL.STRASSE, TRIM(AL.HAUSNR),
                                        TRIM(AL.ADRESSZUSATZ))) AS STRASSEZUSATZ,
                    CASE WHEN U.ERROR_CODE=200 THEN 1
                         WHEN U.ERROR_CODE IN (216,218,219,223) THEN 2
                         WHEN U.ERROR_CODE>200 AND U.ERROR_CODE
                              NOT IN (216,218,219,223) THEN 3
                         ELSE -1 END AS PRUEFUID
               FROM ADRESSEN_LIEF AL
               LEFT JOIN ADRESSEN_UID_PRUEF U
                 ON AL.REC_ID=U.LIEF_ADDR_ID AND U.ADDR_ID=AL.ADDR_ID
              WHERE AL.ADDR_ID=%s
              ORDER BY NAME1 ASC"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id),))
        return list(cur.fetchall() or [])


def ansprechpartner(addr_id: int) -> list[dict[str, Any]]:
    sql = """SELECT *,
                    TRIM(CONCAT_WS(' ', STRASSE, TRIM(HAUSNR),
                                        TRIM(ADRESSZUSATZ))) AS STRASSEZUSATZ
               FROM ADRESSEN_ASP
              WHERE ADDR_ID=%s
              ORDER BY FUNKTION"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id),))
        return list(cur.fetchall() or [])


def sonderpreise(addr_id: int, preis_typ: int = 3) -> list[dict[str, Any]]:
    """Adress-spezifische Artikelpreise (Default ``PREIS_TYP=3`` = Sonder)."""
    sql = """SELECT A.MENGE_AKT, A.ARTNUM, A.KURZNAME, A.EK_PREIS,
                    A.VK1, A.VK2, A.VK3, A.VK4, A.VK5, A.PR_EINHEIT,
                    M.BEZEICHNUNG AS ME_EINHEIT,
                    AP.ARTIKEL_ID, AP.ADRESS_ID, AP.PREIS_TYP,
                    AP.BESTNUM, AP.VPE, AP.PREIS, AP.RABATT,
                    AP.GEAEND, AP.GEAEND_NAME
               FROM ARTIKEL_PREIS AP
               LEFT JOIN ARTIKEL A ON A.REC_ID=AP.ARTIKEL_ID
               LEFT JOIN MENGENEINHEIT M ON A.ME_ID=M.REC_ID
              WHERE AP.ADRESS_ID=%s AND AP.PREIS_TYP=%s
              ORDER BY A.ARTNUM ASC"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id), int(preis_typ)))
        return list(cur.fetchall() or [])


def wgr_rabatte(addr_id: int) -> list[dict[str, Any]]:
    """Warengruppen-Rabatte der Adresse (ADRESSEN_WGR_RABATT)."""
    sql = """SELECT R.WGR_ID, R.RABATT, R.GEAEND, R.GEAEND_NAME, R.INFO,
                    W.NAME AS WGR_NAME
               FROM ADRESSEN_WGR_RABATT R
               LEFT JOIN WARENGRUPPEN W ON W.ID=R.WGR_ID
              WHERE R.ADDR_ID=%s
              ORDER BY W.NAME"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id),))
        return list(cur.fetchall() or [])


def links_zu_adresse(addr_id: int) -> list[dict[str, Any]]:
    """Verknüpfte Dateien (LINK-Tabelle, MODUL_ID=50 = ADRESSEN)."""
    sql = """SELECT * FROM LINK
              WHERE MODUL_ID=50 AND REC_ID=%s
              ORDER BY DATEI, PFAD"""
    with get_db() as cur:
        cur.execute(sql, (int(addr_id),))
        return list(cur.fetchall() or [])


# QUELLE-Code Beschreibungen (CAO-Konvention) für die Anzeige.
QUELLE_LABEL = {
    '1':  'Rechnung',
    '2':  'Lieferschein',
    '3':  'Gutschrift',
    '4':  'Storno-Rechnung',
    '6':  'EK-Bestellung',
    '7':  'Preisanfrage',
    '11': 'Storno-Rechnung',
    '12': 'EDI-Lieferschein',
    '16': 'EK-Bestellung (offen)',
    '17': 'Preisanfrage (offen)',
}


def vorgangs_historie(addr_id: int) -> list[dict[str, Any]]:
    """Vereinigte Vorgangshistorie: Journal + Lieferschein + EK-Bestellung
    + Preisanfrage (Quellen 1:1 aus dem CAO-Trace).

    Rückgabe-Spalten (gleich für alle Quellen, damit sich die UI in einer
    Tabelle abbilden lässt):
      REC_ID, QUELLE (string), BELEGNUM, BELEGDATUM, KUN_NAME, ADDR_ID,
      LIEF_ADDR_ID, NSUMME, MSUMME, BSUMME, STADIUM, PROJEKT, ORGNUM,
      WAEHRUNG, LIEFANSCHR. Sortierung: BELEGDATUM absteigend.
    """
    aid = int(addr_id)
    q_journal = """
        SELECT JOURNAL.REC_ID,
               CONCAT_WS('', JOURNAL.QUELLE) AS QUELLE,
               CASE WHEN JOURNAL.VERSNR>=1 AND JOURNAL.QUELLE IN (1,11)
                    THEN CONCAT_WS('-', JOURNAL.VRENUM, JOURNAL.VERSNR)
                    ELSE JOURNAL.VRENUM END AS BELEGNUM,
               JOURNAL.RDATUM AS BELEGDATUM,
               CONCAT_WS(' ', JOURNAL.KUN_NAME1, JOURNAL.KUN_NAME2,
                              JOURNAL.KUN_NAME3) AS KUN_NAME,
               JOURNAL.ADDR_ID, JOURNAL.LIEF_ADDR_ID,
               JOURNAL.NSUMME, JOURNAL.MSUMME, JOURNAL.BSUMME,
               JOURNAL.STADIUM, JOURNAL.PROJEKT, JOURNAL.ORGNUM,
               JOURNAL.WAEHRUNG,
               CONCAT(TRIM(CONCAT_WS(' ', AD.ANREDE, AD.NAME1,
                                          AD.NAME2, AD.NAME3)),
                      ', ', AD.STRASSE, ', ', AD.LAND, ' ',
                      AD.PLZ, ' ', AD.ORT) AS LIEFANSCHR
          FROM JOURNAL
          LEFT JOIN JOURNALPOS JP ON JP.JOURNAL_ID=JOURNAL.REC_ID
          LEFT OUTER JOIN LIEFERSCHEIN_POS LP
            ON LP.RECHPOS_ID=JP.REC_ID
          LEFT OUTER JOIN LIEFERSCHEIN L ON L.REC_ID=LP.LIEFERSCHEIN_ID
          LEFT OUTER JOIN ADRESSEN_LIEF AD
            ON AD.REC_ID=JOURNAL.LIEF_ADDR_ID
         WHERE JOURNAL.ADDR_ID=%s
           AND JOURNAL.QUELLE>0
           AND JOURNAL.STADIUM<>120
           AND JOURNAL.TERM_ID<>99999
           AND YEAR(JOURNAL.RDATUM) BETWEEN 1900 AND 2300
           AND JP.TOP_POS_ID=-1
      GROUP BY JOURNAL.REC_ID"""
    q_liefer = """
        SELECT L.REC_ID,
               CASE WHEN L.EDI_FLAG='N' THEN '2' ELSE '12' END AS QUELLE,
               L.VLSNUM AS BELEGNUM, L.LDATUM AS BELEGDATUM,
               CONCAT_WS(' ', L.KUN_NAME1, L.KUN_NAME2,
                              L.KUN_NAME3) AS KUN_NAME,
               L.ADDR_ID, L.LIEF_ADDR_ID,
               L.NSUMME, L.MSUMME, L.BSUMME,
               CASE WHEN L.STORNO_FLAG='Y' THEN 127
                    WHEN L.STATUS_FLAG=2 THEN 2
                    WHEN COUNT(LP.REC_ID)=SUM(LP.RECHPOS_ID=-1) THEN 1
                    WHEN SUM(LP.RECHPOS_ID=-1)>0 THEN 5
                    WHEN SUM(LP.RECHPOS_ID=-1)=0 THEN 9
                    ELSE 1 END AS STADIUM,
               L.PROJEKT, L.ORGNUM, L.WAEHRUNG, '-' AS LIEFANSCHR
          FROM LIEFERSCHEIN L
          LEFT OUTER JOIN LIEFERSCHEIN_POS LP
            ON LP.LIEFERSCHEIN_ID=L.REC_ID
            AND LP.ARTIKELTYP IN ('N','S','L','K','F','P')
         WHERE L.ADDR_ID=%s
           AND YEAR(L.LDATUM) BETWEEN 1900 AND 2300
           AND LP.TOP_POS_ID=-1
      GROUP BY L.REC_ID"""
    q_bestell = """
        SELECT REC_ID,
               CASE WHEN STADIUM=0 THEN '16' ELSE '6' END AS QUELLE,
               BELEGNUM, BELEGDATUM,
               CONCAT_WS(' ', KUN_NAME1, KUN_NAME2,
                              KUN_NAME3) AS KUN_NAME,
               ADDR_ID, LIEF_ADDR_ID,
               NSUMME, MSUMME, BSUMME, STADIUM, PROJEKT, ORGNUM, WAEHRUNG,
               '-' AS LIEFANSCHR
          FROM EKBESTELL
         WHERE PREISANFRAGE='N' AND ADDR_ID=%s
           AND YEAR(BELEGDATUM) BETWEEN 1900 AND 2300"""
    q_preisanfr = """
        SELECT REC_ID,
               CASE WHEN STADIUM=0 THEN '17' ELSE '7' END AS QUELLE,
               BELEGNUM, BELEGDATUM,
               CONCAT_WS(' ', KUN_NAME1, KUN_NAME2,
                              KUN_NAME3) AS KUN_NAME,
               ADDR_ID, LIEF_ADDR_ID,
               NSUMME, MSUMME, BSUMME, STADIUM, PROJEKT, ORGNUM, WAEHRUNG,
               '-' AS LIEFANSCHR
          FROM EKBESTELL
         WHERE PREISANFRAGE='Y' AND ADDR_ID=%s
           AND YEAR(BELEGDATUM) BETWEEN 1900 AND 2300"""
    alles: list[dict[str, Any]] = []
    with get_db() as cur:
        for q in (q_journal, q_liefer, q_bestell, q_preisanfr):
            cur.execute(q, (aid,))
            alles.extend(cur.fetchall() or [])
    # BELEGDATUM kann date ODER datetime sein (LIEFERSCHEIN.LDATUM ist
    # datetime, JOURNAL.RDATUM ist date) — als ISO-String sortieren,
    # damit Python die nicht typabhängig vergleicht.
    def _key(r):
        v = r.get('BELEGDATUM')
        return v.isoformat() if v else '0000-00-00'
    alles.sort(key=_key, reverse=True)
    return alles
