"""
Dorfkern Banking — Flask-Routes (Phase E.1, primaer read-only;
Notiz/Geprueft/Kategorie-Edit erlaubt).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from flask import Blueprint, render_template, request, jsonify, abort, session

from . import models as m

bp = Blueprint('orga_banking', __name__, template_folder='templates')


def _login_check() -> None:
    if not session.get('ma_id'):
        abort(401)


def _form_to_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(s, '%d.%m.%Y').date()
        except (ValueError, TypeError):
            return None


@bp.get('/')
def uebersicht():
    _login_check()
    konten = m.konten_liste()
    return render_template('banking.html', konten=konten)


@bp.get('/konto/<int:konto_id>')
def konto_detail(konto_id: int):
    _login_check()
    konto = m.konto_holen(konto_id)
    if not konto:
        abort(404)
    suche = (request.args.get('q') or '').strip()
    suche_regex = bool(request.args.get('regex'))
    art_filter = request.args.get('art') or None
    umsatztyp_id = request.args.get('umsatztyp_id', type=int)
    nur_ungeprueft = bool(request.args.get('nur_ungeprueft'))
    # Zeitraum-Preset: wenn 'preset' gesetzt, ueberschreibt es von/bis
    preset_key = request.args.get('preset') or ''
    von = _form_to_date(request.args.get('von'))
    bis = _form_to_date(request.args.get('bis'))
    if preset_key:
        for p in m.zeitraum_presets():
            if p['key'] == preset_key:
                von, bis = p['von'], p['bis']
                break
    umsaetze = m.umsaetze_liste(
        konto_id=konto_id, suche=suche, suche_regex=suche_regex,
        von_datum=von, bis_datum=bis,
        art_filter=art_filter, umsatztyp_id=umsatztyp_id,
        nur_ungeprueft=nur_ungeprueft,
        limit=500,
    )
    return render_template(
        'banking_konto.html',
        konto=konto, umsaetze=umsaetze,
        arten=m.umsatz_arten(),
        umsatztypen=m.umsatztypen_liste(),
        zeitraum_presets=m.zeitraum_presets(),
        suche=suche, suche_regex=suche_regex,
        art_filter=art_filter, umsatztyp_id=umsatztyp_id,
        nur_ungeprueft=nur_ungeprueft, preset_key=preset_key,
        von=(von.strftime('%d.%m.%Y') if von else ''),
        bis=(bis.strftime('%d.%m.%Y') if bis else ''),
    )


# ── Edit-Endpunkte fuer Geprueft / Notiz / Kategorie ──────────


@bp.post('/umsatz/<int:umsatz_id>/geprueft')
def api_umsatz_geprueft(umsatz_id: int):
    _login_check()
    body = request.get_json(silent=True) or {}
    geprueft = bool(body.get('geprueft'))
    try:
        m.umsatz_geprueft_setzen(umsatz_id, geprueft)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'geprueft': geprueft})


@bp.post('/umsatz/<int:umsatz_id>/notiz')
def api_umsatz_notiz(umsatz_id: int):
    _login_check()
    body = request.get_json(silent=True) or {}
    notiz = str(body.get('notiz') or '')
    try:
        m.umsatz_notiz_setzen(umsatz_id, notiz)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'notiz': notiz.strip()})


@bp.post('/umsatz/<int:umsatz_id>/kategorie')
def api_umsatz_kategorie(umsatz_id: int):
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('umsatztyp_id')
    if raw in (None, '', 0):
        kat_id = None
    else:
        try:
            kat_id = int(raw)
        except (TypeError, ValueError):
            return jsonify({'ok': False,
                            'fehler': 'umsatztyp_id muss int sein'}), 400
    try:
        m.umsatz_kategorie_setzen(umsatz_id, kat_id)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'umsatztyp_id': kat_id})


@bp.get('/sepa-ueberweisungen')
def sepa_ueb_liste():
    _login_check()
    konten = m.konten_liste()
    konto_id = request.args.get('konto_id', type=int)
    sepasueb = m.sepa_ueberweisungen_liste(konto_id=konto_id)
    return render_template(
        'banking_sepa_ueb.html',
        konten=konten, konto_id=konto_id, sepasueb=sepasueb,
    )


@bp.get('/sepa-ueberweisungen/<int:rec_id>')
def sepa_ueb_detail(rec_id: int):
    _login_check()
    detail = m.sepa_ueberweisung_detail(rec_id)
    if not detail:
        abort(404)
    return render_template('banking_sepa_ueb_detail.html', kopf=detail)


def create_blueprint():
    return bp
