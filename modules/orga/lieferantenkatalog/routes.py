"""Flask-Routes für Orga – Lieferantenkataloge.

v1: Excel-Upload (festes Kramer-Format) je gewähltem Lieferant,
Liste/Suche/Sortierung je Lieferant, Markierung pro Artikel
(„bestellen" / „in Artikelstamm übernehmen"). Aktionen (Brücke in
cao_sync) folgen als eigene Einheit.
"""
from __future__ import annotations

import logging
import os
import tempfile

from flask import (Blueprint, render_template, request, jsonify,
                   session, abort, redirect, url_for, flash)

from common import listing
from common import cao_adressen as adr
from . import models as m

log = logging.getLogger(__name__)

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
bp = Blueprint('orga_lieferantenkatalog', __name__,
               template_folder='templates')

_MAX_UPLOAD = 8 * 1024 * 1024  # 8 MB reicht für Katalog-Excels


def _login_check() -> None:
    if not session.get('ma_id'):
        abort(401)


def _slug(name: str) -> str:
    s = ''.join(c if c.isalnum() else '-' for c in (name or '').upper())
    return s.strip('-')[:20] or 'LIEF'


@bp.get('/')
def uebersicht():
    """Lieferanten-Übersicht + (bei Auswahl) Katalog-Tabelle."""
    _login_check()
    lieferanten = m.lieferanten_mit_katalog()
    sel = (request.args.get('lief') or '').strip()
    if not sel and lieferanten:
        sel = lieferanten[0]['LIEFERANT_KUERZEL']

    daten = None
    kategorien: list[str] = []
    suche = (request.args.get('q') or '').strip()
    kategorie = (request.args.get('kat') or '').strip()
    status = (request.args.get('status') or 'aktiv').strip()
    order_sql, sort_key, sort_dir = listing.parse_sort(
        request.args, m.LK_SORT, m.LK_DEFAULT_ORDER)
    if sel:
        kategorien = m.kategorien(sel)
        daten = m.positionen(
            lieferant_kuerzel=sel, suche=suche, kategorie=kategorie,
            status=status, sort_sql=order_sql)

    return render_template(
        'lieferantenkatalog.html',
        lieferanten=lieferanten, sel=sel, daten=daten,
        kategorien=kategorien, suche=suche, kategorie=kategorie,
        status=status, sort_key=sort_key, sort_dir=sort_dir,
    )


@bp.post('/import')
def katalog_import():
    """Excel (Kramer-Format) für den gewählten Lieferant importieren."""
    _login_check()
    f = request.files.get('katalog')
    addr_raw = (request.form.get('lief_addr_id') or '').strip()
    lief_name = (request.form.get('lief_name') or '').strip()
    if not f or not f.filename:
        flash('Keine Datei gewählt.', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht'))
    if not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        flash('Bitte eine .xlsx-Datei wählen.', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht'))
    if not lief_name:
        flash('Bitte einen Lieferanten wählen.', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht'))
    try:
        cao_lief_id = int(addr_raw) if addr_raw.isdigit() else None
    except (TypeError, ValueError):
        cao_lief_id = None

    fd, tmp = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    try:
        f.save(tmp)
        if os.path.getsize(tmp) > _MAX_UPLOAD:
            flash('Datei zu groß (max. 8 MB).', 'fehler')
            return redirect(url_for(
                'orga_lieferantenkatalog.uebersicht'))
        kuerzel = _slug(lief_name)
        res = m.katalog_importieren(
            path=tmp, lieferant_kuerzel=kuerzel,
            lieferant_name=lief_name, cao_lief_id=cao_lief_id,
            dateiname=f.filename,
            ma_name=session.get('login_name')
                    or session.get('mitarbeiter') or 'CAO-XT')
        flash(f"Import OK: {res['positionen']} Artikel "
              f"({', '.join(res['marken']) or '–'}), "
              f"{res['entfallen']} entfallen.", 'ok')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht',
                                lief=kuerzel))
    except Exception as e:  # noqa: BLE001
        log.exception('Katalog-Import fehlgeschlagen')
        flash(f'Import fehlgeschlagen: {e}', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht'))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@bp.post('/api/pos/<int:rec_id>/flag')
def api_flag(rec_id: int):
    """Setzt eine Markierung (bestellen / in_stamm) einer Zeile."""
    _login_check()
    body = request.get_json(silent=True) or {}
    try:
        m.pos_flag_setzen(rec_id, str(body.get('feld')),
                          bool(body.get('wert')))
    except (ValueError, LookupError) as e:
        return jsonify(ok=False, fehler=str(e)), 400
    return jsonify(ok=True)


@bp.get('/adresse')
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
    return render_template('lk_adresse.html', gruppen=FELDGRUPPEN,
                           werte=werte, rid=rid)


@bp.post('/adresse')
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
                    'orga_lieferantenkatalog.adresse_form'))
            neu = adr.adresse_anlegen(felder, ma_name=ma)
            flash(f'Adresse #{neu} „{felder.get("NAME1")}" angelegt.',
                  'ok')
    except (ValueError, LookupError, RuntimeError) as e:
        flash(f'Nicht gespeichert: {e}', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.adresse_form',
                                **({'id': rid} if rid else {})))
    except Exception as e:  # noqa: BLE001 - Salt/DB
        log.exception('Adresse speichern')
        flash(f'Fehler: {e}', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.adresse_form',
                                **({'id': rid} if rid else {})))
    return redirect(url_for('orga_lieferantenkatalog.uebersicht'))


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
