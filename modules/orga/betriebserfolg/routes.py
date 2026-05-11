"""Flask-Routes fuer den Betriebserfolg-Bericht."""
from __future__ import annotations

import datetime as _dt
import logging

from flask import (Blueprint, render_template, request, jsonify, session)

from . import schema as _schema
from . import models as _m

log = logging.getLogger(__name__)
bp = Blueprint('orga_betriebserfolg', __name__, template_folder='templates')


def _vormonat() -> tuple[int, int]:
    heute = _dt.date.today()
    if heute.month == 1:
        return heute.year - 1, 12
    return heute.year, heute.month - 1


@bp.get('/')
def seite():
    jahr_arg  = request.args.get('jahr', type=int)
    monat_arg = request.args.get('monat', type=int)
    if jahr_arg and monat_arg:
        jahr, monat = jahr_arg, monat_arg
    else:
        jahr, monat = _vormonat()
    return render_template('betriebserfolg.html',
                           jahr=jahr, monat=monat)


@bp.get('/api/daten')
def api_daten():
    try:
        jahr  = int(request.args.get('jahr')
                    or _vormonat()[0])
        monat = int(request.args.get('monat')
                    or _vormonat()[1])
        if not (1 <= monat <= 12):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': 'ungueltige Parameter'}), 400
    return jsonify({'ok': True, **_m.betriebserfolg(jahr, monat)})


@bp.post('/api/eingaben')
def api_eingaben_speichern():
    body = request.get_json(silent=True) or {}
    try:
        jahr  = int(body['jahr'])
        monat = int(body['monat'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'ok': False, 'msg': 'jahr/monat fehlt'}), 400
    _m.monatswerte_speichern(jahr, monat, body, ma_id=session.get('ma_id'))
    return jsonify({'ok': True})


@bp.post('/api/konfig')
def api_konfig_speichern():
    body = request.get_json(silent=True) or {}
    _m.konfig_speichern(body)
    return jsonify({'ok': True})


def create_blueprint():
    _schema.run_migration()
    return bp
