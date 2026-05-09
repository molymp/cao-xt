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
from . import wareneingang as we


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


# ── Wareneingang (Phase A: Erfassen ohne Buchen) ────────────────────


@bp.post('/<int:rec_id>/api/wareneingang-anlegen')
def api_wareneingang_anlegen(rec_id: int) -> Any:
    """Erstellt einen EKEINGANG-Beleg aus einer EKBESTELL."""
    _login_check()
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        ergebnis = we.wareneingang_anlegen(rec_id, ma_id, ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(ergebnis)


@bp.get('/wareneingang/')
def wareneingang_uebersicht():
    """Liste aller EKEINGANG-Belege."""
    _login_check()
    suche = (request.args.get('q') or '').strip()
    stadium_raw = (request.args.get('stadium') or '').strip()
    stadium = int(stadium_raw) if stadium_raw.isdigit() else None
    eingaenge = we.wareneingang_liste(suche=suche, stadium=stadium)
    return render_template(
        'wareneingang.html',
        eingaenge=eingaenge,
        suche=suche,
        stadium=stadium,
        stadium_label=we.STADIUM_LABEL_KOPF,
    )


@bp.get('/wareneingang/<int:rec_id>')
def wareneingang_detail(rec_id: int):
    """Detail-Ansicht eines Wareneingangs (Pos-Tabelle, editierbar)."""
    _login_check()
    daten = we.wareneingang_detail(rec_id)
    if not daten:
        abort(404)
    # Offene Bestellungen werden jetzt lazy via JS geholt (siehe
    # /api/offene-bestellungen) — spart 1-2s beim Page-Load.
    return render_template(
        'wareneingang_detail.html',
        kopf=daten['kopf'],
        positionen=daten['positionen'],
        stadium_label=we.STADIUM_LABEL_KOPF,
    )


@bp.post('/wareneingang/<int:rec_id>/api/positionen/<int:pos_id>/menge')
def api_we_pos_menge(rec_id: int, pos_id: int) -> Any:
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('menge')
    try:
        menge = float(str(raw).replace(',', '.'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'menge fehlt/ungültig'}), 400
    try:
        result = we.pos_menge_setzen(rec_id, pos_id, menge)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/positionen/<int:pos_id>/epreis')
def api_we_pos_epreis(rec_id: int, pos_id: int) -> Any:
    """Stub: EKEINGANG_POS hat keine Preisspalte — EPREIS wird ueber die
    EK-Rechnung gepflegt, nicht im Wareneingang. Der Endpunkt liefert
    eine klare Fehlermeldung statt einem 500-Crash."""
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('epreis') or body.get('lieferpreis')  # alt-kompatibel
    try:
        ep = float(str(raw).replace(',', '.'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'epreis ungültig'}), 400
    try:
        result = we.pos_epreis_setzen(rec_id, pos_id, ep)
    except (LookupError, PermissionError, ValueError, NotImplementedError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/scan')
def api_we_scan(rec_id: int) -> Any:
    """Barcode-Scan: erkennt Stück- oder Gebinde-EAN, erhöht die
    passende Position-Menge entsprechend."""
    _login_check()
    body = request.get_json(silent=True) or {}
    ean = (body.get('ean') or '').strip()
    if not ean:
        return jsonify({'ok': False, 'fehler': 'EAN fehlt'}), 400
    try:
        result = we.scan_ean(rec_id, ean)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.get('/wareneingang/<int:rec_id>/api/offene-bestellungen')
def api_we_offene_bestellungen(rec_id: int) -> Any:
    """Listet offene Bestellpositionen für den Lieferanten dieses Wareneingangs."""
    _login_check()
    try:
        zeilen = we.offene_bestell_positionen(rec_id)
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify({'ok': True, 'zeilen': zeilen})


@bp.post('/wareneingang/<int:rec_id>/api/positionen/anhaengen')
def api_we_pos_anhaengen(rec_id: int) -> Any:
    """Hängt eine Bestellposition als neue EKEINGANG_POS-Zeile an."""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        bestell_pos_id = int(body.get('bestell_pos_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'bestell_pos_id fehlt/ungültig'}), 400
    raw_menge = body.get('menge')
    menge: float | None = None
    if raw_menge is not None and str(raw_menge).strip() != '':
        try:
            menge = float(str(raw_menge).replace(',', '.'))
        except ValueError:
            return jsonify({'ok': False, 'fehler': 'menge ungültig'}), 400
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = we.pos_aus_bestellpos_anhaengen(rec_id, bestell_pos_id, menge, ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/positionen/<int:pos_id>/entfernen')
def api_we_pos_entfernen(rec_id: int, pos_id: int) -> Any:
    """Entfernt eine einzelne ungebuchte Position."""
    _login_check()
    try:
        result = we.pos_entfernen(rec_id, pos_id)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/positionen/entfernen-bulk')
def api_we_pos_entfernen_bulk(rec_id: int) -> Any:
    """Entfernt mehrere ungebuchte Positionen in einem Roundtrip."""
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('pos_ids') or []
    ids: list[int] = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    try:
        result = we.pos_entfernen_bulk(rec_id, ids)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


# ── Wareneingang Buchen (Phase B) ────────────────────────────────────


@bp.get('/wareneingang/<int:rec_id>/api/buchen-vorbereitung')
def api_we_buchen_vorbereitung(rec_id: int) -> Any:
    """Liefert Pos + aktuelle Lief-Preise — fuer das Buchen-Modal."""
    _login_check()
    try:
        return jsonify({'ok': True, **we.buchen_vorbereitung(rec_id)})
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400


@bp.post('/wareneingang/<int:rec_id>/api/buchen')
def api_we_buchen(rec_id: int) -> Any:
    """Bucht den Wareneingang. Erwartet im Body optional eine Liste
    ``preis_uebernahmen`` mit ``{pos_id, neuer_preis, neuer_vpe?,
    alt_preis, uebernehmen}``-Eintraegen — fuer markierte Pos werden
    ARTIKEL_PREIS und VK-Kontrolle aktualisiert."""
    _login_check()
    body = request.get_json(silent=True) or {}
    pue = body.get('preis_uebernahmen') or []
    if not isinstance(pue, list):
        return jsonify({'ok': False, 'fehler': 'preis_uebernahmen muss Liste sein'}), 400
    ma_id = session.get('ma_id')
    ma_name = session.get('ma_name') or session.get('login_name') or 'CAO-XT'
    try:
        result = we.buchen(rec_id, ma_id, ma_name, preis_uebernahmen=pue)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


# ── Common-Picker-Endpunkte (Artikel + Adresse) ──────────────────────


@bp.get('/api/picker/wgs')
def api_picker_wgs() -> Any:
    """Warengruppen-Baum für den Common-Picker."""
    _login_check()
    from common.picker_data import warengruppen_baum
    return jsonify({'ok': True, 'zeilen': warengruppen_baum()})


def _arg_lief_addr() -> int | None:
    """Holt die optionale lief_addr_id aus den Query-Parametern."""
    raw = request.args.get('lief_addr_id', '').strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


@bp.get('/api/picker/artikel')
def api_picker_artikel() -> Any:
    """Artikel einer Warengruppe (rekursiv) für den Common-Picker."""
    _login_check()
    from common.picker_data import artikel_in_warengruppe
    raw_wg = request.args.get('wg', '0').strip()
    try:
        wg = int(raw_wg)
    except ValueError:
        wg = 0
    return jsonify({'ok': True,
                    'zeilen': artikel_in_warengruppe(
                        wg if wg > 0 else None,
                        lief_addr_id=_arg_lief_addr())})


@bp.get('/api/picker/artikel/suche')
def api_picker_artikel_suche() -> Any:
    """Volltextsuche Artikel."""
    _login_check()
    from common.picker_data import artikel_volltext_suche
    q = request.args.get('q', '').strip()
    return jsonify({'ok': True, 'zeilen': artikel_volltext_suche(
        q, lief_addr_id=_arg_lief_addr())})


def _arg_typ_filter() -> str | None:
    raw = (request.args.get('typ', '') or '').strip().lower()
    return raw if raw in ('lief', 'kunde') else None


@bp.get('/api/picker/adressgruppen')
def api_picker_adressgruppen() -> Any:
    """Adressgruppen aus ``ADRESSGRUPPEN``."""
    _login_check()
    from common.picker_data import adressgruppen
    return jsonify({'ok': True, 'zeilen': adressgruppen(_arg_typ_filter())})


@bp.get('/api/picker/adressen')
def api_picker_adressen() -> Any:
    """Adressen einer Gruppe."""
    _login_check()
    from common.picker_data import adressen_in_gruppe
    grp = (request.args.get('grp', '') or '').strip()
    return jsonify({'ok': True,
                    'zeilen': adressen_in_gruppe(grp or None,
                                                 typ_filter=_arg_typ_filter())})


@bp.get('/api/picker/adressen/suche')
def api_picker_adressen_suche() -> Any:
    """Volltextsuche Adressen (innerhalb einer Gruppe)."""
    _login_check()
    from common.picker_data import adressen_in_gruppe
    q = request.args.get('q', '').strip()
    grp = (request.args.get('grp', '') or '').strip()
    return jsonify({'ok': True,
                    'zeilen': adressen_in_gruppe(grp or None, suche=q,
                                                 typ_filter=_arg_typ_filter())})


@bp.get('/wareneingang/api/lieferant-suche')
def api_we_lieferant_suche() -> Any:
    """Suche fuer Lieferanten-Picker (Wareneingang neu anlegen)."""
    _login_check()
    q = (request.args.get('q') or '').strip()
    return jsonify({'ok': True, 'zeilen': we.lieferant_suche(q)})


@bp.get('/wareneingang/api/artikel-suche')
def api_we_artikel_suche() -> Any:
    """Suche fuer Artikel-Picker (Pos manuell anhaengen)."""
    _login_check()
    q = (request.args.get('q') or '').strip()
    return jsonify({'ok': True, 'zeilen': we.artikel_suche(q)})


@bp.post('/wareneingang/api/neu')
def api_we_neu() -> Any:
    """Legt einen leeren Wareneingang fuer einen Lieferanten an (ohne Bestellung)."""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        addr_id = int(body.get('addr_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'addr_id fehlt/ungültig'}), 400
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = we.wareneingang_anlegen_leer(addr_id, ma_id, ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/wareneingang/<int:rec_id>/api/positionen/artikel-anhaengen')
def api_we_artikel_anhaengen(rec_id: int) -> Any:
    """Haengt einen oder mehrere Artikel als neue EKEINGANG_POS-Zeilen an.

    Body: ``{artikel_id: <int>, menge: <float?>}`` ODER
          ``{artikel_ids: [<int>, ...]}`` (Bulk; Reihenfolge bleibt erhalten).
    """
    _login_check()
    body = request.get_json(silent=True) or {}
    ma_name = session.get('login_name') or session.get('mitarbeiter')

    # Bulk-Variante
    if isinstance(body.get('artikel_ids'), list):
        ids = []
        for x in body['artikel_ids']:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                pass
        try:
            result = we.pos_artikel_anhaengen_bulk(rec_id, ids, ma_name)
        except (LookupError, PermissionError, ValueError) as e:
            return jsonify({'ok': False, 'fehler': str(e)}), 400
        return jsonify({'ok': True, **result})

    # Single
    try:
        artikel_id = int(body.get('artikel_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'artikel_id fehlt/ungültig'}), 400
    raw_menge = body.get('menge') or 0
    try:
        menge = float(str(raw_menge).replace(',', '.'))
    except ValueError:
        menge = 0.0
    try:
        result = we.pos_artikel_anhaengen(rec_id, artikel_id, menge, ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/storno')
def api_we_storno(rec_id: int) -> Any:
    _login_check()
    try:
        result = we.storno(rec_id)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


def create_blueprint():
    return bp
