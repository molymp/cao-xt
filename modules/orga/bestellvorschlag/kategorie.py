"""
Bericht-Kategorien fuer das Backwaren-/Verzehr-Reporting.

Jede Kategorie definiert eine Filterregel auf JOURNALPOS:
* ``wg_ids``:      JOURNALPOS.WARENGRUPPE IN (...) — fuer reine WG-Kategorien
                   (z.B. Backwaren WG=1, Speiseeis WG=610)
* ``artikel_ids``: JOURNALPOS.ARTIKEL_ID IN (...) — fuer Artikel-Listen
                   (typisch fuer die Verzehr-WG=5, wo unterschiedliche
                   Sortimente in einem Topf liegen)

Beide werden mit OR verknuepft (ein Pos zaehlt, wenn entweder
WARENGRUPPE in der WG-Liste ist ODER die ARTIKEL_ID).
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

# ── Kategorie-Definitionen ───────────────────────────────────────
# Pflege erfolgt in dieser Datei. ARTIKEL.REC_IDs aus der CAO-DB
# (Stand 2026-05-11).

KATEGORIEN: list[dict] = [
    {
        'slug':         'backwaren',
        'name':         'Backwaren (Bäcker / Luidl)',
        'icon':         '🥨',
        'beschreibung': 'Alle Bons aus WG „Backwaren (Bäcker)" und „Luidl" — '
                        'Sammelartikel und einzeln gepflegte Brotsorten.',
        'wg_ids':       [1, 101],
        'artikel_ids':  [],
    },
    {
        'slug':         'heissgetraenke',
        'name':         'Heißgetränke',
        'icon':         '☕',
        'beschreibung': 'Kaffee (Tasse, Haferl, Espresso, Cappuccino, Latte), '
                        'Heiße Schokolade, Chai und Tee. Eis-Kaffee und '
                        'Affogato gehören in die Eis-Spezialitäten.',
        'wg_ids':       [],
        'artikel_ids': [
            # Espresso / Doppio
            4294, 4295, 4296, 4297,
            # Cappuccino / Latte / Milchkaffee
            4302, 4303, 6453, 6454,
            # Haferl Kaffee
            4304, 4305,
            # Tasse Kaffee
            4306, 4307,
            # Heiße Schokolade / Chai
            6194, 6457, 6459,
            # Tee
            4298, 4299,
        ],
    },
    {
        'slug':         'eis_spezialitaeten',
        'name':         'Eis-Spezialitäten',
        'icon':         '🍨',
        'beschreibung': 'Eis-Kaffee, Affogato (Eisschokolade existiert '
                        'aktuell nicht als eigener Artikel — bitte ergänzen, '
                        'wenn das gewünscht ist).',
        'wg_ids':       [],
        'artikel_ids': [
            # Eis-Kaffee
            6190, 6206,
            # Affogato
            4710, 4711,
        ],
    },
    {
        'slug':         'essen',
        'name':         'Essen (mit Pizza / Flammkuchen)',
        'icon':         '🍕',
        'beschreibung': '„Essen to go", „Essen groß to go" und '
                        '„Quiche / Pizza / Flammkuchen". Quiche taucht hier '
                        'doppelt auf, weil im Kassen-Artikel mit Pizza+'
                        'Flammkuchen zusammengefasst.',
        'wg_ids':       [],
        'artikel_ids': [
            5314, 6195,           # Essen / Essen groß
            6196, 6571,           # Quiche / Pizza / Flammkuchen
        ],
    },
    {
        'slug':         'semmel_sandwich',
        'name':         'Semmel & Sandwich (mit Quiche, Butterkringel)',
        'icon':         '🥪',
        'beschreibung': 'Belegte Semmeln, Sandwiches, Butterkringel und '
                        'Quiche (gleicher Artikel wie Pizza/Flammkuchen — '
                        'auf Wunsch hier zusätzlich gelistet).',
        'wg_ids':       [],
        'artikel_ids': [
            6184,                  # Butterkringel
            6196, 6571,            # Quiche/Pizza/Flammkuchen (doppelt zugeordnet, gewollt)
            6202, 6203,            # Sandwich / groß
            6197,                  # Fleischsemmel
            6198, 6199,            # Wurst-Körner-Semmel / Wurst-Semmel
            6200, 6201,            # Leberkäs-Körner-Semmel / Leberkäs-Semmel
        ],
    },
    {
        'slug':         'eisverkauf',
        'name':         'Eisverkauf (Speiseeis-WG)',
        'icon':         '🍦',
        'beschreibung': 'Alle Bons aus der Warengruppe „Speiseeis" '
                        '(Kugeln, Becher, Tüten).',
        'wg_ids':       [610],
        'artikel_ids':  [],
    },
]

_BY_SLUG = {k['slug']: k for k in KATEGORIEN}


def alle() -> list[dict]:
    return KATEGORIEN


def holen(slug: str) -> Optional[dict]:
    return _BY_SLUG.get(slug)


# ── Aggregation mit Filter ───────────────────────────────────────


def tagesdaten_kategorie(kategorie: dict,
                         von: _dt.date, bis: _dt.date) -> list[dict]:
    """Wie ``models.tagesdaten``, aber mit beliebigem WG-/Artikel-Filter.

    Liefert Tageszeilen [von, bis] (inkl.) mit JOURNALPOS-Aggregat +
    Wetter + Feiertag + Ferien-Marker. Reihenfolge: neueste zuerst.
    """
    wg_ids      = kategorie.get('wg_ids') or []
    artikel_ids = kategorie.get('artikel_ids') or []
    if not wg_ids and not artikel_ids:
        raise ValueError(
            f'Kategorie "{kategorie.get("slug")}" hat weder wg_ids '
            'noch artikel_ids')

    # OR-Filter zusammenbauen
    bedingungen: list[str] = []
    params: list = []
    if wg_ids:
        ph = ','.join(['%s'] * len(wg_ids))
        bedingungen.append(f'jp.WARENGRUPPE IN ({ph})')
        params.extend(wg_ids)
    if artikel_ids:
        ph = ','.join(['%s'] * len(artikel_ids))
        bedingungen.append(f'jp.ARTIKEL_ID IN ({ph})')
        params.extend(artikel_ids)
    where_pos = ' OR '.join(bedingungen)

    sql = f"""
        SELECT
            DATE(j.RDATUM) AS datum,
            COUNT(DISTINCT j.REC_ID) AS n_bons,
            SUM(jp.MENGE)            AS menge,
            SUM(jp.GPREIS)           AS umsatz_brutto
        FROM JOURNAL j
        JOIN JOURNALPOS jp ON jp.JOURNAL_ID = j.REC_ID
        WHERE j.QUELLE = 3 AND j.STADIUM = 9
          AND ({where_pos})
          AND j.RDATUM >= %s AND j.RDATUM < %s + INTERVAL 1 DAY
        GROUP BY DATE(j.RDATUM)
    """
    params.extend([von, bis])
    with get_db() as cur:
        cur.execute(sql, params)
        rows_db = {r['datum']: r for r in (cur.fetchall() or [])}

    wmap = _w.wetter_holen(von, bis)
    ftmap = _ft.alle_im_zeitraum(von, bis)
    ferien_set = _fer.alle_im_zeitraum(von, bis)

    wt_namen = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    result: list[dict] = []
    d = von
    while d <= bis:
        agg = rows_db.get(d) or {}
        wett = wmap.get(d) or {}
        ft_name = ftmap.get(d)
        result.append({
            'datum':           d,
            'wochentag':       d.weekday(),
            'wochentag_name':  wt_namen[d.weekday()],
            'n_bons':          int(agg.get('n_bons') or 0),
            'menge':           float(agg.get('menge') or 0),
            'umsatz_brutto':   float(agg.get('umsatz_brutto') or 0),
            'tmax_c':          (float(wett['tmax_c'])
                                if wett.get('tmax_c') is not None else None),
            'tmin_c':          (float(wett['tmin_c'])
                                if wett.get('tmin_c') is not None else None),
            'niederschlag_mm': (float(wett['niederschlag_mm'])
                                if wett.get('niederschlag_mm') is not None
                                else None),
            'sonnenstunden':   (float(wett['sonnenstunden'])
                                if wett.get('sonnenstunden') is not None
                                else None),
            'feiertag':        ft_name,
            'ist_ferien':      d in ferien_set,
        })
        d += _dt.timedelta(days=1)
    result.sort(key=lambda r: r['datum'], reverse=True)
    return result
