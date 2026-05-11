"""
Feiertage Bayern als Map date -> Name.

Wir nutzen die ``holidays``-Bibliothek (offline, MIT-Lizenz).
Bayern hat einige Sonder-Feiertage (Heilige Drei Koenige, Fronleichnam,
Mariae Himmelfahrt, Allerheiligen), die in subdiv='BY' beruecksichtigt
sind.

Cache pro Jahr, weil die Konstruktion ein paar ms dauert.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

try:
    import holidays as _holidays
except ImportError:  # pragma: no cover
    _holidays = None  # type: ignore

_cache: dict[int, dict[_dt.date, str]] = {}


def fuer_jahr(jahr: int) -> dict[_dt.date, str]:
    if jahr in _cache:
        return _cache[jahr]
    if _holidays is None:
        _cache[jahr] = {}
        return _cache[jahr]
    by = _holidays.Germany(years=[jahr], subdiv='BY')
    _cache[jahr] = {d: n for d, n in by.items()}
    return _cache[jahr]


def ist_feiertag(d: _dt.date) -> bool:
    return d in fuer_jahr(d.year)


def name(d: _dt.date) -> Optional[str]:
    return fuer_jahr(d.year).get(d)


def alle_im_zeitraum(von: _dt.date, bis: _dt.date) -> dict[_dt.date, str]:
    """Inklusiv-Zeitraum."""
    result: dict[_dt.date, str] = {}
    for jahr in range(von.year, bis.year + 1):
        for d, n in fuer_jahr(jahr).items():
            if von <= d <= bis:
                result[d] = n
    return result
