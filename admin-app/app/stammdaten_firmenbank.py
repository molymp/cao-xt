"""
CAO-Stammdaten: Firmen-Bankkonten – Read-only Data-Access.

Spiegelt den Tab *Firmen-Bankkonten* aus cao_admin.exe (DFM:
``SetupForm/FirBankTab``). Das ist kein eigenes Tabellen-Modell,
sondern ein Filter auf ``FIBU_KONTEN`` mit ``KONTOART = 20``
(SEPA/Giro), gruppiert nach ``KONTORAHMEN``.

Die Delphi-Feldnamen im DFM sind Aliase auf FIBU_KONTEN-Spalten::

    FIBU_KTO      -> KONTO
    kurzbez       -> KONTONAME      (intern oft "Hausbank", "Postbank")
    inhaber       -> KONTO_INHABER
    blz           -> BANK_BLZ
    KTONR         -> BANK_KONTO
    (weitere 1:1: KONTORAHMEN, BANK_NAME, IBAN, SWIFT, STANDARD)

Zweck in CAO: fuer SEPA-Zahlungen, Rechnungsfuesse (IBAN/SWIFT) und
die Auswahl der Default-Bankverbindung bei Buchungen.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_PFLICHT = ('KONTORAHMEN', 'KONTO', 'KONTONAME')
_OPTIONAL = (
    'KONTO_INHABER', 'BANK_NAME', 'BANK_BLZ', 'BANK_KONTO',
    'IBAN', 'SWIFT', 'STANDARD', 'INFO',
)

# Die CAO-Marker-Wert fuer Bankkonto in FIBU_KONTEN.KONTOART
_KONTOART_BANK = 20

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der FIBU_KONTEN-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'FIBU_KONTEN'
        """
    )
    _spalten_cache = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache


def _ja(wert: Any) -> bool:
    return str(wert or '').strip().upper() == 'Y'


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _memo_text(roh: Any) -> str:
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def liste() -> dict[str, Any]:
    """Liefert alle Firmen-Bankkonten (KONTOART=20 in FIBU_KONTEN).

    Rueckgabe::

        {
          'rahmen': ['SKR03', ...],        # alphabetisch
          'eintraege': [
            {
              'rahmen':    str,
              'konto':     int,            # Fibu-Kontonummer
              'kurzbez':   str,            # KONTONAME
              'inhaber':   str,
              'bank':      str,            # BANK_NAME
              'blz':       str,
              'ktonr':     str,
              'iban':      str,
              'swift':     str,
              'standard':  bool,           # Y = Default-Bankverbindung
              'info':      str,
            },
            ...
          ]
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        felder = list(_PFLICHT) + [f for f in _OPTIONAL if f in vorhanden]
        # KONTOART ist fuer den Filter noetig
        if 'KONTOART' not in vorhanden:
            # Ohne KONTOART keine Unterscheidung moeglich -> leer zurueck
            return {'rahmen': [], 'eintraege': []}
        cur.execute(
            f"SELECT {', '.join(felder)} FROM FIBU_KONTEN "
            f"WHERE KONTOART = %s "
            f"ORDER BY KONTORAHMEN, KONTO",
            (_KONTOART_BANK,),
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    rahmen: set[str] = set()
    for r in rows:
        rah = _str(r.get('KONTORAHMEN'))
        rahmen.add(rah)
        eintraege.append({
            'rahmen':   rah,
            'konto':    _int_oder_none(r.get('KONTO')),
            'kurzbez':  _str(r.get('KONTONAME')),
            'inhaber':  _str(r.get('KONTO_INHABER')),
            'bank':     _str(r.get('BANK_NAME')),
            'blz':      _str(r.get('BANK_BLZ')),
            'ktonr':    _str(r.get('BANK_KONTO')),
            'iban':     _str(r.get('IBAN')),
            'swift':    _str(r.get('SWIFT')),
            'standard': _ja(r.get('STANDARD')),
            'info':     _memo_text(r.get('INFO')),
        })

    return {
        'rahmen':    sorted(rahmen),
        'eintraege': eintraege,
    }
