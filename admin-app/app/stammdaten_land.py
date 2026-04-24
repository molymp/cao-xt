"""
CAO-Stammdaten: Laender + MwSt – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``LAND`` fuer die Admin-Ansicht. In
cao_admin.exe ist das die Seite *Einstellungen → Laender* (mit
MwSt-Satzen als Unterseite).

Schema (CAO-Faktura 1.5, nicht alle Spalten sind in jeder DB
vorhanden – wir introspekten vorher)::

    ID            char(2/3)    ISO-2 Code ('DE', 'AT', 'CH') – PK
    NAME          varchar      Deutschland, Oesterreich, ...
    ISO_CODE_3    char(3)      DEU, AUT, CHE
    VORWAHL       varchar      Telefon-Vorwahl ('+49')
    WAEHRUNG      varchar      EUR, CHF, ...
    SPRACHE       varchar      DE, EN, ...
    POST_CODE     varchar      PLZ-Format/Muster
    EU_LAND       char(1)      'Y' = EU-Mitglied
    FORMAT        smallint     Adressformat-Typ (Delphi-intern)
    NAME2         varchar      alternativer Name (Englisch o.Ae.)
    MWST_1        float        Steuersatz 1 (Normalsatz, meist 19.0)
    MWST_2        float        Steuersatz 2 (ermaessigt, meist 7.0)
    MWST_3        float        Steuersatz 3 (frei waehlbar)
    ERLOESKONTO   int          Default-Erloeskonto fuer dieses Land
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_PFLICHT = ('ID', 'NAME')
_OPTIONAL = (
    'ISO_CODE_3', 'VORWAHL', 'WAEHRUNG', 'SPRACHE', 'POST_CODE',
    'EU_LAND', 'FORMAT', 'NAME2',
    'MWST_1', 'MWST_2', 'MWST_3', 'ERLOESKONTO',
)

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der LAND-Tabelle (Cache)."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'LAND'
        """
    )
    _spalten_cache = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache


def _mwst(wert: Any) -> float | None:
    """Leerer/None MwSt-Satz -> None (fuer Unterscheidung 'nicht gepflegt'
    vs. 0.0)."""
    if wert is None:
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _ja(wert: Any) -> bool:
    return str(wert or '').strip().upper() == 'Y'


def liste() -> list[dict[str, Any]]:
    """Liefert alle LAND-Zeilen, sortiert nach NAME.

    Rueckgabe pro Eintrag::

        {
          'id':           str,              # ISO-2 ('DE')
          'name':         str,
          'name2':        str,              # leer falls Spalte fehlt
          'iso3':         str,
          'vorwahl':      str,
          'waehrung':     str,
          'sprache':      str,
          'post_code':    str,              # PLZ-Format-Muster
          'eu_land':      bool,
          'format':       int | None,
          'mwst':         [m1|None, m2|None, m3|None],
          'erloeskonto':  int | None,
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        felder = list(_PFLICHT) + [f for f in _OPTIONAL if f in vorhanden]
        sort_spalte = 'NAME' if 'NAME' in vorhanden else 'ID'
        cur.execute(
            f"SELECT {', '.join(felder)} FROM LAND ORDER BY {sort_spalte}"
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        fmt_roh = r.get('FORMAT')
        try:
            fmt = int(fmt_roh) if fmt_roh is not None else None
        except (TypeError, ValueError):
            fmt = None
        ek_roh = r.get('ERLOESKONTO')
        try:
            ek = int(ek_roh) if ek_roh is not None else None
        except (TypeError, ValueError):
            ek = None

        eintraege.append({
            'id':          (r.get('ID') or '').strip(),
            'name':        (r.get('NAME') or '').strip(),
            'name2':       (r.get('NAME2') or '').strip(),
            'iso3':        (r.get('ISO_CODE_3') or '').strip(),
            'vorwahl':     (r.get('VORWAHL') or '').strip(),
            'waehrung':    (r.get('WAEHRUNG') or '').strip(),
            'sprache':     (r.get('SPRACHE') or '').strip(),
            'post_code':   (r.get('POST_CODE') or '').strip(),
            'eu_land':     _ja(r.get('EU_LAND')),
            'format':      fmt,
            'mwst':        [_mwst(r.get('MWST_1')),
                            _mwst(r.get('MWST_2')),
                            _mwst(r.get('MWST_3'))],
            'erloeskonto': ek,
        })
    return eintraege
