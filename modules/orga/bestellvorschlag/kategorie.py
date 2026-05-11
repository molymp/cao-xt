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
        'slug':         'mittagstisch',
        'name':         'Mittagstisch',
        'icon':         '🍽',
        'beschreibung': 'Tagesmenü Mo–Fr — Artikel „Essen to go" (seit 2020) '
                        'und „Essen groß to go" (seit April 2024). '
                        'Quiche/Pizza/Flammkuchen NICHT enthalten — '
                        'gehören in die „Essen"-Kategorie.',
        'wg_ids':       [],
        'artikel_ids': [
            5314,  # Essen to go
            6195,  # Essen groß to go
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


# ── Gesamtumsatz als virtuelle Kategorie ─────────────────────────


def gesamtumsatz_tagesdaten(von: _dt.date, bis: _dt.date) -> list[dict]:
    """Tageszeilen mit ALLEM (QUELLE=3 STADIUM=9) — auf JOURNAL-Ebene
    aggregiert, nicht JOURNALPOS. Schneller und korrekt fuer
    Gesamtumsatz-Vergleich.
    """
    with get_db() as cur:
        cur.execute("""
            SELECT DATE(j.RDATUM) AS datum,
                   COUNT(*) AS n_bons,
                   SUM(j.BSUMME) AS umsatz_brutto
            FROM JOURNAL j
            WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2 AND j.STADIUM < 127
              AND j.RDATUM >= %s AND j.RDATUM < %s + INTERVAL 1 DAY
            GROUP BY DATE(j.RDATUM)
        """, (von, bis))
        rows_db = {r['datum']: r for r in (cur.fetchall() or [])}
    wmap = _w.wetter_holen(von, bis)
    ftmap = _ft.alle_im_zeitraum(von, bis)
    fer = _fer.alle_im_zeitraum(von, bis)
    wt_namen = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    result: list[dict] = []
    d = von
    while d <= bis:
        agg = rows_db.get(d) or {}
        wett = wmap.get(d) or {}
        result.append({
            'datum':           d,
            'wochentag':       d.weekday(),
            'wochentag_name':  wt_namen[d.weekday()],
            'n_bons':          int(agg.get('n_bons') or 0),
            'menge':           0,  # auf JOURNAL-Ebene kein Mengen-Aggregat
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
            'feiertag':        ftmap.get(d),
            'ist_ferien':      d in fer,
        })
        d += _dt.timedelta(days=1)
    result.sort(key=lambda r: r['datum'], reverse=True)
    return result


GESAMT_KATEGORIE = {
    'slug':         'gesamt',
    'name':         'Gesamtumsatz (alle Bons)',
    'icon':         '📊',
    'beschreibung': 'Alle Kassenbons (QUELLE=3, STADIUM=9) — Vergleichs-'
                    'baseline für die einzelnen Kategorien.',
    'wg_ids':       [],
    'artikel_ids':  [],
    '_gesamt':      True,
}


def alle_inkl_gesamt() -> list[dict]:
    return [GESAMT_KATEGORIE] + KATEGORIEN


# ── Wettereffekt-Analyse: Lift bei Top- vs. Bottom-Wetter ────────


def _avg(zeilen: list[dict]) -> Optional[float]:
    aktiv = [z for z in zeilen if z['n_bons'] > 0]
    if not aktiv:
        return None
    return sum(float(z['umsatz_brutto']) for z in aktiv) / len(aktiv)


def _lift(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


def _wettereffekt(zeilen: list[dict], schwellen: dict) -> dict:
    """Berechnet Lift-Werte für eine Kategorie.

    Lifts werden gegen das Vergleichs-Gegenstueck (gleich groß)
    berechnet. Ein positiver Lift heißt: bei der „guten"-Bedingung
    ist der Umsatz höher.
    """
    # Datenbasis: nur Verkaufstage mit Wetter-Daten
    aktiv = [z for z in zeilen if z['n_bons'] > 0 and z['tmax_c'] is not None
             and z['niederschlag_mm'] is not None
             and z['sonnenstunden'] is not None]
    if len(aktiv) < 20:
        return {'n': len(aktiv), 'gesamt_n': len(aktiv)}

    # Composite "Schoenwetter" (warm + sonnig + trocken)
    schoen = [z for z in aktiv
              if z['tmax_c']          >= schwellen['warm_tmax']
              and z['niederschlag_mm'] < schwellen['trocken_mm']]
    schlecht = [z for z in aktiv
                 if z['tmax_c']          <= schwellen['kalt_tmax']
                 or z['niederschlag_mm'] >= schwellen['regen_mm']]

    # Einzeln pro Wetter-Variable
    warm = [z for z in aktiv if z['tmax_c'] >= schwellen['warm_tmax']]
    kalt = [z for z in aktiv if z['tmax_c'] <= schwellen['kalt_tmax']]
    trocken = [z for z in aktiv if z['niederschlag_mm'] < schwellen['trocken_mm']]
    regen   = [z for z in aktiv if z['niederschlag_mm'] >= schwellen['regen_mm']]
    sonnig  = [z for z in aktiv if z['sonnenstunden'] >= schwellen['sonnig_h']]
    bedeckt = [z for z in aktiv if z['sonnenstunden'] <  schwellen['bedeckt_h']]

    avg_alle = _avg(aktiv)
    return {
        'n':               len(aktiv),
        'avg_alle':        avg_alle,
        # Composite
        'avg_schoen':      _avg(schoen),
        'avg_schlecht':    _avg(schlecht),
        'n_schoen':        len(schoen),
        'n_schlecht':      len(schlecht),
        'lift_schoen_vs_schlecht': _lift(_avg(schoen), _avg(schlecht)),
        # Tmax
        'avg_warm':        _avg(warm),
        'avg_kalt':        _avg(kalt),
        'n_warm':          len(warm),
        'n_kalt':          len(kalt),
        'lift_warm_vs_kalt': _lift(_avg(warm), _avg(kalt)),
        # Niederschlag
        'avg_trocken':     _avg(trocken),
        'avg_regen':       _avg(regen),
        'n_trocken':       len(trocken),
        'n_regen':         len(regen),
        'lift_trocken_vs_regen': _lift(_avg(trocken), _avg(regen)),
        # Sonne
        'avg_sonnig':      _avg(sonnig),
        'avg_bedeckt':     _avg(bedeckt),
        'n_sonnig':        len(sonnig),
        'n_bedeckt':       len(bedeckt),
        'lift_sonnig_vs_bedeckt': _lift(_avg(sonnig), _avg(bedeckt)),
    }


def _wochentag_avgs(rows: list[dict]) -> dict[int, dict]:
    aktiv = [r for r in rows if r['n_bons'] > 0]
    nach: dict[int, list[float]] = {}
    for r in aktiv:
        nach.setdefault(r['wochentag'], []).append(r['umsatz_brutto'])
    out: dict[int, dict] = {}
    for wd, vals in nach.items():
        out[wd] = {'avg': sum(vals) / len(vals), 'n': len(vals)}
    return out


def _monat_avgs(rows: list[dict]) -> dict[int, dict]:
    aktiv = [r for r in rows if r['n_bons'] > 0]
    nach: dict[int, list[float]] = {}
    for r in aktiv:
        nach.setdefault(r['datum'].month, []).append(r['umsatz_brutto'])
    out: dict[int, dict] = {}
    for m, vals in nach.items():
        out[m] = {'avg': sum(vals) / len(vals), 'n': len(vals)}
    return out


def _faktoren_lifts(rows: list[dict],
                    feiertage_im_zeitraum: set) -> dict:
    """Liefert Lift-Werte für die wichtigsten NICHT-Wetter-Faktoren."""
    aktiv = [r for r in rows if r['n_bons'] > 0]
    if not aktiv:
        return {'n': 0}
    avg_alle = sum(r['umsatz_brutto'] for r in aktiv) / len(aktiv)

    def sub_lift(filt) -> dict:
        sub = [r for r in aktiv if filt(r)]
        if not sub:
            return {'lift': None, 'n': 0, 'avg': None}
        a = sum(r['umsatz_brutto'] for r in sub) / len(sub)
        return {'lift': (a - avg_alle) / avg_alle * 100 if avg_alle else None,
                'n': len(sub), 'avg': a}

    return {
        'n':                       len(aktiv),
        'avg_alle':                avg_alle,
        # Vor-/Nach-Feiertag (Hamsterkauf-Cluster)
        'tag_vor_ft':              sub_lift(
            lambda r: (r['datum'] + _dt.timedelta(days=1)) in feiertage_im_zeitraum),
        'zwei_tage_vor_ft':        sub_lift(
            lambda r: (r['datum'] + _dt.timedelta(days=2)) in feiertage_im_zeitraum),
        'tag_nach_ft':             sub_lift(
            lambda r: (r['datum'] - _dt.timedelta(days=1)) in feiertage_im_zeitraum),
        'zwei_tage_nach_ft':       sub_lift(
            lambda r: (r['datum'] - _dt.timedelta(days=2)) in feiertage_im_zeitraum),
        # Schulferien
        'ferien':                  sub_lift(lambda r: r['ist_ferien']),
        'schulzeit':               sub_lift(lambda r: not r['ist_ferien']),
        # Saison
        'advent':                  sub_lift(
            lambda r: r['datum'].month == 12 and r['datum'].day <= 24),
        'hochsommer':              sub_lift(
            lambda r: r['datum'].month in (7, 8)),
        'nachweihnachten':         sub_lift(
            lambda r: r['datum'].month in (1, 2)),
        # Wochentage
        'wochentag':               _wochentag_avgs(aktiv),
        'monat':                   _monat_avgs(aktiv),
    }


def faktoren_vergleich(von: _dt.date, bis: _dt.date,
                        wochentag: Optional[int] = None) -> dict:
    """Sammelt fuer Gesamtumsatz + alle Kategorien alle nicht-Wetter-
    Lift-Werte (Wochentag, Monat, Saison, Feiertags-Cluster, Ferien).
    """
    feiertage_im_zeitraum = set(_ft.alle_im_zeitraum(von, bis).keys())

    def _filter_wt(rows):
        if wochentag is None: return rows
        return [r for r in rows if r['wochentag'] == wochentag]

    ergebnisse = []
    # Gesamtumsatz
    rows = _filter_wt(gesamtumsatz_tagesdaten(von, bis))
    ergebnisse.append({
        'slug':    GESAMT_KATEGORIE['slug'],
        'name':    GESAMT_KATEGORIE['name'],
        'icon':    GESAMT_KATEGORIE['icon'],
        'faktoren': _faktoren_lifts(rows, feiertage_im_zeitraum),
    })
    for k in KATEGORIEN:
        rows = _filter_wt(tagesdaten_kategorie(k, von, bis))
        ergebnisse.append({
            'slug':    k['slug'],
            'name':    k['name'],
            'icon':    k['icon'],
            'faktoren': _faktoren_lifts(rows, feiertage_im_zeitraum),
        })
    return {
        'von':         von,
        'bis':         bis,
        'wochentag':   wochentag,
        'kategorien':  ergebnisse,
    }


def wettereffekt_vergleich(von: _dt.date, bis: _dt.date,
                            wochentag: Optional[int] = None,
                            schwellen: Optional[dict] = None) -> dict:
    """Berechnet Wetter-Lift fuer Gesamtumsatz + alle Kategorien.

    schwellen-Defaults:
      warm_tmax    = 18  (Tmax ≥ 18 °C)
      kalt_tmax    = 12  (Tmax ≤ 12 °C)
      trocken_mm   = 1   (Niederschlag < 1 mm)
      regen_mm     = 5   (Niederschlag ≥ 5 mm)
      sonnig_h     = 8   (Sonnenstunden ≥ 8 h)
      bedeckt_h    = 2   (Sonnenstunden < 2 h)
    """
    s = {
        'warm_tmax':  18.0, 'kalt_tmax':  12.0,
        'trocken_mm':  1.0, 'regen_mm':    5.0,
        'sonnig_h':    8.0, 'bedeckt_h':   2.0,
    }
    if schwellen:
        s.update(schwellen)

    def _filter_wt(rows):
        if wochentag is None:
            return rows
        return [r for r in rows if r['wochentag'] == wochentag]

    ergebnisse = []
    # Gesamtumsatz
    rows = _filter_wt(gesamtumsatz_tagesdaten(von, bis))
    eff = _wettereffekt(rows, s)
    ergebnisse.append({
        'slug':  GESAMT_KATEGORIE['slug'],
        'name':  GESAMT_KATEGORIE['name'],
        'icon':  GESAMT_KATEGORIE['icon'],
        'effekt': eff,
    })
    # Pro Kategorie
    for k in KATEGORIEN:
        rows = _filter_wt(tagesdaten_kategorie(k, von, bis))
        eff = _wettereffekt(rows, s)
        ergebnisse.append({
            'slug':  k['slug'],
            'name':  k['name'],
            'icon':  k['icon'],
            'effekt': eff,
        })
    return {
        'von':       von,
        'bis':       bis,
        'wochentag': wochentag,
        'schwellen': s,
        'kategorien': ergebnisse,
    }


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
        WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2 AND j.STADIUM < 127
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
