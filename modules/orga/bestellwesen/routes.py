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
    """Diagnose-Endpunkt: welche STADIUM-Codes kommen in EKBESTELL +
    EKBESTELL_POS vor?

    Hilft, das Mapping in models.STADIUM_LABEL ggf. zu ergänzen.
    """
    _login_check()
    return jsonify(m.stadium_codes_in_use())


@bp.post('/api/heile-positions-stadium')
def api_heile_positions_stadium() -> Any:
    """Einmal-Migration: alte EKBESTELL_POS.STADIUM=0 auf 2 setzen für
    offene Bestellungen.

    Ursache: vor dem 2026-05-08 wurden Positionen mit STADIUM=0 (->"??-[0]")
    angelegt. Hiermit nachträglich auf 2 (offen) angehoben.
    """
    _login_check()
    return jsonify(m.heile_alte_positions_stadium())


# ── Stufe 2: Schreib-Endpunkte ──────────────────────────────────────────────


def _request_datum() -> Any:
    """Liest 'datum' aus dem JSON-Body, erlaubt leer/None zum Löschen."""
    body = request.get_json(silent=True) or {}
    raw = (body.get('datum') or '').strip()
    if not raw:
        return None
    return _form_to_date(raw)


@bp.post('/<int:rec_id>/api/liefertermin')
def api_kopf_liefertermin(rec_id: int) -> Any:
    """Setzt den Liefertermin auf alle bearbeitbaren Positionen einer Bestellung."""
    _login_check()
    datum = _request_datum()
    try:
        n = m.kopf_liefertermin_setzen(rec_id, datum)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'positionen_geaendert': n,
                    'datum': datum.isoformat() if datum else None})


@bp.post('/<int:rec_id>/api/positionen/<int:pos_id>/liefertermin')
def api_pos_liefertermin(rec_id: int, pos_id: int) -> Any:
    """Setzt den Liefertermin einer einzelnen Position (EKBESTELL_INFO)."""
    _login_check()
    datum = _request_datum()
    try:
        m.position_liefertermin_setzen(pos_id, datum)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True,
                    'datum': datum.isoformat() if datum else None})


@bp.post('/<int:rec_id>/api/positionen/<int:pos_id>/status')
def api_pos_status(rec_id: int, pos_id: int) -> Any:
    """Setzt den STADIUM-Code einer Position."""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        stadium = int(body.get('stadium'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'stadium fehlt oder ungueltig'}), 400
    try:
        m.position_status_setzen(pos_id, stadium)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'stadium': stadium,
                    'label': m._stadium_label_pos(stadium)})


@bp.post('/<int:rec_id>/api/storno')
def api_bestellung_storno(rec_id: int) -> Any:
    """Storniert die komplette Bestellung (EKBESTELL + alle EKBESTELL_POS auf 127)."""
    _login_check()
    try:
        ergebnis = m.bestellung_stornieren(rec_id)
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify({'ok': True, **ergebnis})


@bp.post('/<int:rec_id>/api/metadata')
def api_kopf_metadata(rec_id: int) -> Any:
    """Setzt Header-Metadaten (LIEF_AB, TERMIN). INFO bewusst ausgeklammert
    weil es als RTF gespeichert wird — Plain-Text aus dem Frontend würde
    den RTF-Header zerstören.
    """
    _login_check()
    body = request.get_json(silent=True) or {}
    lief_ab = body.get('lief_ab', None)
    if lief_ab is not None:
        lief_ab = str(lief_ab).strip()
    termin_raw = body.get('termin', None)
    termin = _form_to_date(termin_raw) if termin_raw else None
    if termin_raw == '':
        termin = None  # leer = TERMIN auf NULL setzen
    try:
        m.kopf_metadata_setzen(rec_id, lief_ab=lief_ab, termin=termin)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True})


@bp.post('/<int:rec_id>/api/positionen/<int:pos_id>/lieferpreis')
def api_pos_lieferpreis(rec_id: int, pos_id: int) -> Any:
    """Setzt LIEFPREIS einer Position (+ GLIEFPREIS = LIEFPREIS × MENGE)."""
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('lieferpreis')
    if raw is None or str(raw).strip() == '':
        return jsonify({'ok': False, 'fehler': 'lieferpreis fehlt'}), 400
    try:
        lpreis = float(str(raw).replace(',', '.'))
    except ValueError:
        return jsonify({'ok': False, 'fehler': 'lieferpreis nicht numerisch'}), 400
    if lpreis < 0:
        return jsonify({'ok': False, 'fehler': 'lieferpreis muss >= 0 sein'}), 400
    try:
        result = m.position_lieferpreis_setzen(pos_id, lpreis)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/<int:rec_id>/api/rest-nicht-lieferbar')
def api_rest_nicht_lieferbar(rec_id: int) -> Any:
    """Setzt alle Positionen mit STADIUM in (2,3) auf 8 — schließt damit
    die Bestellung mit „Rest nicht lieferbar" ab."""
    _login_check()
    try:
        ergebnis = m.bestellung_rest_nicht_lieferbar(rec_id)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **ergebnis})


def create_blueprint():
    return bp
