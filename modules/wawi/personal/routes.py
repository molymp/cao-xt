"""
CAO-XT WaWi-Personal – Flask-Blueprint (P1 Stammdaten).

Registrierung:
    from modules.wawi.personal import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi/personal')
"""
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash)

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
            # Stundensatz: nur speichern wenn Wert+Datum angegeben
            satz_raw = request.form.get('stundensatz', '').strip()
            ab_raw = request.form.get('stundensatz_ab', '').strip()
            if satz_raw and ab_raw:
                m.stundensatz_setzen(
                    pers_id,
                    _form_to_date(ab_raw),
                    _euro_to_ct(satz_raw),
                    request.form.get('stundensatz_kommentar', '').strip() or None,
                    session['ma_id'],
                )
                flash('Stundensatz hinzugefuegt.', 'ok')
            if anz:
                flash(f'{anz} Feld(er) aktualisiert.', 'ok')
            elif not (satz_raw and ab_raw):
                flash('Keine Aenderungen.', 'info')
            return redirect(url_for('wawi_personal.detail', pers_id=pers_id))
        except (ValueError, LookupError) as e:
            flash(str(e), 'error')
        except Exception as e:
            flash(f'Fehler beim Speichern: {e}', 'error')
        # bei Fehler: Formular mit POST-Werten rendern
        ma = {**ma, **_form_werte(request.form)}

    aktuell_ct = m.aktueller_stundensatz_ct(pers_id)
    return render_template('personal/ma_detail.html',
                           ma=ma,
                           aktueller_stundensatz=m.ct_to_eurostr(aktuell_ct))


def create_blueprint():
    return bp
