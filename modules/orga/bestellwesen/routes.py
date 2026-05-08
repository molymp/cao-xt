"""
CAO-XT Orga-Bestellwesen – Flask-Blueprint (Phase 1: Übersicht read-only).

Endpunkte:
    GET  /orga/bestellwesen/
    GET  /orga/bestellwesen/<int:rec_id>            – Detail (Header + Positionen)
    GET  /orga/bestellwesen/api/stadium-codes       – Diagnose: welche STADIUM-Codes
                                                       kommen in EKBESTELL real vor?

Schreibvorgänge (Liefertermin anpassen, Position-Status, Storno) folgen
in Phase 2. Hier keine UI-Aktionen die EKBESTELL/EKBESTELL_POS verändern.
"""
from datetime import datetime, date
from typing import Any

from flask import Blueprint, render_template, request, jsonify, abort, session

from . import models as m


bp = Blueprint('orga_bestellwesen', __name__, template_folder=None)


def _login_check() -> None:
    """Hard-Stopp wenn keine Orga-Session vorliegt — analog Hauptblueprint."""
    if not session.get('mitarbeiter'):
        abort(403)


def _form_to_date(val: str | None) -> date | None:
    val = (val or '').strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except ValueError:
        return None


@bp.get('/')
def uebersicht():
    """Übersicht aller Lieferanten-Bestellungen (EKBESTELL)."""
    _login_check()
    suche       = (request.args.get('q') or '').strip()
    stadium_raw = (request.args.get('stadium') or '').strip()
    von_datum   = _form_to_date(request.args.get('von'))
    bis_datum   = _form_to_date(request.args.get('bis'))
    stadium     = int(stadium_raw) if stadium_raw.isdigit() else None

    bestellungen = m.bestellungen_liste(
        suche=suche,
        stadium=stadium,
        von_datum=von_datum,
        bis_datum=bis_datum,
    )

    return render_template(
        'bestellwesen.html',
        bestellungen=bestellungen,
        suche=suche,
        stadium=stadium,
        von_datum=von_datum,
        bis_datum=bis_datum,
        stadium_label=m.STADIUM_LABEL,
    )


@bp.get('/<int:rec_id>')
def detail(rec_id: int):
    """Detail-Ansicht einer Bestellung (read-only, Phase 1)."""
    _login_check()
    daten = m.bestellung_detail(rec_id)
    if not daten:
        abort(404)
    return render_template(
        'bestellwesen_detail.html',
        kopf=daten['kopf'],
        positionen=daten['positionen'],
        stadium_label=m.STADIUM_LABEL,
    )


@bp.get('/api/stadium-codes')
def api_stadium_codes() -> Any:
    """Diagnose-Endpunkt: welche STADIUM-Codes kommen in EKBESTELL vor?

    Hilft, das Mapping in models.STADIUM_LABEL ggf. zu ergänzen.
    """
    _login_check()
    return jsonify(m.stadium_codes_in_use())


def create_blueprint():
    return bp
