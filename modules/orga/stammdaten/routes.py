"""Flask-Routes für Orga – Stammdaten/Adressen.

CAO-Adresse anlegen/bearbeiten über ``common.cao_adressen``
(ADRESSEN + ADRESSEN_LOG + XT-HMAC; Record-Lock beim Ändern).
Hierher verschoben aus dem Lieferantenkatalog (Adressen sind
übergreifende Stammdaten, kein Katalog-Belang).
"""
from __future__ import annotations

import logging

from flask import (Blueprint, render_template, request, jsonify,
                   session, abort, redirect, url_for, flash)

from common import cao_adressen as adr

log = logging.getLogger(__name__)
bp = Blueprint('orga_stammdaten', __name__, template_folder='templates')

# Stamm-Formular: Gruppen → [(Spalte, Label, Typ)]. Spalten müssen in
# cao_adressen.EDITIERBAR sein.
FELDGRUPPEN = [
    ('Name & Anschrift', [
        ('NAME1', 'Name 1', 'text'), ('NAME2', 'Name 2', 'text'),
        ('NAME3', 'Name 3', 'text'), ('ANREDE', 'Anrede', 'text'),
        ('ABTEILUNG', 'Abteilung', 'text'),
        ('BRIEFANREDE', 'Briefanrede', 'text'),
        ('STRASSE', 'Straße', 'text'), ('HAUSNR', 'Haus-Nr', 'text'),
        ('ADRESSZUSATZ', 'Adresszusatz', 'text'),
        ('PLZ', 'PLZ', 'text'), ('ORT', 'Ort', 'text'),
        ('LAND', 'Land', 'text'),
        ('POSTFACH', 'Postfach', 'text'),
        ('PF_PLZ', 'Postfach-PLZ', 'text'),
        ('KUNNUM1', 'Kunden-/Lief-Nr 1', 'text'),
        ('KUNNUM2', 'Kunden-/Lief-Nr 2', 'text')]),
    ('Kontakt', [
        ('TELE1', 'Telefon 1', 'text'), ('TELE2', 'Telefon 2', 'text'),
        ('FAX', 'Fax', 'text'), ('FUNK', 'Mobil', 'text'),
        ('EMAIL', 'E-Mail', 'text'), ('EMAIL2', 'E-Mail 2', 'text'),
        ('INTERNET', 'Internet', 'text')]),
    ('Bank', [
        ('IBAN', 'IBAN', 'text'), ('SWIFT', 'BIC/SWIFT', 'text'),
        ('BANK', 'Bank', 'text'), ('BLZ', 'BLZ', 'text'),
        ('KTO', 'Konto', 'text'),
        ('KTO_INHABER', 'Kontoinhaber', 'text')]),
    ('Steuer & Konditionen', [
        ('UST_NUM', 'USt-IdNr', 'text'), ('UID', 'UID', 'text'),
        ('WAEHRUNG', 'Währung', 'text'),
        ('BRUTTO_FLAG', 'Brutto-Preise', 'jn'),
        ('PR_EBENE', 'Preisebene', 'num'),
        ('LIEF_LIEFART', 'Lief.-Lieferart-ID', 'num'),
        ('LIEF_ZAHLART', 'Lief.-Zahlart-ID', 'num'),
        ('LIEF_PRLISTE', 'Lief.-Preisliste', 'jn'),
        ('LIEF_TKOSTEN', 'Lief.-Transportkosten', 'num'),
        ('LIEF_MBWERT', 'Lief.-Mindestbestellwert', 'num'),
        ('KUN_LIEFART', 'Kun.-Lieferart-ID', 'num'),
        ('KUN_ZAHLART', 'Kun.-Zahlart-ID', 'num'),
        ('KUN_PRLISTE', 'Kun.-Preisliste', 'jn'),
        ('DIVERSES', 'Diverses', 'text')]),
]


def _login_check() -> None:
    if not session.get('ma_id'):
        abort(401)


@bp.get('/adressen')
def adressen():
    """Landing: Einstieg zur Adress-Pflege."""
    _login_check()
    return render_template('stammdaten_adressen.html')


@bp.get('/adressen/form')
def adresse_form():
    """Stamm-Formular: neu (ohne ?id) oder bearbeiten (?id=)."""
    _login_check()
    rid = request.args.get('id', type=int)
    werte: dict = {}
    if rid:
        a = adr.adresse_holen(rid)
        if not a:
            abort(404)
        werte = {k: ('' if v is None else v) for k, v in a.items()}
    return render_template('stammdaten_adresse.html',
                           gruppen=FELDGRUPPEN, werte=werte, rid=rid)


@bp.post('/adressen/form')
def adresse_speichern():
    """Anlegen (kein Lock) bzw. Ändern (CAO-Record-Lock)."""
    _login_check()
    rid = request.form.get('id', type=int)
    ma = (session.get('login_name') or session.get('mitarbeiter')
          or 'CAO-XT')
    erlaubt = {c for _, felder in FELDGRUPPEN for c, _, _ in felder}
    felder = {k: (request.form.get(k) or '').strip()
              for k in erlaubt if k in request.form}
    try:
        if rid:
            adr.adresse_aendern(rid, felder, ma_name=ma)
            flash(f'Adresse #{rid} gespeichert.', 'ok')
        else:
            if not felder.get('NAME1'):
                flash('Name 1 ist Pflicht.', 'fehler')
                return redirect(url_for(
                    'orga_stammdaten.adresse_form'))
            neu = adr.adresse_anlegen(felder, ma_name=ma)
            flash(f'Adresse #{neu} „{felder.get("NAME1")}" angelegt.',
                  'ok')
    except (ValueError, LookupError, RuntimeError) as e:
        flash(f'Nicht gespeichert: {e}', 'fehler')
        return redirect(url_for('orga_stammdaten.adresse_form',
                                **({'id': rid} if rid else {})))
    except Exception as e:  # noqa: BLE001 - Salt/DB
        log.exception('Adresse speichern')
        flash(f'Fehler: {e}', 'fehler')
        return redirect(url_for('orga_stammdaten.adresse_form',
                                **({'id': rid} if rid else {})))
    return redirect(url_for('orga_stammdaten.adressen'))


@bp.get('/api/plz')
def api_plz():
    """Ort-Vorschlag zur PLZ (CAO-PLZ-Tabelle)."""
    _login_check()
    orte = adr.plz_orte(request.args.get('land') or 'DE',
                        request.args.get('plz') or '')
    return jsonify(ok=True, orte=[
        {'ort': o.get('NAME'), 'bundesland': o.get('BUNDESLAND'),
         'vorwahl': o.get('VORWAHL')} for o in orte])


def create_blueprint():
    return bp
