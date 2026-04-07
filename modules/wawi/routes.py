"""
CAO-XT WaWi-Modul – Flask-Blueprint (Phase 1: Artikelpreispflege & VK-Ermittlung)

Registrierung:
    app.register_blueprint(bp, url_prefix='/wawi')

Alle schreibenden Endpunkte erwarten JSON; Authentifizierung gegen CAO-MITARBEITER-Tabelle
(analog kasse-app, MD5-Hash in Großbuchstaben).
"""

from flask import Blueprint, jsonify, request, session, abort, Response
import json
import models as m

bp = Blueprint('wawi', __name__)


def _benutzer() -> str:
    """Aktuell eingeloggten Benutzer aus Session; JSON-403 wenn nicht gesetzt."""
    user = session.get('mitarbeiter')
    if not user:
        # abort() mit Response-Objekt statt int, damit API-Endpunkte JSON zurückgeben
        abort(Response(
            json.dumps({'error': 'Nicht angemeldet'}),
            403,
            {'Content-Type': 'application/json'},
        ))
    return user


# ── Artikel ───────────────────────────────────────────────────────────────────

@bp.get('/api/artikel/suche')
def api_artikel_suche():
    """
    GET /wawi/api/artikel/suche?q=<suchbegriff>&limit=50

    Sucht in ARTNUM, KURZNAME, KAS_NAME, BARCODE (CAO read-only).
    """
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    limit = min(int(request.args.get('limit', 50)), 200)
    return jsonify(m.artikel_suche(q, limit))


@bp.get('/api/artikel/<artnum>')
def api_artikel_detail(artnum: str):
    """GET /wawi/api/artikel/<artnum> – Artikeldetails inkl. aktueller VK-Preise."""
    artikel = m.artikel_by_artnum(artnum)
    if not artikel:
        abort(404)
    return jsonify(artikel)


# ── VK-Ermittlung ─────────────────────────────────────────────────────────────

@bp.get('/api/artikel/<artnum>/vk')
def api_vk(artnum: str):
    """
    GET /wawi/api/artikel/<artnum>/vk?ebene=5

    Gibt den aktuell gültigen VK-Preis zurück (Quelle: wawi | aktion | cao).
    """
    ebene = int(request.args.get('ebene', 5))
    if ebene not in range(1, 6):
        return jsonify({'error': 'Preisebene muss zwischen 1 und 5 liegen'}), 400
    try:
        return jsonify(m.vk_berechnen(artnum, ebene))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


# ── Preispflege ───────────────────────────────────────────────────────────────

@bp.get('/api/artikel/<artnum>/preise')
def api_preishistorie(artnum: str):
    """
    GET /wawi/api/artikel/<artnum>/preise

    Komplette append-only Preishistorie für alle Ebenen.
    """
    return jsonify(m.preishistorie_fuer_artikel(artnum))


@bp.post('/api/artikel/<artnum>/preise')
def api_preis_setzen(artnum: str):
    """
    POST /wawi/api/artikel/<artnum>/preise

    Body (JSON):
        {
            "preisebene":     5,
            "preis_brutto_ct": 199,     ← Cent!
            "gueltig_ab":     "2026-04-01",
            "gueltig_bis":    null,      ← optional; null = unbefristet
            "kommentar":      "Frühjahrsanpassung"
        }

    GoBD: bestehender Preis wird soft-closed (GUELTIG_BIS gesetzt),
    neuer Eintrag wird append-only angelegt.
    """
    benutzer = _benutzer()
    data = request.get_json(force=True)

    required = ('preisebene', 'preis_brutto_ct', 'gueltig_ab')
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'Fehlende Felder: {missing}'}), 400

    preisebene = int(data['preisebene'])
    if preisebene not in range(1, 6):
        return jsonify({'error': 'Preisebene 1–5'}), 400

    preis_ct = int(data['preis_brutto_ct'])
    if preis_ct < 0:
        return jsonify({'error': 'Preis darf nicht negativ sein'}), 400

    try:
        rec_id = m.preis_setzen(
            artnum=artnum,
            preisebene=preisebene,
            preis_brutto_ct=preis_ct,
            gueltig_ab=data['gueltig_ab'],
            gueltig_bis=data.get('gueltig_bis'),
            benutzer=benutzer,
            kommentar=data.get('kommentar', ''),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({'ok': True, 'rec_id': rec_id}), 201


@bp.get('/api/preishistorie')
def api_preishistorie_alle():
    """
    GET /wawi/api/preishistorie?artnum=<optional>&limit=200&offset=0

    Gesamtübersicht der Preishistorie (Audit-Log).
    """
    artnum = request.args.get('artnum') or None
    limit = min(int(request.args.get('limit', 200)), 1000)
    offset = int(request.args.get('offset', 0))
    return jsonify(m.preishistorie_alle(limit=limit, offset=offset, artnum=artnum))


# ── Preispflege-Tabelle (HAB-235) ─────────────────────────────────────────────

@bp.get('/api/warengruppen')
def api_warengruppen():
    """GET /wawi/api/warengruppen – Alle Warengruppen für Filter-Dropdown."""
    return jsonify(m.warengruppen_liste())


@bp.get('/api/warengruppen/mit-faktor')
def api_warengruppen_mit_faktor():
    """GET /wawi/api/warengruppen/mit-faktor – Warengruppen mit Durchschnitts-Faktor."""
    return jsonify(m.warengruppen_mit_faktor())


@bp.get('/api/preispflege')
def api_preispflege():
    """
    GET /wawi/api/preispflege?wgr_id=<optional>

    Liefert alle aktiven Artikel (ARTIKELTYP N/F/S, nicht gelöscht, keine
    VK-Sperre) mit EK, VK5, Typ und Faktor. Optional gefiltert nach Warengruppe.
    """
    wgr_id = request.args.get('wgr_id')
    try:
        wgr_id_int = int(wgr_id) if wgr_id else None
    except (TypeError, ValueError):
        return jsonify({'error': 'wgr_id muss eine Ganzzahl sein'}), 400
    return jsonify(m.preispflege_liste(wgr_id=wgr_id_int))


@bp.get('/api/artikel/<artnr>/lieferanten')
def api_artikel_lieferanten(artnr: str):
    """
    GET /wawi/api/artikel/<artnr>/lieferanten

    Lieferantenpreise für einen Artikel.
    Rückgabe: [{lief_nr, lief_name, lief_artnr, ek_preis, vpe}, ...]
    Leere Liste wenn keine Lieferantendaten vorhanden oder Tabelle fehlt.
    """
    return jsonify(m.lieferantenpreise_fuer_artikel(artnr))


@bp.patch('/api/artikel/<artnr>/vk5')
def api_artikel_vk5_setzen(artnr: str):
    """
    PATCH /wawi/api/artikel/<artnr>/vk5
    Body: { "vk5": 2.49 }  — Brutto-VK5 in Euro

    Schreibt direkt ARTIKEL.VK5B (CAO-Stammdatenpflege).
    """
    _benutzer()
    data = request.get_json(force=True) or {}
    if 'vk5' not in data:
        return jsonify({'error': 'Feld vk5 fehlt'}), 400
    try:
        vk5 = float(data['vk5'])
    except (TypeError, ValueError):
        return jsonify({'error': 'vk5 muss eine Zahl sein'}), 400
    try:
        result = m.artikel_vk5_setzen(artnr, vk5)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(result)


@bp.patch('/api/artikel/<artnr>/ek')
def api_artikel_ek_setzen(artnr: str):
    """
    PATCH /wawi/api/artikel/<artnr>/ek
    Body: { "ek": 1.20 }  — EK in Euro

    Schreibt direkt ARTIKEL.EK_PREIS (CAO-Stammdatenpflege).
    """
    _benutzer()
    data = request.get_json(force=True) or {}
    if 'ek' not in data:
        return jsonify({'error': 'Feld ek fehlt'}), 400
    try:
        ek = float(data['ek'])
    except (TypeError, ValueError):
        return jsonify({'error': 'ek muss eine Zahl sein'}), 400
    try:
        result = m.artikel_ek_setzen(artnr, ek)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(result)
