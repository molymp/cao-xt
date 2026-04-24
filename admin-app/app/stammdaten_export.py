"""
CAO-Stammdaten: Export-Queries – Read-only Data-Access.

Die EXPORT-Tabelle haelt benutzerdefinierte Report-/Export-Definitionen
(SQL + Felder + Format). Gruppiert werden sie ueber EXPORT_KATEGORIEN,
Laufzeit-Parameter stehen in EXPORT_PARAMETER (als Pro-Mitarbeiter-
Defaults).

Schema (gekuerzt)::

    EXPORT
      ID               PK
      KURZBEZ          Name des Reports
      INFO             Memo
      QUERY            SQL-Code
      FELDER           optionale Felder (Memo)
      FORMULAR         LONGBLOB (Fast-Report-Template) – nicht gelesen
      FORMAT           'XLS', 'CSV', 'PDF', 'FR ' (FastReport), ...
      FILENAME         Default-Dateiname
      EINSTELLUNGEN    sonstige Config (Memo)
      LAST_CHANGE      timestamp
      CHANGE_NAME      wer zuletzt editiert hat
      STATISTIK_FLAG   0/1 – in Statistik-Menue einblenden?
      SUBKATEGORIE     sekundaere Gruppierung (freier Text)
      KATEGORIE_ID     FK -> EXPORT_KATEGORIEN.REC_ID
      MA_ID            Besitzer-Mitarbeiter (-1 = global)

    EXPORT_KATEGORIEN
      REC_ID           PK
      KURZNAME         'Rechnungen', 'DATEV', ...
      BESCHREIBUNG     Memo

Wir lesen NICHT die FORMULAR-BLOBs aus (koennen mehrere MB sein),
zeigen aber deren Vorhandensein + Groesse.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_spalten_cache: dict[str, set[str]] = {}


def _spalten(cur, tabelle: str) -> set[str]:
    if tabelle in _spalten_cache:
        return _spalten_cache[tabelle]
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (tabelle,),
    )
    _spalten_cache[tabelle] = {
        r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache[tabelle]


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def _memo(roh: Any) -> str:
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def liste() -> dict[str, Any]:
    """Liefert alle Export-Reports + Kategorien.

    Rueckgabe::

        {
          'kategorien': [
            {'id': int, 'name': str, 'beschreibung': str, 'anzahl': int},
            ...
          ],
          'eintraege': [
            {
              'id':             int,
              'kurzbez':        str,
              'kategorie_id':   int | None,
              'subkategorie':   str,
              'format':         str,          # 'XLS', 'CSV', 'PDF', 'FR '
              'filename':       str,
              'info':           str,
              'query_kurz':     str,          # erste ~200 Zeichen
              'felder_kurz':    str,          # erste ~200 Zeichen
              'statistik':      bool,
              'ma_id':          int | None,   # -1 = global
              'last_change':    str,          # ISO
              'change_name':    str,
              'hat_formular':   bool,
              'formular_bytes': int,
            },
            ...
          ]
        }
    """
    with get_db() as cur:
        exp_vorhanden = _spalten(cur, 'EXPORT')
        if not exp_vorhanden:
            return {'kategorien': [], 'eintraege': []}

        # Kategorien (falls Tabelle vorhanden)
        kategorien_rows: list[dict[str, Any]] = []
        if _spalten(cur, 'EXPORT_KATEGORIEN'):
            cur.execute(
                "SELECT REC_ID, KURZNAME, BESCHREIBUNG "
                "FROM EXPORT_KATEGORIEN ORDER BY REC_ID"
            )
            kategorien_rows = cur.fetchall() or []

        # Reports – FORMULAR separat als Laenge, nicht als BLOB
        felder = ['ID', 'KURZBEZ', 'INFO', 'QUERY', 'FELDER',
                  'FORMAT', 'FILENAME', 'LAST_CHANGE', 'CHANGE_NAME',
                  'STATISTIK_FLAG', 'SUBKATEGORIE', 'KATEGORIE_ID',
                  'MA_ID']
        felder = [f for f in felder if f in exp_vorhanden]
        has_formular = 'FORMULAR' in exp_vorhanden
        select_extra = (
            ', OCTET_LENGTH(FORMULAR) AS FORMULAR_LEN'
            if has_formular else ''
        )
        cur.execute(
            f"SELECT {', '.join(felder)}{select_extra} "
            f"FROM EXPORT ORDER BY KATEGORIE_ID, KURZBEZ"
        )
        rows = cur.fetchall() or []

    # Counts pro Kategorie
    anz_pro_kat: dict[int, int] = {}
    for r in rows:
        kid = _int_oder_none(r.get('KATEGORIE_ID'))
        if kid is not None:
            anz_pro_kat[kid] = anz_pro_kat.get(kid, 0) + 1

    kategorien = []
    seen_ids: set[int] = set()
    for k in kategorien_rows:
        kid = _int_oder_none(k.get('REC_ID'))
        if kid is None:
            continue
        seen_ids.add(kid)
        kategorien.append({
            'id':           kid,
            'name':         _str(k.get('KURZNAME')),
            'beschreibung': _memo(k.get('BESCHREIBUNG')),
            'anzahl':       anz_pro_kat.get(kid, 0),
        })
    # Reports mit unbekannter Kategorie -> virtuelle "Ohne Kategorie"
    verwaiste = [r for r in rows
                 if _int_oder_none(r.get('KATEGORIE_ID'))
                    not in seen_ids]
    if verwaiste:
        kategorien.append({
            'id':           None,
            'name':         '(ohne / unbekannt)',
            'beschreibung': '',
            'anzahl':       len(verwaiste),
        })

    def _kurz(roh: Any, max_len: int = 200) -> str:
        t = _memo(roh)
        if len(t) <= max_len:
            return t
        return t[:max_len].rstrip() + ' …'

    eintraege = []
    for r in rows:
        eintraege.append({
            'id':           _int_oder_none(r.get('ID')),
            'kurzbez':      _str(r.get('KURZBEZ')),
            'kategorie_id': _int_oder_none(r.get('KATEGORIE_ID')),
            'subkategorie': _str(r.get('SUBKATEGORIE')),
            'format':       _str(r.get('FORMAT')),
            'filename':     _str(r.get('FILENAME')),
            'info':         _memo(r.get('INFO')),
            'query_kurz':   _kurz(r.get('QUERY')),
            'felder_kurz':  _kurz(r.get('FELDER')),
            'statistik':    bool(_int_oder_none(r.get('STATISTIK_FLAG'))),
            'ma_id':        _int_oder_none(r.get('MA_ID')),
            'last_change':  (
                r.get('LAST_CHANGE').isoformat()
                if hasattr(r.get('LAST_CHANGE'), 'isoformat')
                else _str(r.get('LAST_CHANGE'))),
            'change_name':  _str(r.get('CHANGE_NAME')),
            'hat_formular':
                bool(_int_oder_none(r.get('FORMULAR_LEN'))),
            'formular_bytes':
                _int_oder_none(r.get('FORMULAR_LEN')) or 0,
        })

    return {'kategorien': kategorien, 'eintraege': eintraege}
