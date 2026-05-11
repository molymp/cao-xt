"""
Schulferien Bayern: Loader fuer XT_SCHULFERIEN_BY.

Primaere Quelle: OpenHolidaysAPI (https://www.openholidaysapi.org/),
freier Open-Data-Service, kein Key. Endpunkt:

  GET https://openholidaysapi.org/SchoolHolidays
       ?countryIsoCode=DE&subdivisionCode=DE-BY
       &validFrom=YYYY-MM-DD&validTo=YYYY-MM-DD

Antwort: Liste von Objekten mit ``startDate``, ``endDate``, ``name``
(Liste mit language=de Eintrag), z.B. "Sommerferien".

Wir cachen die Daten dauerhaft in XT_SCHULFERIEN_BY. Re-Loads sind
idempotent (UNIQUE auf (von_datum, bis_datum, name)).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import urllib.request
import urllib.parse

from common.db import get_db

log = logging.getLogger(__name__)

_API_URL = 'https://openholidaysapi.org/SchoolHolidays'


def _fetch(start: _dt.date, ende: _dt.date,
           subdiv: str = 'DE-BY') -> list[dict]:
    params = {
        'countryIsoCode':    'DE',
        'subdivisionCode':   subdiv,
        'languageIsoCode':   'DE',
        'validFrom':         start.isoformat(),
        'validTo':           ende.isoformat(),
    }
    url = f'{_API_URL}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(
        url, headers={'User-Agent': 'CAO-XT-Backwaren/1.0',
                       'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f'HTTP {r.status}')
        return json.loads(r.read().decode('utf-8'))


def _name_aus_eintrag(entry: dict) -> str:
    """openholidaysapi liefert name als Liste [{language, text}]."""
    names = entry.get('name') or []
    if isinstance(names, list):
        for n in names:
            if n.get('language') == 'DE':
                return n.get('text') or ''
        if names:
            return (names[0].get('text') or '')
    if isinstance(names, str):
        return names
    return ''


def jahr_laden(jahr: int) -> int:
    """Laedt alle Schulferien-Perioden fuer Bayern in ``jahr`` und
    schreibt sie nach XT_SCHULFERIEN_BY. Liefert die Anzahl neu
    gespeicherter Eintraege (Re-Inserts werden via UNIQUE ignoriert).
    """
    start = _dt.date(jahr, 1, 1)
    ende  = _dt.date(jahr, 12, 31)
    entries = _fetch(start, ende)
    if not entries:
        log.warning('Keine Ferien-Daten fuer %d', jahr)
        return 0
    sql = """
        INSERT IGNORE INTO XT_SCHULFERIEN_BY
          (jahr, name, von_datum, bis_datum, quelle)
        VALUES (%s, %s, %s, %s, %s)
    """
    params = []
    for e in entries:
        name = _name_aus_eintrag(e)[:60]
        try:
            v = _dt.date.fromisoformat(e['startDate'])
            b = _dt.date.fromisoformat(e['endDate'])
        except (KeyError, ValueError):
            continue
        params.append((jahr, name, v, b, 'openholidaysapi'))
    with get_db() as cur:
        cur.executemany(sql, params)
    return len(params)


def ist_ferien(d: _dt.date) -> bool:
    """Schnell-Check: liegt ``d`` in einer Bayern-Schulferien-Periode?"""
    with get_db() as cur:
        cur.execute("""
            SELECT 1 FROM XT_SCHULFERIEN_BY
            WHERE %s BETWEEN von_datum AND bis_datum
            LIMIT 1
        """, (d,))
        return cur.fetchone() is not None


def alle_im_zeitraum(von: _dt.date, bis: _dt.date) -> set[_dt.date]:
    """Liefert die Menge aller Ferien-Tage im Zeitraum (inkl.)."""
    with get_db() as cur:
        cur.execute("""
            SELECT von_datum, bis_datum FROM XT_SCHULFERIEN_BY
            WHERE NOT (bis_datum < %s OR von_datum > %s)
        """, (von, bis))
        result: set[_dt.date] = set()
        for r in cur.fetchall() or []:
            v = max(r['von_datum'], von)
            b = min(r['bis_datum'], bis)
            d = v
            while d <= b:
                result.add(d)
                d += _dt.timedelta(days=1)
        return result
