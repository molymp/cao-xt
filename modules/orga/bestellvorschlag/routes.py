"""Flask-Routes fuer Backwaren-Bestellvorschlag (Luidl)."""
from __future__ import annotations

import datetime as _dt
import logging

from flask import (Blueprint, render_template, request, jsonify,
                   session, abort)

from . import models as _m
from . import vorhersage as _v
from . import wetter as _w
from . import feiertage as _ft
from . import schulferien as _fer
from . import schema as _schema

log = logging.getLogger(__name__)
bp = Blueprint('orga_bestellvorschlag', __name__,
               template_folder='templates')


def _login_check() -> None:
    if not session.get('ma_id'):
        abort(401)


def _form_to_date(s: str | None,
                  default: _dt.date | None = None) -> _dt.date | None:
    if not s:
        return default
    s = s.strip()
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        try:
            return _dt.datetime.strptime(s, '%d.%m.%Y').date()
        except ValueError:
            return default


@bp.get('/luidl')
def luidl_uebersicht():
    """Bestellvorschlag-Hauptseite."""
    _login_check()
    heute = _dt.date.today()
    naechster_sa = heute
    while naechster_sa.weekday() != 5:
        naechster_sa += _dt.timedelta(days=1)
    return render_template(
        'bestellvorschlag_luidl.html',
        heute=heute,
        ziel_datum=naechster_sa,
    )


@bp.get('/api/luidl/tagesdaten')
def api_tagesdaten():
    """Tagesaggregat Backwaren plus Kontext (Wetter, Feiertag, Ferien)."""
    _login_check()
    bis = _form_to_date(request.args.get('bis'),
                         _dt.date.today())
    von = _form_to_date(request.args.get('von'),
                         bis - _dt.timedelta(days=90))
    if not von or not bis or von > bis:
        return jsonify({'ok': False, 'msg': 'Ungueltiger Zeitraum'}), 400
    rows = _m.tagesdaten(von, bis)
    medians = _m.wochentag_median(von, bis)
    # JSON-Serialisierung: Datum → ISO-String
    out = []
    for r in rows:
        r2 = dict(r)
        r2['datum'] = r['datum'].isoformat()
        out.append(r2)
    return jsonify({
        'ok': True,
        'von': von.isoformat(),
        'bis': bis.isoformat(),
        'zeilen': out,
        'wochentag_avg': medians,
    })


@bp.get('/api/luidl/vorhersage')
def api_vorhersage():
    """Vorhersage fuer ein Zieldatum.

    Query-Parameter:
      datum     YYYY-MM-DD (Pflicht)
      tmax      optional override
      niederschlag, sonnenstunden  optional override
    Falls Wettervorhersage in DB vorhanden, wird sie gezogen.
    """
    _login_check()
    datum = _form_to_date(request.args.get('datum'))
    if not datum:
        return jsonify({'ok': False, 'msg': 'datum fehlt'}), 400
    # Wetterdaten — entweder Override aus Query oder DB-Cache
    tmax = request.args.get('tmax', type=float)
    nied = request.args.get('niederschlag', type=float)
    sonne = request.args.get('sonnenstunden', type=float)
    if tmax is None or nied is None or sonne is None:
        wmap = _w.wetter_holen(datum, datum)
        wett = wmap.get(datum) or {}
        if tmax is None and wett.get('tmax_c') is not None:
            tmax = float(wett['tmax_c'])
        if nied is None and wett.get('niederschlag_mm') is not None:
            nied = float(wett['niederschlag_mm'])
        if sonne is None and wett.get('sonnenstunden') is not None:
            sonne = float(wett['sonnenstunden'])
    ist_ft = _ft.ist_feiertag(datum)
    ist_fer = _fer.ist_ferien(datum)
    v = _v.vorhersage_fuer_tag(
        datum, tmax_c=tmax, niederschlag_mm=nied,
        sonnenstunden=sonne, ist_feiertag=ist_ft,
        ist_ferien=ist_fer)
    if v.get('datum'):
        v['datum'] = v['datum'].isoformat()
    return jsonify({
        'ok':    True,
        'wetter': {'tmax_c': tmax, 'niederschlag_mm': nied,
                    'sonnenstunden': sonne},
        'feiertag': _ft.name(datum),
        'ist_ferien': ist_fer,
        'vorhersage': v,
        'modell':   _v.status(),
    })


@bp.post('/api/luidl/modell/neu-trainieren')
def api_modell_neu_trainieren():
    """Zwingt das Modell zum Neu-Training (sonst lazy beim ersten Request)."""
    _login_check()
    status = _v.modell_neu_trainieren()
    return jsonify({'ok': True, 'status': status})


@bp.get('/api/luidl/modell/koeffizienten')
def api_koeffizienten():
    _login_check()
    if not _v.status()['wochentage']:
        _v.modell_neu_trainieren()
    return jsonify({
        'ok': True,
        'koeffizienten': _v.koeffizienten(),
        'modell':        _v.status(),
    })


@bp.post('/api/luidl/wetter/aktualisieren')
def api_wetter_aktualisieren():
    """Forecast neu holen (naechste 7 Tage)."""
    _login_check()
    try:
        n = _w.forecast_laden(tage=7)
        state = _w.wetter_zaehler()
        return jsonify({'ok': True, 'n': n,
                        'cache': {'n': state['n'],
                                   'frueh': str(state['frueh']),
                                   'spaet': str(state['spaet'])}})
    except Exception as exc:
        log.warning('Forecast-Aktualisierung: %s', exc)
        return jsonify({'ok': False, 'msg': str(exc)}), 500


def create_blueprint():
    _schema.run_migration()
    return bp
