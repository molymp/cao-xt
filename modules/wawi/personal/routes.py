"""
CAO-XT WaWi-Personal – Flask-Blueprint (P1 Stammdaten).

Registrierung:
    from modules.wawi.personal import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi/personal')
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify, make_response, send_file)

from .auth import backoffice_required
from . import models as m
from . import stundenzettel_pdf as _sz_pdf


bp = Blueprint('wawi_personal', __name__, template_folder=None)


def _form_to_date(val: str | None) -> date | None:
    val = (val or '').strip()
    if not val:
        return None
    return date.fromisoformat(val)


def _form_werte(form) -> dict:
    """Form-Daten → Werte-Dict fuer ma_insert/update."""
    w = {
        'PERSONALNUMMER': form.get('personalnummer', '').strip(),
        'VNAME':          form.get('vname', '').strip(),
        'NAME':           form.get('name', '').strip(),
        'KUERZEL':        (form.get('kuerzel', '').strip().upper() or None),
        'GEBDATUM':       _form_to_date(form.get('gebdatum')),
        'EMAIL':          form.get('email', '').strip() or None,
        'EMAIL_ALT':      form.get('email_alt', '').strip() or None,
        'STRASSE':        form.get('strasse', '').strip() or None,
        'PLZ':            form.get('plz', '').strip() or None,
        'ORT':            form.get('ort', '').strip() or None,
        'TELEFON':        form.get('telefon', '').strip() or None,
        'MOBIL':          form.get('mobil', '').strip() or None,
        'EINTRITT':       _form_to_date(form.get('eintritt')),
        'AUSTRITT':       _form_to_date(form.get('austritt')),
        'BEMERKUNG':      form.get('bemerkung', '').strip() or None,
    }
    cao_raw = form.get('cao_ma_id', '').strip()
    w['CAO_MA_ID'] = int(cao_raw) if cao_raw.isdigit() else None
    return w


def _euro_to_ct(val: str) -> int:
    """"13,90" → 1390. Leere/ungueltige Eingabe → ValueError."""
    v = (val or '').replace('.', '').replace(',', '.').strip()
    if not v:
        raise ValueError('Stundensatz leer')
    return int(round(float(v) * 100))


# ── Uebersicht ───────────────────────────────────────────────────────────────

def _zeige_alle_aus_args_oder_session(session_key: str) -> bool:
    """Liest Filter aus URL-Parameter 'alle' (0/1); speichert in Session.
    Fehlt der Parameter, gilt der zuletzt in der Session gemerkte Zustand.
    Default: False (nur aktive)."""
    raw = request.args.get('alle')
    if raw is not None:
        zeige_alle = raw == '1'
        session[session_key] = zeige_alle
        return zeige_alle
    return bool(session.get(session_key, False))


@bp.get('/')
@backoffice_required
def uebersicht():
    zeige_alle = _zeige_alle_aus_args_oder_session('personal_ma_zeige_alle')
    liste = m.ma_liste(nur_aktive=not zeige_alle)
    return render_template('personal/uebersicht.html',
                           mitarbeiter=liste,
                           zeige_alle=zeige_alle)


# ── Neu ──────────────────────────────────────────────────────────────────────

@bp.route('/neu', methods=['GET', 'POST'])
@backoffice_required
def neu():
    if request.method == 'POST':
        try:
            werte = _form_werte(request.form)
            pers_id = m.ma_insert(werte, session['ma_id'])
            # optional initialer Stundensatz
            satz_raw = request.form.get('stundensatz', '').strip()
            if satz_raw:
                m.stundensatz_setzen(
                    pers_id,
                    _form_to_date(request.form.get('stundensatz_ab')) or date.today(),
                    _euro_to_ct(satz_raw),
                    'Anlage',
                    session['ma_id'],
                )
            flash(f'{werte["VNAME"]} {werte["NAME"]} angelegt.', 'ok')
            return redirect(url_for('wawi_personal.detail', pers_id=pers_id))
        except (ValueError, LookupError) as e:
            flash(str(e), 'error')
        except Exception as e:
            # z.B. UNIQUE-Verletzung
            flash(f'Fehler beim Speichern: {e}', 'error')

    return render_template('personal/ma_neu.html',
                           werte=request.form if request.method == 'POST' else {})


# ── Detail ───────────────────────────────────────────────────────────────────

@bp.route('/<int:pers_id>', methods=['GET', 'POST'])
@backoffice_required
def detail(pers_id: int):
    ma = m.ma_by_id(pers_id)
    if not ma:
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))

    if request.method == 'POST':
        try:
            werte = _form_werte(request.form)
            anz = m.ma_update(pers_id, werte, session['ma_id'])
            if anz:
                flash(f'{anz} Feld(er) aktualisiert.', 'ok')
            else:
                flash('Keine Aenderungen.', 'info')
            return redirect(url_for('wawi_personal.detail', pers_id=pers_id))
        except (ValueError, LookupError) as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'error')
        ma = {**ma, **_form_werte(request.form)}

    aktuell_ct = m.aktueller_stundensatz_ct(pers_id)
    try:
        urlaub_jahr = int(request.args.get('urlaub_jahr', date.today().year))
    except (TypeError, ValueError):
        urlaub_jahr = date.today().year
    # Tagesaktueller Abschluss: genehmigte Antraege mit BIS < heute → 'genommen'
    m.urlaub_antraege_abschliessen(pers_id)
    return render_template(
        'personal/ma_detail.html',
        ma=ma,
        aktueller_stundensatz=m.ct_to_eurostr(aktuell_ct),
        aktueller_stundensatz_ct=aktuell_ct,
        stundensaetze=m.stundensaetze(pers_id),
        az_modelle=m.az_modelle(pers_id),
        aktuelles_az=m.aktuelles_az_modell(pers_id),
        lohnarten=m.lohnarten(),
        lohnkonstanten=m.lohnkonstanten_aktuell(),
        ma_log=m.ma_log(pers_id),
        urlaub_jahr=urlaub_jahr,
        urlaub_uebertrag_stichtag=m.urlaub_uebertrag_verfall_stichtag(urlaub_jahr),
        urlaub_saldo=m.urlaub_saldo(pers_id, urlaub_jahr),
        urlaub_korrekturen=m.urlaub_korrekturen(pers_id, urlaub_jahr),
        urlaub_antraege=m.urlaub_antraege(pers_id, urlaub_jahr),
        abwesenheiten=m.abwesenheiten_ma(pers_id, urlaub_jahr),
        abwesenheit_typen=m.ABWESENHEIT_TYPEN,
        abwesenheit_typ_labels=m.ABWESENHEIT_TYP_LABELS,
        abwesenheit_status_labels=m.ABWESENHEIT_STATUS_LABELS,
        abwesenheit_bezahlt_default={
            t: m.abwesenheit_bezahlt_default(t) for t in m.ABWESENHEIT_TYPEN
        },
        cao_ma_kandidaten=m.cao_ma_kandidaten(pers_id),
        pin_gesetzt=m.pin_ist_gesetzt(pers_id),
        today=date.today(),
    )


# ── Stundensatz anlegen ──────────────────────────────────────────────────────

@bp.post('/<int:pers_id>/stundensatz')
@backoffice_required
def stundensatz_anlegen(pers_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        satz_raw = request.form.get('stundensatz', '').strip()
        ab_raw   = request.form.get('stundensatz_ab', '').strip()
        if not satz_raw or not ab_raw:
            raise ValueError('Betrag und Gueltigkeitsdatum sind Pflicht.')
        m.stundensatz_setzen(
            pers_id,
            _form_to_date(ab_raw),
            _euro_to_ct(satz_raw),
            request.form.get('stundensatz_kommentar', '').strip() or None,
            session['ma_id'],
        )
        flash('Stundensatz hinzugefuegt.', 'ok')
    except (ValueError, LookupError) as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


# ── Arbeitszeitmodell anlegen ────────────────────────────────────────────────

def _dezimal(val: str | None) -> Decimal | None:
    val = (val or '').strip().replace(',', '.')
    if not val:
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        raise ValueError(f'Ungueltige Dezimalzahl: {val!r}')


@bp.post('/<int:pers_id>/az-modell')
@backoffice_required
def az_modell_anlegen(pers_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        werte = {
            'GUELTIG_AB':       _form_to_date(request.form.get('gueltig_ab')),
            'LOHNART_ID':       int(request.form['lohnart_id']),
            'TYP':              request.form.get('typ', 'WOCHE'),
            'STUNDEN_SOLL':     _dezimal(request.form.get('stunden_soll')),
            'URLAUB_JAHR_TAGE': _dezimal(request.form.get('urlaub_jahr_tage')),
            'BEMERKUNG':        request.form.get('bemerkung', '').strip() or None,
        }
        for k in m.WOCHENTAGE:
            werte[k] = _dezimal(request.form.get(k.lower()))
        m.az_modell_speichern(pers_id, werte, session['ma_id'])
        flash('Arbeitszeitmodell gespeichert.', 'ok')
    except (ValueError, KeyError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


# ── Einzelfeld-Autosave (AJAX) ───────────────────────────────────────────────

@bp.post('/<int:pers_id>/feld')
@backoffice_required
def feld_autosave(pers_id: int):
    """JSON-Endpoint fuer Autosave eines einzelnen MA-Stammdatenfelds.
    POST: feld=<FELDNAME>&wert=<wert>  → {ok: bool, anz: int, ...}"""
    if not m.ma_by_id(pers_id):
        return jsonify({'error': 'Mitarbeiter nicht gefunden'}), 404
    feld = (request.form.get('feld') or '').strip()
    if feld not in m.MA_FELDER:
        return jsonify({'error': f'Unbekanntes Feld: {feld!r}'}), 400
    wert_raw = request.form.get('wert', '')
    # Datum-Felder
    if feld in ('GEBDATUM', 'EINTRITT', 'AUSTRITT'):
        try:
            wert = _form_to_date(wert_raw)
        except ValueError:
            return jsonify({'error': 'Ungueltiges Datum'}), 400
    elif feld == 'CAO_MA_ID':
        wert = int(wert_raw) if wert_raw.strip().isdigit() else None
    else:
        wert = wert_raw if wert_raw != '' else None
    try:
        anz = m.ma_update(pers_id, {feld: wert}, session['ma_id'])
        return jsonify({'ok': True, 'anz': anz})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ── PIN setzen / zuruecksetzen ───────────────────────────────────────────────

@bp.post('/<int:pers_id>/pin')
@backoffice_required
def pin_setzen(pers_id: int):
    """Setzt die 4-stellige Stempeluhr-PIN eines MA."""
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    neue_pin = (request.form.get('pin') or '').strip()
    try:
        m.pin_setzen(pers_id, neue_pin, session['ma_id'])
        flash('PIN gespeichert.', 'ok')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


@bp.post('/<int:pers_id>/pin/loeschen')
@backoffice_required
def pin_loeschen(pers_id: int):
    """Loescht die PIN (Admin-Reset)."""
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        m.pin_setzen(pers_id, None, session['ma_id'])
        flash('PIN zurueckgesetzt.', 'ok')
    except Exception as e:
        flash(f'Fehler: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


# ── AZ-Modell bearbeiten (retroaktive Aenderung) ─────────────────────────────

@bp.post('/<int:pers_id>/az-modell/<int:rec_id>')
@backoffice_required
def az_modell_bearbeiten(pers_id: int, rec_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        werte = {}
        # Nur Felder uebernehmen, die im Form-POST vorkommen
        # GUELTIG_AB nur wenn nicht leer (Edit-Modus: leer = "nicht aendern")
        if request.form.get('gueltig_ab', '').strip():
            werte['GUELTIG_AB'] = _form_to_date(request.form['gueltig_ab'])
        if 'lohnart_id' in request.form:
            werte['LOHNART_ID'] = int(request.form['lohnart_id'])
        if 'typ' in request.form:
            werte['TYP'] = request.form['typ']
        if 'stunden_soll' in request.form:
            werte['STUNDEN_SOLL'] = _dezimal(request.form['stunden_soll'])
        if 'urlaub_jahr_tage' in request.form:
            werte['URLAUB_JAHR_TAGE'] = _dezimal(request.form['urlaub_jahr_tage'])
        for k in m.WOCHENTAGE:
            if k.lower() in request.form:
                werte[k] = _dezimal(request.form[k.lower()])
        if 'bemerkung' in request.form:
            werte['BEMERKUNG'] = request.form['bemerkung'].strip() or None

        n = m.az_modell_bearbeiten(rec_id, werte, session['ma_id'])
        flash(f'{n} Feld(er) aktualisiert.' if n else 'Keine Aenderung.',
              'ok' if n else 'info')
    except (ValueError, KeyError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


# ── Live-Minijob-Check (AJAX, JSON) ──────────────────────────────────────────

@bp.get('/api/minijob-check')
@backoffice_required
def api_minijob_check():
    """GET ?stunden=20&typ=WOCHE&stundensatz=13.90 → JSON mit Brutto/Grenze."""
    try:
        stunden = float(request.args.get('stunden', '0').replace(',', '.'))
        typ = request.args.get('typ', 'WOCHE')
        stundensatz_eur = request.args.get('stundensatz', '').replace(',', '.').strip()
        stundensatz_ct = int(round(float(stundensatz_eur) * 100)) if stundensatz_eur else 0
    except ValueError:
        return jsonify({'error': 'ungueltige Zahl'}), 400

    lk = m.lohnkonstanten_aktuell()
    if not lk or not lk.get('MINIJOB_GRENZE_CT'):
        return jsonify({'error': 'Keine Lohnkonstanten gepflegt'}), 404
    if stunden <= 0 or stundensatz_ct <= 0:
        return jsonify({'brutto_monat_ct': 0, 'grenze_ct': lk['MINIJOB_GRENZE_CT'],
                        'ueberschreitet': False, 'differenz_ct': -lk['MINIJOB_GRENZE_CT']})
    return jsonify(m.minijob_check(stunden, typ, stundensatz_ct, lk['MINIJOB_GRENZE_CT']))


# ── P1c: Urlaubskorrektur / Urlaubsantrag ────────────────────────────────────

@bp.post('/<int:pers_id>/urlaub/korrektur')
@backoffice_required
def urlaub_korrektur_anlegen(pers_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    jahr_raw = request.form.get('jahr', '').strip()
    try:
        jahr = int(jahr_raw) if jahr_raw else date.today().year
        tage = _dezimal(request.form.get('tage'))
        if tage is None:
            raise ValueError('TAGE ist Pflicht')
        # Uebertrag-Flag gesetzt → Verfallsdatum = Stichtag im Ziel-Jahr
        verfaellt_am: date | None = None
        if request.form.get('uebertrag_vorjahr'):
            if float(tage) <= 0:
                raise ValueError(
                    'Uebertrag muss positiv sein (sonst Flag weglassen).'
                )
            verfaellt_am = m.urlaub_uebertrag_verfall_stichtag(jahr)
        m.urlaub_korrektur_anlegen(
            pers_id, jahr, float(tage),
            request.form.get('grund', '').strip(),
            request.form.get('kommentar', '').strip() or None,
            session['ma_id'],
            verfaellt_am=verfaellt_am,
        )
        flash('Korrekturbuchung hinzugefuegt.', 'ok')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail',
                            pers_id=pers_id, urlaub_jahr=jahr_raw or None))


@bp.post('/<int:pers_id>/urlaub/antrag')
@backoffice_required
def urlaub_antrag_anlegen(pers_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        von = _form_to_date(request.form.get('von'))
        bis = _form_to_date(request.form.get('bis'))
        if not von or not bis:
            raise ValueError('VON und BIS sind Pflicht.')
        status = request.form.get('status', 'geplant')
        m.urlaub_antrag_anlegen(
            pers_id, von, bis,
            request.form.get('kommentar', '').strip() or None,
            session['ma_id'], status,
        )
        flash('Urlaubsantrag angelegt.', 'ok')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail',
                            pers_id=pers_id,
                            urlaub_jahr=request.form.get('jahr') or None))


@bp.post('/<int:pers_id>/urlaub/antrag/<int:rec_id>/status')
@backoffice_required
def urlaub_antrag_status(pers_id: int, rec_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        neuer = request.form.get('status', '').strip()
        n = m.urlaub_antrag_status_setzen(rec_id, neuer, session['ma_id'])
        flash('Status aktualisiert.' if n else 'Keine Aenderung.',
              'ok' if n else 'info')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail',
                            pers_id=pers_id,
                            urlaub_jahr=request.form.get('jahr') or None))


# ── Live-Arbeitstage-Berechnung (AJAX, JSON) ─────────────────────────────────

@bp.get('/<int:pers_id>/urlaub/arbeitstage')
@backoffice_required
def api_urlaub_arbeitstage(pers_id: int):
    try:
        von = _form_to_date(request.args.get('von'))
        bis = _form_to_date(request.args.get('bis'))
    except ValueError:
        return jsonify({'error': 'Ungueltiges Datum'}), 400
    if not von or not bis:
        return jsonify({'error': 'VON und BIS sind Pflicht'}), 400
    return jsonify({'arbeitstage': m.urlaub_arbeitstage(pers_id, von, bis)})


# ── P4: Abwesenheiten (Krankheit etc.) ──────────────────────────────────────

def _abwesenheit_form_werte(form) -> dict:
    """Extrahiert Abwesenheit-Felder aus einem POST-Form."""
    def _bool(key: str) -> bool:
        v = (form.get(key) or '').strip().lower()
        return v in ('1', 'true', 'ja', 'on', 'yes')

    def _stunden(val: str | None):
        v = (val or '').strip().replace(',', '.')
        return float(v) if v else None

    return {
        'typ':         (form.get('typ') or '').strip(),
        'von':         _form_to_date(form.get('von')),
        'bis':         _form_to_date(form.get('bis')),
        'ganztags':    _bool('ganztags'),
        'stunden':     _stunden(form.get('stunden')),
        'au_vorgelegt': _bool('au_vorgelegt'),
        'bezahlt':     _bool('bezahlt'),
        'bemerkung':   (form.get('bemerkung') or '').strip() or None,
    }


@bp.post('/<int:pers_id>/abwesenheit')
@backoffice_required
def abwesenheit_anlegen(pers_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        w = _abwesenheit_form_werte(request.form)
        if not w['von'] or not w['bis']:
            raise ValueError('VON und BIS sind Pflicht.')
        m.abwesenheit_anlegen(
            pers_id, w['typ'], w['von'], w['bis'],
            ganztags=w['ganztags'], stunden=w['stunden'],
            au_vorgelegt=w['au_vorgelegt'], bezahlt=w['bezahlt'],
            bemerkung=w['bemerkung'],
            benutzer_ma_id=session['ma_id'],
        )
        flash('Abwesenheit angelegt.', 'ok')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


@bp.post('/<int:pers_id>/abwesenheit/<int:rec_id>/bearbeiten')
@backoffice_required
def abwesenheit_bearbeiten(pers_id: int, rec_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        w = _abwesenheit_form_werte(request.form)
        werte = {
            'TYP':          w['typ'],
            'VON':          w['von'],
            'BIS':          w['bis'],
            'GANZTAGS':     w['ganztags'],
            'STUNDEN':      w['stunden'],
            'AU_VORGELEGT': w['au_vorgelegt'],
            'BEZAHLT':      w['bezahlt'],
            'BEMERKUNG':    w['bemerkung'],
        }
        n = m.abwesenheit_bearbeiten(rec_id, werte, session['ma_id'])
        flash('Abwesenheit aktualisiert.' if n else 'Keine Aenderung.',
              'ok' if n else 'info')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


@bp.post('/<int:pers_id>/abwesenheit/<int:rec_id>/status')
@backoffice_required
def abwesenheit_status(pers_id: int, rec_id: int):
    """Status eines Abwesenheitsantrags auf 'genehmigt' oder 'abgelehnt' setzen."""
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    neuer_status = (request.form.get('status') or '').strip()
    try:
        n = m.abwesenheit_status_setzen(rec_id, neuer_status, session['ma_id'])
        if n:
            label = m.ABWESENHEIT_STATUS_LABELS.get(neuer_status, neuer_status)
            flash(f'Abwesenheit {label.lower()}.', 'ok')
        else:
            flash('Status unveraendert.', 'info')
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Aendern: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


@bp.post('/<int:pers_id>/abwesenheit/<int:rec_id>/stornieren')
@backoffice_required
def abwesenheit_stornieren(pers_id: int, rec_id: int):
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    try:
        n = m.abwesenheit_stornieren(rec_id, session['ma_id'])
        flash('Abwesenheit storniert.' if n else 'Schon storniert.',
              'ok' if n else 'info')
    except LookupError as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Stornieren: {e}', 'error')
    return redirect(url_for('wawi_personal.detail', pers_id=pers_id))


@bp.get('/abwesenheiten')
@backoffice_required
def abwesenheiten_uebersicht():
    """MA-uebergreifende Liste aktiver Abwesenheiten im gewaehlten Zeitraum."""
    von = _form_to_date(request.args.get('von')) or date.today()
    bis = _form_to_date(request.args.get('bis')) or (von + timedelta(days=30))
    typ = (request.args.get('typ') or '').strip() or None
    eintraege = m.abwesenheiten_im_zeitraum(von, bis, typ=typ)
    return render_template(
        'personal/abwesenheiten.html',
        von=von, bis=bis, typ_filter=typ,
        eintraege=eintraege,
        typen=m.ABWESENHEIT_TYPEN,
        typ_labels=m.ABWESENHEIT_TYP_LABELS,
    )


@bp.get('/abwesenheiten/kalender')
@backoffice_required
def abwesenheiten_kalender():
    """Zeitstrahl-Ansicht aller Abwesenheiten als MA × Tag-Matrix.

    Query-Parameter:
      ansicht: 'monat' (Default) oder 'jahr'
      jahr:    4-stellig (Default: heute)
      monat:   1-12 (nur bei ansicht='monat'; Default: heute)
    """
    heute = date.today()
    ansicht = (request.args.get('ansicht') or 'monat').lower()
    if ansicht not in ('monat', 'jahr'):
        ansicht = 'monat'
    try:
        jahr = int(request.args.get('jahr') or heute.year)
    except (TypeError, ValueError):
        jahr = heute.year
    try:
        monat = int(request.args.get('monat') or heute.month)
        if monat < 1 or monat > 12:
            monat = heute.month
    except (TypeError, ValueError):
        monat = heute.month

    if ansicht == 'monat':
        von = date(jahr, monat, 1)
        if monat == 12:
            bis = date(jahr, 12, 31)
        else:
            bis = date(jahr, monat + 1, 1) - timedelta(days=1)
    else:
        von = date(jahr, 1, 1)
        bis = date(jahr, 12, 31)

    # Tage-Liste fuer die Spalten (jeder Tag als date-Objekt).
    tage: list[date] = []
    t = von
    while t <= bis:
        tage.append(t)
        t += timedelta(days=1)

    mitarbeiter = m.ma_liste(nur_aktive=True)
    abw = m.abwesenheiten_im_zeitraum(von, bis)
    feiertage = m.feiertage_im_zeitraum(von, bis)

    # Matrix: {pers_id: {tag: abwesenheits_dict}} — pro Tag gewinnt der erste
    # Eintrag (in Praxis sind sich ueberschneidende Abwesenheiten selten).
    matrix: dict[int, dict[date, dict]] = {int(ma['PERS_ID']): {} for ma in mitarbeiter}
    for a in abw:
        pid = int(a['PERS_ID'])
        if pid not in matrix:
            continue  # MA nicht in "aktiv"-Liste (z.B. ausgeschieden)
        d = max(a['VON'], von)
        end = min(a['BIS'], bis)
        while d <= end:
            matrix[pid].setdefault(d, a)
            d += timedelta(days=1)

    # Navigations-Links (vor/zurueck) vorberechnen, damit das Template simpel bleibt.
    if ansicht == 'monat':
        prev_monat = 12 if monat == 1 else monat - 1
        prev_jahr = jahr - 1 if monat == 1 else jahr
        next_monat = 1 if monat == 12 else monat + 1
        next_jahr = jahr + 1 if monat == 12 else jahr
    else:
        prev_monat = next_monat = None
        prev_jahr = jahr - 1
        next_jahr = jahr + 1

    # Jahresansicht: Monatskopf-Zeile (colspan pro Monat), damit die
    # Tag-Spalten keine eigenen Labels tragen muessen und sich frei auf
    # die Viewport-Breite verteilen koennen.
    monats_koepfe: list[dict] = []
    if ansicht == 'jahr':
        import calendar
        for mm in range(1, 13):
            anzahl = calendar.monthrange(jahr, mm)[1]
            monats_koepfe.append({
                'name':  date(jahr, mm, 1).strftime('%b'),
                'tage':  anzahl,
                'jahr':  jahr,
                'monat': mm,
            })

    return render_template(
        'personal/abwesenheiten_kalender.html',
        ansicht=ansicht, jahr=jahr, monat=monat,
        von=von, bis=bis, tage=tage,
        mitarbeiter=mitarbeiter, matrix=matrix, feiertage=feiertage,
        typ_labels=m.ABWESENHEIT_TYP_LABELS,
        status_labels=m.ABWESENHEIT_STATUS_LABELS,
        prev_jahr=prev_jahr, prev_monat=prev_monat,
        next_jahr=next_jahr, next_monat=next_monat,
        monats_koepfe=monats_koepfe,
        heute=heute,
    )


@bp.get('/arbeitszeitkonten')
@backoffice_required
def arbeitszeitkonten():
    """Arbeitszeitkonten fuer das ganze Jahr, pro MA eine Tabelle.

    Query-Parameter (alle optional, werden in Cookies gemerkt):
      modus:  'woche' oder 'monat'  (Default: letzter Cookie oder 'monat')
      jahr:   4-stellig             (Default: heute)
      ma_ids: '1,2,3' (komma-sep.)  (Default: letzter Cookie oder alle aktiven)
    """
    heute = date.today()

    # Ansicht (Woche/Monat) persistieren.
    modus_arg = (request.args.get('modus') or '').lower()
    if modus_arg in ('woche', 'monat'):
        modus = modus_arg
    else:
        modus = (request.cookies.get('azk_modus') or 'monat').lower()
        if modus not in ('woche', 'monat'):
            modus = 'monat'

    try:
        jahr = int(request.args.get('jahr') or heute.year)
    except (TypeError, ValueError):
        jahr = heute.year

    # Mitarbeiter-Auswahl persistieren.
    mitarbeiter = m.ma_liste(nur_aktive=True)
    alle_ids = [int(ma['PERS_ID']) for ma in mitarbeiter]

    def _parse_ids(raw: str | None) -> list[int] | None:
        if raw is None:
            return None
        raw = raw.strip()
        if raw == '':
            return []  # bewusst alle abgewaehlt
        try:
            return [int(x) for x in raw.split(',') if x.strip()]
        except ValueError:
            return None

    ids_from_arg = _parse_ids(request.args.get('ma_ids'))
    if ids_from_arg is not None:
        sel_ids = [i for i in ids_from_arg if i in alle_ids]
    else:
        cookie_ids = _parse_ids(request.cookies.get('azk_ma_ids'))
        if cookie_ids is None:
            sel_ids = list(alle_ids)
        else:
            sel_ids = [i for i in cookie_ids if i in alle_ids]

    # Daten pro MA aggregieren (nur fuer ausgewaehlte MAs).
    mas_selected = [ma for ma in mitarbeiter if int(ma['PERS_ID']) in sel_ids]
    zeilen = []
    for ma in mas_selected:
        pid = int(ma['PERS_ID'])
        daten = m.arbeitszeitkonto_jahr(pid, jahr, modus)
        saldo = m.urlaub_saldo(pid, jahr)
        in_ze = m.ma_in_zeiterfassung(pid, date(jahr, 1, 1))
        zeilen.append({'ma': ma, 'd': daten, 'saldo': saldo,
                       'in_zeiterfassung': in_ze})

    # Monatsauswahl fuer Stundenzettel-Batch: Default = letzter abgeschlossener
    # Monat (= Monat VOR heute; im Januar → Dezember des Vorjahres).
    heute_mo = date.today()
    if heute_mo.month == 1:
        sz_monat_default, sz_jahr_default = 12, heute_mo.year - 1
    else:
        sz_monat_default, sz_jahr_default = heute_mo.month - 1, heute_mo.year

    # Cookies setzen (1 Jahr gueltig).
    resp = make_response(render_template(
        'personal/arbeitszeitkonten.html',
        modus=modus, jahr=jahr,
        mitarbeiter=mitarbeiter, sel_ids=sel_ids, alle_ids=alle_ids,
        zeilen=zeilen,
        prev_jahr=jahr - 1, next_jahr=jahr + 1,
        m_hstr=m.minuten_zu_hstr,
        sz_monat_default=sz_monat_default,
        sz_jahr_default=sz_jahr_default,
    ))
    resp.set_cookie('azk_modus', modus, max_age=365 * 24 * 3600,
                    samesite='Lax')
    resp.set_cookie('azk_ma_ids', ','.join(str(i) for i in sel_ids),
                    max_age=365 * 24 * 3600, samesite='Lax')
    return resp


@bp.post('/<int:pers_id>/stundenkorrektur')
@backoffice_required
def stundenkorrektur_anlegen(pers_id: int):
    """Manuelle Stunden-Korrektur (Tages-Delta, vorzeichenbehaftet).

    Form-Felder:
      datum   – ISO-Datum (YYYY-MM-DD)
      stunden – Dezimal-Stunden mit Vorzeichen (z.B. "+1,75", "-0,5")
      grund   – Pflicht, Kurz-Begruendung
      kommentar – optional
    """
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten'))
    try:
        datum = _form_to_date(request.form.get('datum'))
        if not datum:
            raise ValueError('Datum ist Pflicht.')
        stunden = _dezimal(request.form.get('stunden'))
        if stunden is None:
            raise ValueError('Stunden sind Pflicht.')
        minuten = int(round(float(stunden) * 60))
        if minuten == 0:
            raise ValueError('Stunden duerfen nicht 0 sein.')
        grund = (request.form.get('grund') or '').strip()
        if not grund:
            raise ValueError('Grund ist Pflicht.')
        kommentar = (request.form.get('kommentar') or '').strip() or None
        # Kommentar haengen wir an den Grund an (das Schema hat kein separates
        # Kommentar-Feld – pragmatisch, hoechstens 255 Zeichen).
        if kommentar:
            grund = f'{grund} | {kommentar}'[:255]
        m.stundenkorrektur_insert(
            pers_id, datum, minuten, grund,
            quelle='manuell',
            benutzer_ma_id=session['ma_id'],
        )
        flash(
            f'Stunden-Korrektur fuer {datum.strftime("%d.%m.%Y")} '
            f'gebucht ({float(stunden):+.2f}h).',
            'ok',
        )
    except (ValueError, LookupError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return redirect(url_for('wawi_personal.arbeitszeitkonten',
                            jahr=datum.year if 'datum' in locals() and datum
                                 else None))


# ── Stundenzettel (monatliches PDF pro MA) ──────────────────────────────────

def _parse_jahr_monat() -> tuple[int, int]:
    """Liest 'jahr' und 'monat' aus request.args (GET) oder .form (POST).

    Default: aktueller Monat. Fehlerhafte Eingaben → ValueError.
    """
    heute = date.today()
    quelle = request.values  # vereint args und form
    try:
        jahr = int(quelle.get('jahr') or heute.year)
        monat = int(quelle.get('monat') or heute.month)
    except (TypeError, ValueError):
        raise ValueError('Jahr/Monat ungueltig')
    if not (1 <= monat <= 12):
        raise ValueError('Monat ausserhalb 1..12')
    return jahr, monat


def _firma_name() -> str:
    """Firmenname fuer PDF-Header. Vorrang: Flask-App-Config ``FIRMA_NAME``
    (wird in wawi-app/app/config.py gesetzt), fallback XT_EINSTELLUNGEN,
    sonst leer."""
    try:
        from flask import current_app
        v = current_app.config.get('FIRMA_NAME')
        if v:
            return str(v)
    except Exception:
        pass
    try:
        with m.get_db_ro() as cur:
            cur.execute(
                "SELECT wert FROM XT_EINSTELLUNGEN WHERE schluessel = 'firma_name'"
            )
            row = cur.fetchone()
            return (row['wert'] if row else '') or ''
    except Exception:
        return ''


@bp.get('/<int:pers_id>/stundenzettel')
@backoffice_required
def stundenzettel_pdf(pers_id: int):
    """Erzeugt den Stundenzettel-PDF fuer einen MA fuer einen Monat.

    Query-Parameter: ``jahr`` (YYYY), ``monat`` (1..12). Default: aktueller Monat.
    MAs mit Lohnart ``IN_ZEITERFASSUNG=0`` (z.B. Leitende/GF) erhalten keinen
    Stundenzettel – die Route antwortet in dem Fall mit 400.
    """
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten'))
    try:
        jahr, monat = _parse_jahr_monat()
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten'))
    if not m.ma_in_zeiterfassung(pers_id, date(jahr, monat, 1)):
        flash('Mitarbeiter nimmt nicht an der Zeiterfassung teil – '
              'kein Stundenzettel moeglich.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten',
                                jahr=jahr))
    daten = m.stundenzettel_monat_daten(pers_id, jahr, monat)
    pdf = _sz_pdf.stundenzettel_als_pdf(daten, firma_name=_firma_name())
    # Dateiname: Stundenzettel_YYYY-MM_Name_Vorname.pdf
    import re as _re

    def _safe(s: str) -> str:
        return _re.sub(r'[^A-Za-z0-9._-]', '_',
                       (s or '').strip()) or 'MA'
    ma = daten['ma']
    dateiname = (
        f"Stundenzettel_{jahr:04d}-{monat:02d}_"
        f"{_safe(ma.get('NAME') or '')}_{_safe(ma.get('VNAME') or '')}.pdf"
    )
    import io as _io
    return send_file(
        _io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=dateiname,
    )


@bp.post('/stundenzettel/batch')
@backoffice_required
def stundenzettel_batch():
    """Erzeugt ein ZIP mit Stundenzetteln fuer mehrere MAs fuer einen Monat.

    Form-Felder:
      jahr    – 4-stellig
      monat   – 1..12
      ma_ids  – komma-separierte PERS_IDs
    """
    try:
        jahr, monat = _parse_jahr_monat()
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten'))
    raw_ids = (request.form.get('ma_ids') or '').strip()
    if not raw_ids:
        flash('Keine Mitarbeiter ausgewaehlt.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten',
                                jahr=jahr))
    try:
        pers_ids = [int(x) for x in raw_ids.split(',') if x.strip()]
    except ValueError:
        flash('Ungueltige MA-Auswahl.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten',
                                jahr=jahr))

    stichtag = date(jahr, monat, 1)
    daten_liste: list[dict] = []
    uebersprungen: list[str] = []
    for pid in pers_ids:
        ma = m.ma_by_id(pid)
        if not ma:
            continue
        if not m.ma_in_zeiterfassung(pid, stichtag):
            uebersprungen.append(
                f"{ma.get('NAME','')}, {ma.get('VNAME','')}")
            continue
        daten_liste.append(m.stundenzettel_monat_daten(pid, jahr, monat))

    if not daten_liste:
        flash('Keiner der ausgewaehlten Mitarbeiter nimmt an der '
              'Zeiterfassung teil.', 'error')
        return redirect(url_for('wawi_personal.arbeitszeitkonten',
                                jahr=jahr))

    zip_bytes = _sz_pdf.batch_als_zip(
        daten_liste, firma_name=_firma_name(),
    )

    if uebersprungen:
        flash('Uebersprungen (keine Zeiterfassung): '
              + '; '.join(uebersprungen), 'info')

    monats_name = daten_liste[0]['monats_name']
    dateiname = f"Stundenzettel_{monats_name}_{jahr}.zip"
    import io as _io
    return send_file(
        _io.BytesIO(zip_bytes),
        mimetype='application/zip',
        as_attachment=True,
        download_name=dateiname,
    )


# ── P3: Stempeluhr ───────────────────────────────────────────────────────────

def _parse_stempel_dt(val: str | None) -> datetime | None:
    val = (val or '').strip()
    if not val:
        return None
    # HTML datetime-local liefert "YYYY-MM-DDTHH:MM" (ohne Sekunden).
    return datetime.fromisoformat(val)


@bp.get('/stempel/')
@backoffice_required
def stempel_uebersicht():
    """Tagesuebersicht aller Stempel. Default: heute."""
    tag = _form_to_date(request.args.get('tag')) or date.today()
    eintraege = m.stempel_tagesliste(tag)
    return render_template(
        'personal/stempel_tag.html',
        tag=tag, eintraege=eintraege,
    )


@bp.get('/<int:pers_id>/stempel')
@backoffice_required
def stempel_ma(pers_id: int):
    """Stempel eines MA im gewaehlten Zeitraum, plus Korrektur-Log."""
    ma = m.ma_by_id(pers_id)
    if not ma:
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    heute = date.today()
    von = _form_to_date(request.args.get('von')) or heute.replace(day=1)
    bis = _form_to_date(request.args.get('bis')) or heute
    eintraege = m.stempel_ma_zeitraum(pers_id, von, bis)
    # Gruppieren nach Tag + Tages-Arbeitsdauer berechnen.
    tage: dict[date, dict] = {}
    for e in eintraege:
        d = e['ZEITPUNKT'].date()
        tage.setdefault(d, {'datum': d, 'stempel': []})
        tage[d]['stempel'].append(e)
    for d, t in tage.items():
        t['arbeitsdauer_min'] = m.stempel_arbeitsdauer_min(pers_id, d)
    korrektur_log = m.stempel_korrektur_log(pers_id, limit=30)
    return render_template(
        'personal/stempel_ma.html',
        ma=ma, von=von, bis=bis,
        tage=sorted(tage.values(), key=lambda t: t['datum']),
        korrektur_log=korrektur_log,
    )


@bp.post('/<int:pers_id>/stempel/korrektur')
@backoffice_required
def stempel_korrektur_anlegen(pers_id: int):
    """Admin fuegt manuell einen Stempel hinzu (z.B. vergessenes Ausstempeln)."""
    if not m.ma_by_id(pers_id):
        flash('Mitarbeiter nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.uebersicht'))
    richtung = (request.form.get('richtung') or '').strip()
    zeitpunkt = _parse_stempel_dt(request.form.get('zeitpunkt'))
    grund = (request.form.get('grund') or '').strip()
    if not zeitpunkt:
        flash('Zeitpunkt fehlt.', 'error')
        return redirect(url_for('wawi_personal.stempel_ma', pers_id=pers_id))
    try:
        m.stempel_korrektur_insert(pers_id, richtung, zeitpunkt,
                                   grund, session['ma_id'])
        flash('Stempel nachtraeglich angelegt.', 'ok')
    except ValueError as exc:
        flash(f'Fehler: {exc}', 'error')
    return redirect(url_for('wawi_personal.stempel_ma', pers_id=pers_id))


@bp.post('/<int:pers_id>/stempel/<int:rec_id>/bearbeiten')
@backoffice_required
def stempel_korrektur_bearbeiten(pers_id: int, rec_id: int):
    """Admin aendert Richtung/Zeitpunkt eines bestehenden Stempels."""
    richtung = (request.form.get('richtung') or '').strip()
    zeitpunkt = _parse_stempel_dt(request.form.get('zeitpunkt'))
    grund = (request.form.get('grund') or '').strip()
    if not zeitpunkt:
        flash('Zeitpunkt fehlt.', 'error')
        return redirect(url_for('wawi_personal.stempel_ma', pers_id=pers_id))
    try:
        n = m.stempel_korrektur_update(rec_id, richtung, zeitpunkt,
                                       grund, session['ma_id'])
        flash('Stempel geaendert.' if n else 'Stempel nicht gefunden.',
              'ok' if n else 'error')
    except ValueError as exc:
        flash(f'Fehler: {exc}', 'error')
    return redirect(url_for('wawi_personal.stempel_ma', pers_id=pers_id))


@bp.post('/<int:pers_id>/stempel/<int:rec_id>/loeschen')
@backoffice_required
def stempel_korrektur_loeschen(pers_id: int, rec_id: int):
    """Admin loescht einen Fehl-Stempel (mit Grund)."""
    grund = (request.form.get('grund') or '').strip()
    try:
        n = m.stempel_korrektur_delete(rec_id, grund, session['ma_id'])
        flash('Stempel geloescht.' if n else 'Stempel nicht gefunden.',
              'ok' if n else 'error')
    except ValueError as exc:
        flash(f'Fehler: {exc}', 'error')
    return redirect(url_for('wawi_personal.stempel_ma', pers_id=pers_id))


# ── P2: Schicht-Stammdaten ──────────────────────────────────────────────────

def _schicht_form_werte(form) -> dict:
    def _zeit(s):
        s = (s or '').strip()
        return s if len(s) >= 5 else None
    def _int(s, default=None):
        s = (s or '').strip()
        return int(s) if s else default
    typ = form.get('typ', 'fix')
    return {
        'BEZEICHNUNG': form.get('bezeichnung', '').strip(),
        'KUERZEL':     form.get('kuerzel', '').strip().upper() or None,
        'TYP':         typ if typ in m.SCHICHT_TYPEN else 'fix',
        'STARTZEIT':   _zeit(form.get('startzeit')),
        'ENDZEIT':     _zeit(form.get('endzeit')),
        'FARBE':       form.get('farbe', '').strip() or '#4A7C3A',
        'AKTIV':       1 if form.get('aktiv') else 0,
        'SORT':        _int(form.get('sort'), 0) or 0,
    }


@bp.get('/schicht/')
@backoffice_required
def schicht_uebersicht():
    zeige_alle = _zeige_alle_aus_args_oder_session('personal_schicht_zeige_alle')
    return render_template(
        'personal/schicht_uebersicht.html',
        schichten=m.schichten(nur_aktive=not zeige_alle),
        zeige_alle=zeige_alle,
        brutto_min=m.schicht_brutto_min,
    )


@bp.route('/schicht/neu', methods=['GET', 'POST'])
@backoffice_required
def schicht_neu():
    if request.method == 'POST':
        try:
            werte = _schicht_form_werte(request.form)
            m.schicht_insert(werte, session['ma_id'])
            flash(f'Schicht {werte["BEZEICHNUNG"]} angelegt.', 'ok')
            return redirect(url_for('wawi_personal.schicht_uebersicht'))
        except (ValueError, LookupError) as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'error')
    return render_template(
        'personal/schicht_form.html',
        modus='neu',
        werte={
            'AKTIV': 1, 'TYP': 'fix', 'FARBE': '#4A7C3A',
            'BEZEICHNUNG': '', 'KUERZEL': '',
            'STARTZEIT': None, 'ENDZEIT': None, 'SORT': 0,
        },
    )


@bp.route('/schicht/<int:schicht_id>', methods=['GET', 'POST'])
@backoffice_required
def schicht_bearbeiten(schicht_id: int):
    schicht = m.schicht_by_id(schicht_id)
    if not schicht:
        flash('Schicht nicht gefunden.', 'error')
        return redirect(url_for('wawi_personal.schicht_uebersicht'))
    if request.method == 'POST':
        try:
            werte = _schicht_form_werte(request.form)
            anz = m.schicht_update(schicht_id, werte, session['ma_id'])
            flash(f'{anz} Feld(er) aktualisiert.' if anz else 'Keine Aenderung.',
                  'ok' if anz else 'info')
            return redirect(url_for('wawi_personal.schicht_uebersicht'))
        except (ValueError, LookupError) as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'error')
        schicht = {**schicht, **_schicht_form_werte(request.form)}
    return render_template(
        'personal/schicht_form.html',
        modus='edit',
        schicht=schicht,
        werte=schicht,
    )


# ── P2: Wochen-Schichtplan ──────────────────────────────────────────────────

def _parse_woche(s: str | None) -> date:
    """Akzeptiert 'YYYY-MM-DD' (Tag aus gewuenschter Woche) oder 'YYYY-Www'
    (ISO-Wochenformat). Leere/ungueltige Eingabe → aktueller Montag."""
    s = (s or '').strip()
    if not s:
        return m.montag_der_woche(date.today())
    try:
        if 'W' in s.upper():
            jahr, wo = s.upper().split('-W')
            return date.fromisocalendar(int(jahr), int(wo), 1)
        return m.montag_der_woche(date.fromisoformat(s))
    except (ValueError, TypeError):
        return m.montag_der_woche(date.today())


def _kw_optionen(referenz_jahr: int) -> list[dict]:
    """Liste aller ISO-KW-Optionen fuer das Schichtplan-KW-Select.

    Deckt referenz_jahr-1 .. referenz_jahr+1 ab (3 Jahre), damit Jahres-
    uebergaenge bequem springbar sind. Liefert dicts mit ``value`` (Montag
    ISO-Datum), ``label`` ("KW 23 / 2026") und ``jahr`` (fuer optgroup).
    """
    aus = []
    for j in (referenz_jahr - 1, referenz_jahr, referenz_jahr + 1):
        kw = 1
        while True:
            try:
                mo = date.fromisocalendar(j, kw, 1)
            except ValueError:
                break
            aus.append({
                'value': mo.isoformat(),
                'label': f'KW {kw:02d} / {j}',
                'jahr':  j,
            })
            kw += 1
    return aus


@bp.get('/schichtplan/')
@backoffice_required
def schichtplan():
    montag = _parse_woche(request.args.get('woche'))
    sonntag = montag + timedelta(days=6)
    tage = [montag + timedelta(days=i) for i in range(7)]

    zuordnungen = m.schicht_zuordnungen_woche(montag)
    urlaube = m.urlaube_im_zeitraum(montag, sonntag)
    abwesenheiten = m.abwesenheiten_im_zeitraum(montag, sonntag)
    mitarbeiter = m.ma_aktiv_am(sonntag)
    alle_schichten = m.schichten(nur_aktive=True)
    pause_reg = m.pause_regelung_aktuell(montag)

    # Index: (pers_id, datum) → Liste Zuordnungen
    plan = {}
    for z in zuordnungen:
        plan.setdefault((z['PERS_ID'], z['DATUM']), []).append(z)

    # Index: (pers_id, datum) → urlaub_status (erster matchender Eintrag)
    urlaub_map = {}
    for u in urlaube:
        for i in range(7):
            d = montag + timedelta(days=i)
            if u['VON'] <= d <= u['BIS']:
                urlaub_map.setdefault((u['PERS_ID'], d), u['STATUS'])

    # Index: (pers_id, datum) → TYP der Abwesenheit (erster matchender Eintrag).
    # Abwesenheiten (Krank etc.) beanspruchen den Tag analog zum Urlaub fuer
    # die UI-Kollisionspruefung.
    abwesenheit_map = {}
    for a in abwesenheiten:
        for i in range(7):
            d = montag + timedelta(days=i)
            if a['VON'] <= d <= a['BIS']:
                abwesenheit_map.setdefault((a['PERS_ID'], d), a['TYP'])

    # Feiertage der Woche: {datum: name}. Werden im Kopf der Matrix
    # angezeigt; eine Schichtzuweisung bleibt moeglich (analog Sonntag).
    feiertage = m.feiertage_im_zeitraum(montag, sonntag)

    # Wochen-KPI: Pause wird tagesweise aus der Tagesarbeitszeit ermittelt.
    # tag_summary[(pers_id, datum)] → {brutto_min, pause_min, netto_min}
    kpi = {}
    tag_summary = {}
    for ma in mitarbeiter:
        ist_netto = 0
        ist_brutto = 0
        pause_ges = 0
        for tag in tage:
            zs = plan.get((ma['PERS_ID'], tag), [])
            agg = m.tagesarbeitszeit_min(zs, pause_reg)
            tag_summary[(ma['PERS_ID'], tag)] = agg
            ist_brutto += agg['brutto_min']
            pause_ges  += agg['pause_min']
            ist_netto  += agg['netto_min']
        soll = m.az_soll_woche_min(ma['PERS_ID'], montag)
        kpi[ma['PERS_ID']] = {
            'ist_min':    ist_netto,
            'brutto_min': ist_brutto,
            'pause_min':  pause_ges,
            'soll_min':   soll,
        }

    jahr, kw = m._iso_jahr_kw(montag)
    status = m.woche_status(jahr, kw)
    log = m.woche_log(jahr, kw, limit=20)
    vorlagen = m.vorlage_liste()

    return render_template(
        'personal/schichtplan.html',
        montag=montag,
        sonntag=sonntag,
        tage=tage,
        wochennummer=kw,
        jahr=jahr,
        kw_optionen=_kw_optionen(jahr),
        vorwoche=(montag - timedelta(days=7)).isoformat(),
        folgewoche=(montag + timedelta(days=7)).isoformat(),
        aktuelle_woche=m.montag_der_woche(date.today()).isoformat(),
        mitarbeiter=mitarbeiter,
        alle_schichten=alle_schichten,
        plan=plan,
        urlaub_map=urlaub_map,
        abwesenheit_map=abwesenheit_map,
        abwesenheit_typ_labels=m.ABWESENHEIT_TYP_LABELS,
        feiertage=feiertage,
        kpi=kpi,
        tag_summary=tag_summary,
        pause_reg=pause_reg,
        heute=date.today(),
        woche_status=status,
        woche_gesperrt=(status['STATUS'] == 'freigegeben'),
        woche_log=log,
        vorlagen=vorlagen,
    )


def _redirect_schichtplan(montag_raw: str, rueck: str):
    """Redirect nach Zuordnungs-Aktionen: 'matrix' (Default) oder 'raster'."""
    ziel = ('wawi_personal.schichtplan_raster' if rueck == 'raster'
            else 'wawi_personal.schichtplan')
    return redirect(url_for(ziel, woche=montag_raw))


@bp.post('/schichtplan/zuordnung')
@backoffice_required
def schichtplan_zuordnung_anlegen():
    montag_raw = request.form.get('woche', '')
    rueck = request.form.get('rueck', 'matrix')
    try:
        pers_id = int(request.form['pers_id'])
        datum = _form_to_date(request.form.get('datum'))
        schicht_id = int(request.form['schicht_id'])
        if not datum:
            raise ValueError('Datum ist Pflicht.')
        dauer_raw = (request.form.get('dauer_min') or '').strip()
        dauer_min = int(dauer_raw) if dauer_raw.isdigit() else None
        m.schicht_zuordnung_insert(
            pers_id, datum, schicht_id,
            request.form.get('kommentar', '').strip() or None,
            session['ma_id'],
            dauer_min=dauer_min,
        )
        flash('Schicht zugeordnet.', 'ok')
    except (ValueError, KeyError) as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return _redirect_schichtplan(montag_raw, rueck)


@bp.get('/schichtplan/raster')
@backoffice_required
def schichtplan_raster():
    """Wochenansicht mit Uhrzeit auf der Y-Achse und Tagen auf der X-Achse.
    Nur fix-Schichten sind im Raster platziert (flex/aufgabe unten als Liste)."""
    montag = _parse_woche(request.args.get('woche'))
    tage = [montag + timedelta(days=i) for i in range(7)]
    zuordnungen = m.schicht_zuordnungen_woche(montag)
    mitarbeiter = m.ma_aktiv_am(montag + timedelta(days=6))
    ma_by_id = {ma['PERS_ID']: ma for ma in mitarbeiter}

    # Raster-Fenster dynamisch anhand tatsaechlicher fix-Schichten ermitteln
    fix_z = [z for z in zuordnungen if z.get('TYP') == 'fix'
                                     and z.get('STARTZEIT') and z.get('ENDZEIT')]
    from_h, to_h = 6, 20
    if fix_z:
        starts = [m._zeit_zu_min(z['STARTZEIT']) // 60 for z in fix_z]
        ends_raw = []
        for z in fix_z:
            s = m._zeit_zu_min(z['STARTZEIT'])
            e = m._zeit_zu_min(z['ENDZEIT'])
            ends_raw.append(e if e > s else e + 24 * 60)  # Nachtschicht
        ends = [(e + 59) // 60 for e in ends_raw]  # aufrunden
        from_h = max(0, min(starts) - 1)
        to_h   = min(26, max(ends) + 1)
    stunden = list(range(from_h, to_h))

    # Indizes fuer das Template.
    # Fix-Schichten werden pro (Datum, Schicht) zu EINEM Block gruppiert und
    # listen alle zugeordneten MA – sonst wuerden Zuordnungen mit identischer
    # Kernzeit im Raster uebereinanderliegen und nur einer waere sichtbar.
    plan_fix = {}    # datum → Liste Gruppen {schicht-felder, _start_min, _ende_min, mas:[...]}
    plan_flex = {}   # datum → Liste flex-Zuordnungen
    plan_task = {}   # datum → Liste aufgabe-Zuordnungen
    fix_gruppen = {}  # (datum, schicht_id) → Gruppen-Dict
    for z in zuordnungen:
        ma = ma_by_id.get(z['PERS_ID'], {})
        if z.get('TYP') == 'fix' and z.get('STARTZEIT') and z.get('ENDZEIT'):
            s = m._zeit_zu_min(z['STARTZEIT'])
            e = m._zeit_zu_min(z['ENDZEIT'])
            if e <= s:
                e = e + 24 * 60
            schluessel = (z['DATUM'], z['SCHICHT_ID'])
            gr = fix_gruppen.get(schluessel)
            if gr is None:
                gr = {
                    'SCHICHT_ID': z['SCHICHT_ID'],
                    'KUERZEL':    z['KUERZEL'],
                    'BEZEICHNUNG': z['BEZEICHNUNG'],
                    'FARBE':      z['FARBE'],
                    'STARTZEIT':  z['STARTZEIT'],
                    'ENDZEIT':    z['ENDZEIT'],
                    'DATUM':      z['DATUM'],
                    '_start_min': s,
                    '_ende_min':  e,
                    'mas':        [],
                }
                fix_gruppen[schluessel] = gr
                plan_fix.setdefault(z['DATUM'], []).append(gr)
            # MA-Eintrag inkl. REC_ID der Zuordnung (fuer Remove im Overlay).
            gr['mas'].append({**ma, 'REC_ID': z['REC_ID']})
        elif z.get('TYP') == 'flex':
            z['_ma'] = ma
            plan_flex.setdefault(z['DATUM'], []).append(z)
        else:
            z['_ma'] = ma
            plan_task.setdefault(z['DATUM'], []).append(z)

    jahr, kw = m._iso_jahr_kw(montag)
    status = m.woche_status(jahr, kw)
    vorlagen = m.vorlage_liste()
    feiertage = m.feiertage_im_zeitraum(montag, montag + timedelta(days=6))

    return render_template(
        'personal/schichtplan_raster.html',
        montag=montag,
        tage=tage,
        wochennummer=kw,
        jahr=jahr,
        vorwoche=(montag - timedelta(days=7)).isoformat(),
        folgewoche=(montag + timedelta(days=7)).isoformat(),
        aktuelle_woche=m.montag_der_woche(date.today()).isoformat(),
        stunden=stunden,
        raster_von_min=from_h * 60,
        raster_bis_min=to_h * 60,
        plan_fix=plan_fix,
        plan_flex=plan_flex,
        plan_task=plan_task,
        mitarbeiter=mitarbeiter,
        heute=date.today(),
        woche_status=status,
        woche_gesperrt=(status['STATUS'] == 'freigegeben'),
        vorlagen=vorlagen,
        feiertage=feiertage,
    )


@bp.post('/schichtplan/zuordnung/<int:rec_id>/loeschen')
@backoffice_required
def schichtplan_zuordnung_loeschen(rec_id: int):
    montag_raw = request.form.get('woche', '')
    rueck = request.form.get('rueck', 'matrix')
    try:
        n = m.schicht_zuordnung_delete(rec_id)
        flash('Zuordnung entfernt.' if n else 'Nicht gefunden.',
              'ok' if n else 'error')
    except Exception as e:
        flash(f'Fehler: {e}', 'error')
    return _redirect_schichtplan(montag_raw, rueck)


@bp.post('/schichtplan/kopieren')
@backoffice_required
def schichtplan_kopieren():
    """Kopiert alle Zuordnungen einer Quell-KW in eine Ziel-KW (Zukunft).
    Ziel muss leer sein (sonst Abbruch). Warnungen bei Urlaub/Austritt/Eintritt
    werden als Flash-Meldung angezeigt."""
    quelle_raw = request.form.get('woche', '')
    ziel_raw = request.form.get('ziel_woche', '')
    try:
        quelle_montag = _parse_woche(quelle_raw)
        if not ziel_raw:
            raise ValueError('Ziel-Woche angeben.')
        ziel_montag = _parse_woche(ziel_raw)
        ergebnis = m.schichtplan_kopieren_in_woche(
            quelle_montag, ziel_montag, session['ma_id'],
        )
        jahr, kw = m._iso_jahr_kw(ziel_montag)
        flash(f"KW {kw:02d}/{jahr}: {ergebnis['kopiert']} Zuordnungen kopiert.",
              'ok')
        for w in ergebnis['warnungen']:
            flash(f'Warnung: {w}', 'info')
        return redirect(url_for('wawi_personal.schichtplan',
                                woche=ziel_montag.isoformat()))
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Kopieren: {e}', 'error')
    return redirect(url_for('wawi_personal.schichtplan', woche=quelle_raw))


@bp.post('/schichtplan/vorlage/speichern')
@backoffice_required
def schichtplan_vorlage_speichern():
    """Speichert die Zuordnungen einer Quell-KW als Vorlage."""
    quelle_raw = request.form.get('woche', '')
    name = request.form.get('name', '').strip()
    beschreibung = request.form.get('beschreibung', '').strip() or None
    rueck = request.form.get('rueck', 'matrix')
    try:
        quelle_montag = _parse_woche(quelle_raw)
        m.vorlage_speichern(quelle_montag, name, session['ma_id'], beschreibung)
        flash(f'Vorlage "{name}" gespeichert.', 'ok')
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    return _redirect_schichtplan(quelle_raw, rueck)


@bp.post('/schichtplan/vorlage/anwenden')
@backoffice_required
def schichtplan_vorlage_anwenden():
    """Wendet eine Vorlage auf die Ziel-KW an (Ziel muss leer, in Zukunft)."""
    quelle_raw = request.form.get('woche', '')
    ziel_raw = request.form.get('ziel_woche', '')
    vorlage_id_raw = request.form.get('vorlage_id', '')
    try:
        if not vorlage_id_raw:
            raise ValueError('Vorlage auswaehlen.')
        if not ziel_raw:
            raise ValueError('Ziel-Woche angeben.')
        ziel_montag = _parse_woche(ziel_raw)
        ergebnis = m.vorlage_anwenden(
            int(vorlage_id_raw), ziel_montag, session['ma_id'],
        )
        jahr, kw = m._iso_jahr_kw(ziel_montag)
        flash(f"KW {kw:02d}/{jahr}: {ergebnis['angelegt']} Zuordnungen "
              f"aus Vorlage angelegt.", 'ok')
        for w in ergebnis['warnungen']:
            flash(f'Warnung: {w}', 'info')
        return redirect(url_for('wawi_personal.schichtplan',
                                woche=ziel_montag.isoformat()))
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Anwenden: {e}', 'error')
    return redirect(url_for('wawi_personal.schichtplan', woche=quelle_raw))


@bp.post('/schichtplan/vorlage/<int:rec_id>/loeschen')
@backoffice_required
def schichtplan_vorlage_loeschen(rec_id: int):
    """Loescht eine Vorlage inkl. aller Zuordnungen."""
    quelle_raw = request.form.get('woche', '')
    rueck = request.form.get('rueck', 'matrix')
    try:
        n = m.vorlage_loeschen(rec_id)
        if n > 0:
            flash('Vorlage geloescht.', 'ok')
        else:
            flash('Vorlage nicht gefunden.', 'info')
    except Exception as e:
        flash(f'Fehler beim Loeschen: {e}', 'error')
    return _redirect_schichtplan(quelle_raw, rueck)


@bp.post('/schichtplan/freigabe')
@backoffice_required
def schichtplan_freigabe():
    """Toggelt den Wochen-Status zwischen 'offen' und 'freigegeben'.
    Aktion kommt aus dem Form-Feld 'aktion' ('freigeben' | 'entsperren').
    Bei 'freigeben' werden zusaetzlich die MA-Benachrichtigungsmails versendet
    (siehe common/email.py; Dev-Mode schickt alles an den Freigebenden)."""
    montag_raw = request.form.get('woche', '')
    aktion = request.form.get('aktion', '').strip()
    kommentar = request.form.get('kommentar', '').strip() or None
    rueck = request.form.get('rueck', 'matrix')  # matrix | raster
    try:
        montag = _parse_woche(montag_raw)
        jahr, kw = m._iso_jahr_kw(montag)
        if aktion == 'freigeben':
            m.woche_freigeben(jahr, kw, session['ma_id'], kommentar)
            flash(f'KW {kw:02d}/{jahr} freigegeben und gesperrt.', 'ok')
            mail = m.schichtplan_freigabe_emails_senden(montag, session['ma_id'])
            if mail['modus'] == 'dev':
                flash(f"Dev-Modus: {mail['gesendet']} Mail(s) an dich als "
                      f"Freigebenden umgeleitet.", 'info')
            elif mail['modus'] == 'ok' and mail['gesendet'] > 0:
                flash(f"{mail['gesendet']} Benachrichtigung(en) versendet.", 'ok')
            elif mail['modus'] == 'disabled':
                flash('Email-Versand deaktiviert (SMTP nicht konfiguriert).',
                      'info')
            for f in mail.get('fehler', []):
                flash(f'Mail-Fehler: {f}', 'error')
        elif aktion == 'entsperren':
            m.woche_entsperren(jahr, kw, session['ma_id'], kommentar)
            flash(f'KW {kw:02d}/{jahr} entsperrt.', 'ok')
        else:
            flash(f'Unbekannte Aktion: {aktion!r}', 'error')
    except ValueError as e:
        flash(f'Fehler: {e}', 'error')
    except Exception as e:
        flash(f'Fehler beim Speichern: {e}', 'error')
    ziel = ('wawi_personal.schichtplan_raster' if rueck == 'raster'
            else 'wawi_personal.schichtplan')
    return redirect(url_for(ziel, woche=montag_raw))


@bp.route('/email-diag', methods=['GET'])
@backoffice_required
def email_diagnose():
    """Zeigt die effektive Email-Config + Herkunft pro Key (REGISTRY/ENV/INI).

    Nur fuer Backoffice sichtbar. Passwoerter werden maskiert. Schreibt nicht.
    """
    from common.config import email_config_diagnose
    return render_template('personal/email_diagnose.html',
                           diag=email_config_diagnose())


def create_blueprint():
    return bp
