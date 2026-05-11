"""
Wetter-Loader fuer den Standort Habach (47.7404N / 11.3036E).

Quelle: Open-Meteo Archive (historisch) und /forecast (Vorhersage).
Lizenz: CC-BY 4.0, kein API-Key noetig, weltweite Coverage.

Daten werden in XT_WETTER_HABACH gecacht. Re-Loads sind idempotent
(REPLACE INTO).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional

from common.db import get_db

log = logging.getLogger(__name__)

# Habach, Lkr. Weilheim-Schongau, Oberbayern (vom User bestaetigt)
LAT = 47.7404
LON = 11.3036
TZ  = 'Europe/Berlin'

_ARCHIVE_URL  = 'https://archive-api.open-meteo.com/v1/archive'
_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'

# Welche Tageswerte holen wir?  (Open-Meteo "daily=" Parameter)
_DAILY_VARS = [
    'temperature_2m_max',
    'temperature_2m_min',
    'precipitation_sum',
    'sunshine_duration',   # Sekunden! -> /3600 = Stunden
    'wind_speed_10m_max',
    'snowfall_sum',        # cm
]


def _fetch_json(url: str, params: dict) -> dict:
    """Holt JSON von Open-Meteo. Wirft RuntimeError bei HTTP-Fehler."""
    qs = urllib.parse.urlencode(params, doseq=True)
    full = f'{url}?{qs}'
    log.debug('open-meteo GET %s', full)
    req = urllib.request.Request(
        full, headers={'User-Agent': 'CAO-XT-Backwaren/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                raise RuntimeError(f'HTTP {r.status} {url}')
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode(errors="replace")[:200]}') from exc


def _rows_aus_response(data: dict) -> list[dict]:
    """Mapped die Open-Meteo-Daily-Response in unsere Zeilenstruktur."""
    daily = data.get('daily') or {}
    if not daily or 'time' not in daily:
        return []
    times = daily['time']
    def col(name: str) -> list:
        return daily.get(name) or [None] * len(times)
    tmax  = col('temperature_2m_max')
    tmin  = col('temperature_2m_min')
    prec  = col('precipitation_sum')
    sun_s = col('sunshine_duration')
    wind  = col('wind_speed_10m_max')
    snow  = col('snowfall_sum')
    rows = []
    for i, datum in enumerate(times):
        sun_h = (sun_s[i] / 3600.0) if sun_s[i] is not None else None
        rows.append({
            'datum':           datum,
            'tmax_c':          tmax[i],
            'tmin_c':          tmin[i],
            'niederschlag_mm': prec[i],
            'sonnenstunden':   sun_h,
            'windgeschw_kmh':  wind[i],
            'schnee_cm':       snow[i],
        })
    return rows


def archive_laden(start: _dt.date, ende: _dt.date,
                  quelle: str = 'open-meteo') -> int:
    """Holt historische Tageswerte fuer [start, ende] und schreibt
    sie nach XT_WETTER_HABACH. Liefert die Anzahl gespeicherter
    Zeilen. Idempotent (REPLACE INTO)."""
    params = {
        'latitude':   LAT,
        'longitude':  LON,
        'start_date': start.isoformat(),
        'end_date':   ende.isoformat(),
        'daily':      ','.join(_DAILY_VARS),
        'timezone':   TZ,
    }
    data = _fetch_json(_ARCHIVE_URL, params)
    rows = _rows_aus_response(data)
    if not rows:
        log.warning('Keine Wetterdaten fuer %s..%s', start, ende)
        return 0
    n = _bulk_insert(rows, quelle)
    log.info('Wetter geladen: %s..%s -> %d Tage', start, ende, n)
    return n


def forecast_laden(tage: int = 7, quelle: str = 'open-meteo-forecast'
                   ) -> int:
    """Holt die naechsten ``tage`` Tageswerte (Vorhersage)."""
    params = {
        'latitude':   LAT,
        'longitude':  LON,
        'forecast_days': max(1, min(int(tage), 16)),
        'daily':      ','.join(_DAILY_VARS),
        'timezone':   TZ,
    }
    data = _fetch_json(_FORECAST_URL, params)
    rows = _rows_aus_response(data)
    if not rows:
        log.warning('Forecast leer')
        return 0
    n = _bulk_insert(rows, quelle)
    log.info('Forecast geladen: %d Tage', n)
    return n


def _bulk_insert(rows: list[dict], quelle: str) -> int:
    if not rows:
        return 0
    sql = """
      REPLACE INTO XT_WETTER_HABACH
        (datum, tmax_c, tmin_c, niederschlag_mm,
         sonnenstunden, windgeschw_kmh, schnee_cm,
         quelle, geladen_am)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
    """
    params = [(
        r['datum'], r['tmax_c'], r['tmin_c'], r['niederschlag_mm'],
        r['sonnenstunden'], r['windgeschw_kmh'], r['schnee_cm'],
        quelle,
    ) for r in rows]
    with get_db() as cur:
        cur.executemany(sql, params)
    return len(params)


def wetter_holen(von: _dt.date, bis: _dt.date) -> dict[_dt.date, dict]:
    """Liefert das Wetter aus dem Cache fuer den Zeitraum (inkl).
    Map: date -> dict mit tmax_c, tmin_c, niederschlag_mm, sonnenstunden."""
    with get_db() as cur:
        cur.execute("""
            SELECT datum, tmax_c, tmin_c, niederschlag_mm,
                   sonnenstunden, windgeschw_kmh, schnee_cm
            FROM XT_WETTER_HABACH
            WHERE datum BETWEEN %s AND %s
        """, (von, bis))
        return {r['datum']: r for r in (cur.fetchall() or [])}


def wetter_zaehler() -> dict:
    """Status fuer's UI: wie viele Wetter-Tage haben wir, von wann bis wann."""
    with get_db() as cur:
        cur.execute("SELECT COUNT(*) AS n, MIN(datum) AS frueh, MAX(datum) AS spaet FROM XT_WETTER_HABACH")
        return cur.fetchone() or {'n': 0, 'frueh': None, 'spaet': None}
