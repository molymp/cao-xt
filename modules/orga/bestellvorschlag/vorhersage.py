"""
Einfaches lineares Vorhersage-Modell fuer den Backwaren-Tagesbedarf.

Pro Wochentag separate Regression — Samstag verhaelt sich anders als
Dienstag. Features (alle linear):

  * tmax_c            (Tageshoechsttemperatur in °C)
  * niederschlag_mm   (Niederschlagsmenge in mm)
  * sonnenstunden     (Sonnenscheindauer in Stunden)
  * ist_feiertag      (0/1, Bayern)
  * ist_ferien        (0/1, Schulferien Bayern)
  * monat_sin/cos     (Saisonalitaet via Fourier-Pair)

Schaetzung: ``numpy.linalg.lstsq`` mit zeitlich abklingender Gewichtung
(juengere Tage zaehlen mehr). Output: erwartete ``menge`` und
``umsatz_brutto`` plus MAE-Selbsteinschaetzung pro Wochentag.

Modelle werden im Prozess gecacht und beim ersten Aufruf trainiert.
``modell_neu_trainieren()`` kann sie verwerfen.
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Optional

import numpy as np

from . import models as _m

log = logging.getLogger(__name__)

# Modell-Cache: wochentag -> dict mit coef + MAE + N
_modell_cache: dict[int, dict] = {}
_modell_trainiert_zeitpunkt: Optional[_dt.datetime] = None
MODELL_VERSION = '2026-05-11-lin-v1'


def _features(row: dict) -> list[float]:
    """Bildet den Feature-Vektor zu einer Tageszeile. Reihenfolge muss
    zwischen Training und Vorhersage konsistent sein."""
    monat = row['datum'].month if isinstance(row.get('datum'), _dt.date) \
            else int(row.get('monat') or 1)
    return [
        1.0,                                                   # bias
        float(row.get('tmax_c') or 15.0),                      # default mild
        float(row.get('niederschlag_mm') or 0.0),
        float(row.get('sonnenstunden') or 0.0),
        1.0 if row.get('feiertag') else 0.0,
        1.0 if row.get('ist_ferien') else 0.0,
        math.sin(2 * math.pi * monat / 12.0),
        math.cos(2 * math.pi * monat / 12.0),
    ]


_FEATURE_NAMES = [
    'bias', 'tmax_c', 'niederschlag_mm', 'sonnenstunden',
    'ist_feiertag', 'ist_ferien_by', 'monat_sin', 'monat_cos',
]


def _zeitgewicht(d: _dt.date, ref: _dt.date,
                  halbwertszeit_tage: int = 365 * 2) -> float:
    """Tage in der Vergangenheit zaehlen weniger — Halbwertszeit 2J."""
    dt_d = max(0, (ref - d).days)
    return 0.5 ** (dt_d / halbwertszeit_tage)


def modell_neu_trainieren(von: Optional[_dt.date] = None,
                          bis: Optional[_dt.date] = None) -> dict:
    """Trainiert alle 7 Wochentag-Modelle neu. Default-Trainingszeitraum:
    letzte 5 Jahre bis heute.

    Liefert eine Status-Map ``{wochentag: {n, mae_menge, mae_umsatz}}``.
    """
    global _modell_cache, _modell_trainiert_zeitpunkt
    heute = _dt.date.today()
    if not bis:
        bis = heute
    if not von:
        von = bis - _dt.timedelta(days=365 * 5)

    daten = _m.trainingsdaten(von, bis)
    if not daten:
        log.warning('Keine Trainingsdaten in %s..%s', von, bis)
        _modell_cache = {}
        return {}

    nach_wd: dict[int, list[dict]] = {}
    for r in daten:
        nach_wd.setdefault(r['wochentag'], []).append(r)

    status: dict[int, dict] = {}
    _modell_cache = {}
    for wd, zeilen in nach_wd.items():
        if len(zeilen) < 20:
            log.warning('Wochentag %d: nur %d Datenpunkte, ueberspringe',
                        wd, len(zeilen))
            continue
        X = np.array([_features(r) for r in zeilen], dtype=float)
        y_menge  = np.array([r['menge']         for r in zeilen], dtype=float)
        y_umsatz = np.array([r['umsatz_brutto'] for r in zeilen], dtype=float)
        w = np.array([_zeitgewicht(r['datum'], bis) for r in zeilen],
                     dtype=float)
        # Weighted Least Squares: X * sqrt(w), y * sqrt(w)
        sqw = np.sqrt(w)[:, None]
        Xw = X * sqw
        yw_m = y_menge  * sqw[:, 0]
        yw_u = y_umsatz * sqw[:, 0]
        coef_m, _, _, _ = np.linalg.lstsq(Xw, yw_m, rcond=None)
        coef_u, _, _, _ = np.linalg.lstsq(Xw, yw_u, rcond=None)
        pred_m = X @ coef_m
        pred_u = X @ coef_u
        mae_m = float(np.mean(np.abs(pred_m - y_menge)))
        mae_u = float(np.mean(np.abs(pred_u - y_umsatz)))
        _modell_cache[wd] = {
            'coef_menge':  coef_m,
            'coef_umsatz': coef_u,
            'n':           len(zeilen),
            'mae_menge':   mae_m,
            'mae_umsatz':  mae_u,
            'avg_menge':   float(np.mean(y_menge)),
            'avg_umsatz':  float(np.mean(y_umsatz)),
        }
        status[wd] = {
            'n': len(zeilen), 'mae_menge': mae_m, 'mae_umsatz': mae_u,
            'avg_menge': float(np.mean(y_menge)),
            'avg_umsatz': float(np.mean(y_umsatz)),
        }
    _modell_trainiert_zeitpunkt = _dt.datetime.now()
    log.info('Trainiert: %s Wochentage, Zeitraum %s..%s',
             list(_modell_cache.keys()), von, bis)
    return status


def status() -> dict:
    """Status fuer's UI."""
    return {
        'version': MODELL_VERSION,
        'trainiert_am': (_modell_trainiert_zeitpunkt.isoformat()
                         if _modell_trainiert_zeitpunkt else None),
        'wochentage':   {wd: {k: v for k, v in m.items()
                              if k not in ('coef_menge', 'coef_umsatz')}
                         for wd, m in _modell_cache.items()},
        'feature_names': _FEATURE_NAMES,
    }


def vorhersage_fuer_tag(d: _dt.date,
                        tmax_c: Optional[float] = None,
                        niederschlag_mm: Optional[float] = None,
                        sonnenstunden: Optional[float] = None,
                        ist_feiertag: bool = False,
                        ist_ferien: bool = False) -> dict:
    """Liefert die erwarteten Werte fuer einen Tag ``d``.

    Falls Wetterdaten None sind, werden Defaults benutzt (mild, trocken,
    durchschnittlich sonnig). Liefert ``{menge, umsatz, mae_menge,
    mae_umsatz, n_training}``.
    """
    if not _modell_cache:
        modell_neu_trainieren()
    wd = d.weekday()
    if wd not in _modell_cache:
        return {'menge': None, 'umsatz': None, 'msg':
                'Kein Modell — Bäcker hat sonntags geschlossen?'}
    row = {
        'datum':           d,
        'tmax_c':          tmax_c,
        'niederschlag_mm': niederschlag_mm,
        'sonnenstunden':   sonnenstunden,
        'feiertag':        ist_feiertag,
        'ist_ferien':      ist_ferien,
    }
    X = np.array(_features(row), dtype=float)
    cm = _modell_cache[wd]
    menge  = float(X @ cm['coef_menge'])
    umsatz = float(X @ cm['coef_umsatz'])
    return {
        'datum':       d,
        'wochentag':   wd,
        'menge':       max(0.0, menge),
        'umsatz':      max(0.0, umsatz),
        'mae_menge':   cm['mae_menge'],
        'mae_umsatz':  cm['mae_umsatz'],
        'n_training':  cm['n'],
        'avg_menge':   cm['avg_menge'],
        'avg_umsatz':  cm['avg_umsatz'],
    }


def koeffizienten() -> list[dict]:
    """Pro Wochentag die geschaetzten Koeffizienten — fuer die UI."""
    out = []
    for wd, m in sorted(_modell_cache.items()):
        cm = m['coef_menge']
        cu = m['coef_umsatz']
        out.append({
            'wochentag': wd,
            'n':         m['n'],
            'mae_menge': m['mae_menge'],
            'mae_umsatz': m['mae_umsatz'],
            'avg_menge':  m['avg_menge'],
            'avg_umsatz': m['avg_umsatz'],
            'coef_menge': {n: float(c) for n, c in zip(_FEATURE_NAMES, cm)},
            'coef_umsatz': {n: float(c) for n, c in zip(_FEATURE_NAMES, cu)},
        })
    return out
