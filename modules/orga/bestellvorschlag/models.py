"""
Datenmodell-Funktionen fuer den Backwaren-Bestellvorschlag.

Aggregiert JOURNALPOS WG=1 ("Backwaren (Baecker)") pro Tag und
reichert mit Wetter + Feiertag + Schulferien an.

Quelle JOURNALPOS:
* QUELLE=3 (VK-Bon), STADIUM=9 (bezahlt) — Standard-Filter, schliesst
  Stornos, Trainings-Bons, Lieferscheine etc. aus.
* WARENGRUPPE = 1 (siehe project_backwaren_bedarf.md).
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

from common.db import get_db
from . import feiertage as _ft
from . import schulferien as _fer
from . import wetter as _w

log = logging.getLogger(__name__)

# WG-IDs, die zu "Backwaren" zaehlen (siehe Memory). Wir nehmen die
# Eltern-WG=1 (Backwaren (Baecker)) plus alle Nachkommen — die meisten
# Pos haengen direkt an 1, einige wenige an 101 (Luidl).
_BACKWAREN_WG_IDS = (1, 101)


def tagesdaten(von: _dt.date, bis: _dt.date) -> list[dict]:
    """Tageszeilen [von, bis] (inkl.) mit JOURNALPOS-Aggregat +
    Wetter + Feiertag + Ferien-Marker.

    Liefert eine Liste von Dicts (sortiert nach Datum, neueste zuerst):

        {
          'datum':           date,
          'wochentag':       int (0=Mo .. 6=So),
          'wochentag_name':  str,
          'n_bons':          int,
          'menge':           float (Stueck-Summe),
          'umsatz_brutto':   float,
          'umsatz_netto':    float | None,
          'tmax_c':          float | None,
          'tmin_c':          float | None,
          'niederschlag_mm': float | None,
          'sonnenstunden':   float | None,
          'feiertag':        str | None,
          'ist_ferien':      bool,
        }
    """
    # 1) JOURNALPOS-Aggregat aus CAO
    sql = """
        SELECT
            DATE(j.RDATUM) AS datum,
            COUNT(DISTINCT j.REC_ID)    AS n_bons,
            SUM(jp.MENGE)               AS menge,
            SUM(jp.GPREIS)              AS umsatz_brutto
        FROM JOURNAL j
        JOIN JOURNALPOS jp ON jp.JOURNAL_ID = j.REC_ID
        WHERE j.QUELLE = 3 AND j.STADIUM = 9
          AND jp.WARENGRUPPE IN (%s)
          AND j.RDATUM >= %s AND j.RDATUM < %s + INTERVAL 1 DAY
        GROUP BY DATE(j.RDATUM)
    """ % (','.join(['%s'] * len(_BACKWAREN_WG_IDS)), '%s', '%s')
    params = list(_BACKWAREN_WG_IDS) + [von, bis]
    with get_db() as cur:
        cur.execute(sql, params)
        rows_db = {r['datum']: r for r in (cur.fetchall() or [])}

    # 2) Wetter, Feiertage, Ferien (Bulk-Lookup)
    wmap = _w.wetter_holen(von, bis)
    ftmap = _ft.alle_im_zeitraum(von, bis)
    ferien_set = _fer.alle_im_zeitraum(von, bis)

    # 3) Pro Datum aufbauen
    wochentag_namen = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    result: list[dict] = []
    d = von
    while d <= bis:
        agg = rows_db.get(d) or {}
        wett = wmap.get(d) or {}
        feiertag_name = ftmap.get(d)
        result.append({
            'datum':           d,
            'wochentag':       d.weekday(),
            'wochentag_name':  wochentag_namen[d.weekday()],
            'n_bons':          int(agg.get('n_bons') or 0),
            'menge':           float(agg.get('menge') or 0),
            'umsatz_brutto':   float(agg.get('umsatz_brutto') or 0),
            'tmax_c':          (float(wett['tmax_c'])
                                if wett.get('tmax_c') is not None
                                else None),
            'tmin_c':          (float(wett['tmin_c'])
                                if wett.get('tmin_c') is not None
                                else None),
            'niederschlag_mm': (float(wett['niederschlag_mm'])
                                if wett.get('niederschlag_mm') is not None
                                else None),
            'sonnenstunden':   (float(wett['sonnenstunden'])
                                if wett.get('sonnenstunden') is not None
                                else None),
            'feiertag':        feiertag_name,
            'ist_ferien':      d in ferien_set,
        })
        d += _dt.timedelta(days=1)
    result.sort(key=lambda r: r['datum'], reverse=True)
    return result


def wochentag_median(von: _dt.date, bis: _dt.date) -> dict[int, dict]:
    """Median und n pro Wochentag fuer den Zeitraum — fuer Delta-
    Anzeige in der UI ('+18% vs. typischer Sa')."""
    sql = """
        SELECT
            WEEKDAY(j.RDATUM) AS wd,
            SUM(jp.MENGE)               AS menge,
            SUM(jp.GPREIS)              AS umsatz,
            COUNT(DISTINCT DATE(j.RDATUM)) AS n_tage
        FROM JOURNAL j
        JOIN JOURNALPOS jp ON jp.JOURNAL_ID = j.REC_ID
        WHERE j.QUELLE = 3 AND j.STADIUM = 9
          AND jp.WARENGRUPPE IN (%s)
          AND j.RDATUM >= %s AND j.RDATUM < %s + INTERVAL 1 DAY
        GROUP BY WEEKDAY(j.RDATUM)
    """ % (','.join(['%s'] * len(_BACKWAREN_WG_IDS)), '%s', '%s')
    params = list(_BACKWAREN_WG_IDS) + [von, bis]
    with get_db() as cur:
        cur.execute(sql, params)
        result = {}
        for r in cur.fetchall() or []:
            n_tage = int(r['n_tage'] or 0) or 1
            result[int(r['wd'])] = {
                'menge_avg':  float(r['menge'] or 0)  / n_tage,
                'umsatz_avg': float(r['umsatz'] or 0) / n_tage,
                'n_tage':     n_tage,
            }
        return result


def trainingsdaten(von: _dt.date, bis: _dt.date) -> list[dict]:
    """Wie ``tagesdaten``, aber nur Tage MIT Verkauf (n_bons > 0).
    Zum Trainieren des Vorhersagemodells."""
    return [r for r in tagesdaten(von, bis) if r['n_bons'] > 0]
