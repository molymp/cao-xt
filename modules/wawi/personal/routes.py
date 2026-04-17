"""
CAO-XT WaWi-Personal – Flask-Blueprint (P1 Stammdaten).

Registrierung:
    from modules.wawi.personal import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi/personal')
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify)

from .auth import backoffice_required
from . import models as m


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

@bp.get('/')
@backoffice_required
def uebersicht():
    zeige_alle = request.args.get('alle') == '1'
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


def create_blueprint():
    return bp
