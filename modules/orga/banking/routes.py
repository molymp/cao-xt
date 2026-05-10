"""
Dorfkern Banking — Flask-Routes (Phase E.1, read-only).
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
    art_filter = request.args.get('art') or None
    von = _form_to_date(request.args.get('von'))
    bis = _form_to_date(request.args.get('bis'))
    umsaetze = m.umsaetze_liste(
        konto_id=konto_id, suche=suche,
        von_datum=von, bis_datum=bis, art_filter=art_filter,
        limit=300,
    )
    arten = m.umsatz_arten()
    return render_template(
        'banking_konto.html',
        konto=konto, umsaetze=umsaetze, arten=arten,
        suche=suche, art_filter=art_filter,
        von=(von.strftime('%d.%m.%Y') if von else ''),
        bis=(bis.strftime('%d.%m.%Y') if bis else ''),
    )


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
