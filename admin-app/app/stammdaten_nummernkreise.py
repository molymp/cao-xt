"""
CAO-Stammdaten: Nummernkreise (REGISTRY 'MAIN\\NUMBERS') – Read-only.

CAO speichert Nummernkreise nicht als eigene Tabelle, sondern als
Zeilen in der generischen REGISTRY mit MAINKEY='MAIN\\NUMBERS'.
Jede Zeile ist ein Nummernkreis (VK-RECH, EK-BEST, KUNNUM, ...).

Spalten-Belegung::

    NAME       Kreis-Key (VK-RECH, KUNNUM, ...)
    VAL_CHAR   Format-Maske ('000000' oder '"EDI-"000000')
    VAL_INT    Sort-Position (steuert UI-Reihenfolge)
    VAL_INT2   naechster freier/aktueller Zaehler
    VAL_INT3   laenge des numerischen Teils
    READONLY   'Y' -> durch cao_admin geschuetzt

Zusaetzlich haelt CAO in NUMMERN_LOG einen Hash-geketteten Log aller
je ausgegebenen Nummern (HASHSUM fuer Revisionssicherheit). Wir
zaehlen hier nur die Gesamt-Zahl der Logs fuer Statistik.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

# REGISTRY-MAINKEY fuer Nummernkreise (ein Backslash in der DB)
_MAINKEY = 'MAIN\\NUMBERS'

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
    spalten = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    _spalten_cache[tabelle] = spalten
    return spalten


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def _ja(wert: Any) -> bool:
    return str(wert or '').strip().upper() == 'Y'


def liste() -> dict[str, Any]:
    """Liefert alle Nummernkreise + Log-Zaehler.

    Rueckgabe::

        {
          'eintraege': [
            {
              'key':         str,       # NAME
              'maske':       str,       # VAL_CHAR
              'naechste':    int | None,# VAL_INT2 (aktueller Zaehler)
              'laenge':      int | None,# VAL_INT3
              'sort':        int | None,# VAL_INT
              'readonly':    bool,
            },
            ...
          ],
          'log_total': int,             # Gesamtzahl der NUMMERN_LOG-Zeilen
        }
    """
    with get_db() as cur:
        reg_vorhanden = _spalten(cur, 'REGISTRY')
        if not reg_vorhanden:
            return {'eintraege': [], 'log_total': 0}

        cur.execute(
            "SELECT NAME, VAL_CHAR, VAL_INT, VAL_INT2, VAL_INT3, READONLY "
            "FROM REGISTRY WHERE MAINKEY = %s "
            "ORDER BY VAL_INT, NAME",
            (_MAINKEY,),
        )
        rows = cur.fetchall() or []

        log_total = 0
        if _spalten(cur, 'NUMMERN_LOG'):
            cur.execute("SELECT COUNT(*) AS ANZ FROM NUMMERN_LOG")
            r = (cur.fetchall() or [{'ANZ': 0}])[0]
            log_total = _int_oder_none(r.get('ANZ')) or 0

    eintraege = [
        {
            'key':      _str(r.get('NAME')),
            'maske':    _str(r.get('VAL_CHAR')),
            'sort':     _int_oder_none(r.get('VAL_INT')),
            'naechste': _int_oder_none(r.get('VAL_INT2')),
            'laenge':   _int_oder_none(r.get('VAL_INT3')),
            'readonly': _ja(r.get('READONLY')),
        }
        for r in rows
    ]
    return {'eintraege': eintraege, 'log_total': log_total}
