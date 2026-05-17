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
