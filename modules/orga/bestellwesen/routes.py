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
from . import einkauf as ek


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


# ── Wareneingang Buchen (Phase B): Lieferschein abschliessen ───────


@bp.post('/wareneingang/<int:rec_id>/api/lieferschein')
def api_we_lieferschein_setzen(rec_id: int) -> Any:
    """Setzt LIEFNUM / LIEFDATUM auf einem offenen Wareneingang."""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        result = we.lieferschein_setzen(
            rec_id,
            liefnum=body.get('liefnum'),
            liefdatum=body.get('liefdatum'),
        )
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/wareneingang/<int:rec_id>/api/buchen')
def api_we_buchen(rec_id: int) -> Any:
    """Bucht den Wareneingang. LIEFNUM + LIEFDATUM sind verpflichtend."""
    _login_check()
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    ma_name = session.get('ma_name') or session.get('login_name') or 'CAO-XT'
    try:
        result = we.buchen(
            rec_id, ma_id, ma_name,
            liefnum=body.get('liefnum'),
            liefdatum=body.get('liefdatum'),
        )
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


# ── Einkauf (= EK-Rechnung, Phase C) ────────────────────────────────


@bp.get('/einkauf/')
def einkauf_uebersicht():
    """Liste aller Einkaufs-Belege (in Bearbeitung + verbucht)."""
    _login_check()
    suche = (request.args.get('q') or '').strip()
    stadium_raw = (request.args.get('stadium') or '').strip()
    stadium = int(stadium_raw) if stadium_raw.isdigit() else None
    eintraege = ek.einkauf_liste(suche=suche, stadium=stadium)
    return render_template(
        'einkauf.html',
        eintraege=eintraege,
        suche=suche,
        stadium=stadium,
        stadium_label=ek.STADIUM_LABEL,
    )


@bp.get('/einkauf/<int:rec_id>')
def einkauf_detail(rec_id: int):
    _login_check()
    daten = ek.einkauf_detail(rec_id)
    if not daten:
        abort(404)
    return render_template(
        'einkauf_detail.html',
        kopf=daten['kopf'],
        positionen=daten['positionen'],
        stadium_label=ek.STADIUM_LABEL,
    )


@bp.post('/einkauf/api/neu')
def api_ek_neu() -> Any:
    """Legt einen Einkaufs-Beleg an. Akzeptiert optional `addr_id` —
    der Lieferant wird dann gleich beim INSERT in den Header
    geschrieben."""
    _login_check()
    body = request.get_json(silent=True) or {}
    raw_addr = body.get('addr_id')
    addr_id: int | None = None
    if raw_addr is not None:
        try:
            addr_id = int(raw_addr)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'fehler': 'addr_id ungültig'}), 400
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.einkauf_anlegen(ma_id, ma_name, addr_id=addr_id)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/storno')
def api_ek_storno(rec_id: int) -> Any:
    """Storno fuer in-Bearbeitung-Beleg (DELETE) ODER fuer gebuchten
    Beleg (STADIUM=127, undo side-effects). Wird automatisch je nach
    QUELLE-Wert gewaehlt.
    """
    _login_check()
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        # Erst pruefen ob in-Bearbeitung oder gebucht
        pruef = ek.einkauf_storno_pruefung(rec_id)
        kopf = pruef['kopf']
        if int(kopf.get('QUELLE') or 0) == 15:
            result = ek.einkauf_storno(rec_id)
        else:
            result = ek.einkauf_storno_gebucht(
                rec_id, ma_id=ma_id, ma_name=ma_name)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.get('/einkauf/<int:rec_id>/api/storno-pruefung')
def api_ek_storno_pruefung(rec_id: int) -> Any:
    _login_check()
    try:
        result = ek.einkauf_storno_pruefung(rec_id)
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify(result)


@bp.post('/einkauf/<int:rec_id>/api/kopieren')
def api_ek_kopieren(rec_id: int) -> Any:
    _login_check()
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.einkauf_kopieren(rec_id, ma_id=ma_id, ma_name=ma_name)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/einkauf/<int:rec_id>/api/storno-und-kopieren')
def api_ek_storno_und_kopieren(rec_id: int) -> Any:
    _login_check()
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.einkauf_storno_und_kopieren(
            rec_id, ma_id=ma_id, ma_name=ma_name)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


# ── Phase D: Zahlungs-Erfassung ─────────────────────────────────


@bp.get('/einkauf/<int:rec_id>/api/zahlungen')
def api_ek_zahlungen(rec_id: int) -> Any:
    """Liste aller Zahlungen zur EK-Rechnung + Zahlungsarten-Stamm
    fuer das Erfassungs-Modal."""
    _login_check()
    try:
        d = ek.zahlungen_zu_einkauf(rec_id)
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify({
        'ok': True,
        'zahlungen':     d['zahlungen'],
        'ziel_info':     d['ziel_info'],
        'zahlungsarten': ek.zahlungsarten_aktiv(),
    })


@bp.post('/einkauf/<int:rec_id>/api/zahlungen')
def api_ek_zahlung_erfassen(rec_id: int) -> Any:
    """Erfasst eine Zahlung manuell. Body:
       {betrag, datum, valuta?, zahlart_id?, skonto_proz?, skonto_betrag?,
        belegnum?, verw_zweck?}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.einkauf_zahlung_erfassen(
            rec_id,
            betrag=float(body.get('betrag') or 0),
            datum=body.get('datum'),
            valuta=body.get('valuta'),
            zahlart_id=int(body['zahlart_id'])
                       if body.get('zahlart_id') not in (None, '') else None,
            fibu_kto=int(body['fibu_kto'])
                     if body.get('fibu_kto') not in (None, '') else None,
            skonto_proz=float(body.get('skonto_proz') or 0),
            skonto_betrag=float(body.get('skonto_betrag') or 0),
            belegnum=str(body.get('belegnum') or ''),
            verw_zweck=str(body.get('verw_zweck') or ''),
            ma_id=ma_id, ma_name=ma_name,
        )
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/einkauf/<int:rec_id>/api/vormerken-hibiscus')
def api_ek_vormerken_hibiscus(rec_id: int) -> Any:
    """Phase E.2: legt für die offene EK-Rechnung eine SEPA-Über­
    weisung in Hibiscus an (Status „offen") und setzt STADIUM=11.
    Das Senden mit S-pushTAN macht der Mensch in der Jameica-GUI."""
    _login_check()
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.vormerken_via_hibiscus(
            rec_id, ma_id=ma_id, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 502
    return jsonify(result)


@bp.get('/einkauf/<int:rec_id>/api/bankumsatz-kandidaten')
def api_ek_bankumsatz_kandidaten(rec_id: int) -> Any:
    """Hibiscus-Bankumsatz-Match-Kandidaten fuer offenen EK-Beleg."""
    _login_check()
    try:
        kandidaten = ek.bankumsatz_kandidaten_fuer_einkauf(rec_id)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'kandidaten': kandidaten})


@bp.post('/einkauf/<int:rec_id>/api/bankumsatz-uebernehmen')
def api_ek_bankumsatz_uebernehmen(rec_id: int) -> Any:
    """Uebernimmt einen Hibiscus-Umsatz als ZAHLUNGEN-Eintrag.
    Body: ``{umsatz_id: int}``"""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        umsatz_id = int(body.get('umsatz_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'umsatz_id muss int sein'}), 400
    if umsatz_id <= 0:
        return jsonify({'ok': False, 'fehler': 'umsatz_id fehlt'}), 400
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.bankumsatz_uebernehmen(
            rec_id, umsatz_id, ma_id=ma_id, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/einkauf/zahlungen/<int:zahlung_id>/storno')
def api_ek_zahlung_storno(zahlung_id: int) -> Any:
    """Storniert eine Zahlung. Body: {grund: str (Pflicht)}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.einkauf_zahlung_stornieren(
            zahlung_id,
            grund=str(body.get('grund') or ''),
            ma_id=ma_id, ma_name=ma_name,
        )
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


# ── Einkauf Pos-Operationen (Phase C.2) ────────────────────────────


@bp.get('/einkauf/<int:rec_id>/api/offene-we')
def api_ek_offene_we(rec_id: int) -> Any:
    _login_check()
    try:
        return jsonify({'ok': True, 'zeilen': ek.offene_we_des_lieferanten(rec_id)})
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400


@bp.get('/einkauf/<int:rec_id>/api/offene-bestellpos')
def api_ek_offene_bestellpos(rec_id: int) -> Any:
    _login_check()
    try:
        return jsonify({'ok': True, 'zeilen': ek.offene_bestellpos_des_lieferanten(rec_id)})
    except LookupError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400


@bp.post('/einkauf/<int:rec_id>/api/pos/aus-we')
def api_ek_pos_aus_we(rec_id: int) -> Any:
    """Body: {ekeingang_id}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        we_id = int(body.get('ekeingang_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'ekeingang_id fehlt/ungültig'}), 400
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.pos_aus_we_anhaengen(rec_id, we_id, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/aus-bestellpos')
def api_ek_pos_aus_bestellpos(rec_id: int) -> Any:
    """Body: {bestellpos_id, menge?}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        bp_id = int(body.get('bestellpos_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'bestellpos_id fehlt/ungültig'}), 400
    raw_menge = body.get('menge')
    try:
        menge = float(str(raw_menge).replace(',', '.')) if raw_menge is not None else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'menge ungültig'}), 400
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.pos_aus_bestellpos_anhaengen(
            rec_id, bp_id, menge=menge, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/aus-we-bulk')
def api_ek_pos_aus_we_bulk(rec_id: int) -> Any:
    """Body: {ekeingang_ids: [int, …]}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    raw = body.get('ekeingang_ids') or []
    ids: list[int] = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        return jsonify({'ok': False, 'fehler': 'Keine Wareneingaenge gewaehlt'}), 400
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.pos_aus_we_anhaengen_bulk(rec_id, ids, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/aus-bestellpos-bulk')
def api_ek_pos_aus_bestellpos_bulk(rec_id: int) -> Any:
    """Body: {items: [{pos_id, menge?}, …]}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    items = body.get('items') or []
    if not isinstance(items, list) or not items:
        return jsonify({'ok': False, 'fehler': 'Keine Positionen gewaehlt'}), 400
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.pos_aus_bestellpos_anhaengen_bulk(rec_id, items, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/artikel-anhaengen')
def api_ek_pos_artikel(rec_id: int) -> Any:
    """Body: {artikel_id, menge?, eingabe_preis?}"""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        artikel_id = int(body.get('artikel_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'artikel_id fehlt/ungültig'}), 400
    try:
        menge = float(str(body.get('menge', 1)).replace(',', '.'))
    except (TypeError, ValueError):
        menge = 1.0
    raw_preis = body.get('eingabe_preis')
    try:
        preis = float(str(raw_preis).replace(',', '.')) if raw_preis is not None else None
    except (TypeError, ValueError):
        preis = None
    ma_name = session.get('login_name') or session.get('mitarbeiter')
    try:
        result = ek.pos_artikel_anhaengen(
            rec_id, artikel_id,
            menge=menge, eingabe_preis=preis, ma_name=ma_name)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/<int:pos_id>/menge')
def api_ek_pos_menge(rec_id: int, pos_id: int) -> Any:
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        menge = float(str(body.get('menge', 0)).replace(',', '.'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'menge ungültig'}), 400
    try:
        result = ek.pos_menge_setzen(rec_id, pos_id, menge)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/<int:pos_id>/epreis')
def api_ek_pos_epreis(rec_id: int, pos_id: int) -> Any:
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        epreis = float(str(body.get('epreis', 0)).replace(',', '.'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'fehler': 'epreis ungültig'}), 400
    try:
        result = ek.pos_epreis_setzen(rec_id, pos_id, epreis)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.post('/einkauf/<int:rec_id>/api/pos/<int:pos_id>/entfernen')
def api_ek_pos_entfernen(rec_id: int, pos_id: int) -> Any:
    _login_check()
    try:
        result = ek.pos_entfernen(rec_id, pos_id)
    except (LookupError, PermissionError, ValueError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.get('/einkauf/<int:rec_id>/api/buchen-vorschau')
def api_ek_buchen_vorschau(rec_id: int) -> Any:
    """Read-only-Pruefung: Preisabweichungen + Warnungen vor dem Buchen."""
    _login_check()
    try:
        result = ek.buchen_vorschau(rec_id)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify(result)


@bp.post('/einkauf/<int:rec_id>/api/buchen')
def api_ek_buchen(rec_id: int) -> Any:
    """Verbucht den Einkauf endgueltig.

    Body: ``{"preis_uebernahmen": {"<pos_id>": "uebernehmen"|"behalten"}}``
    """
    _login_check()
    body = request.get_json(silent=True) or {}
    preis_uebernahmen = body.get('preis_uebernahmen') or {}
    ma_id = session.get('ma_id')
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = ek.einkauf_buchen(
            rec_id,
            ma_id=ma_id,
            ma_name=ma_name,
            preis_uebernahmen=preis_uebernahmen,
        )
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


def _arg_nur_lief() -> bool:
    """Liest den optionalen Filter ``nur_lief=1`` aus den Query-Parametern."""
    raw = (request.args.get('nur_lief') or '').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


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
                        lief_addr_id=_arg_lief_addr(),
                        nur_lief=_arg_nur_lief())})


@bp.get('/api/picker/artikel/suche')
def api_picker_artikel_suche() -> Any:
    """Volltextsuche Artikel."""
    _login_check()
    from common.picker_data import artikel_volltext_suche
    q = request.args.get('q', '').strip()
    return jsonify({'ok': True, 'zeilen': artikel_volltext_suche(
        q, lief_addr_id=_arg_lief_addr(),
        nur_lief=_arg_nur_lief())})


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


@bp.get('/wareneingang/<int:rec_id>/api/storno-pruefung')
def api_we_storno_pruefung(rec_id: int) -> Any:
    _login_check()
    try:
        result = we.storno_pruefung(rec_id)
    except (LookupError,) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify({'ok': True, **result})


@bp.post('/wareneingang/<int:rec_id>/api/storno')
def api_we_storno(rec_id: int) -> Any:
    _login_check()
    ma_name = session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT'
    try:
        result = we.storno(rec_id, ma_name=ma_name)
    except (LookupError, PermissionError) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


@bp.get('/<int:rec_id>/api/storno-pruefung')
def api_bestellung_storno_pruefung(rec_id: int) -> Any:
    _login_check()
    try:
        result = m.bestellung_storno_pruefung(rec_id)
    except (LookupError,) as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 404
    return jsonify({'ok': True, **result})


def create_blueprint():
    return bp
