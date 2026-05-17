"""Flask-Routes für Orga – Lieferantenkataloge.

Landing = Übersicht ALLER Kataloge (keine Artikel). Artikel erst
nach Auswahl eines Katalogs (``?lief=``). Excel-Upload (festes
Kramer-Format) je gewähltem Lieferant; Markierung pro Artikel
(„bestellen" / „in Artikelstamm übernehmen"); Katalog entfernbar.
Adress-Anlage/-Änderung liegt in Stammdaten/Adressen, NICHT hier.
"""
from __future__ import annotations

import logging
import os
import tempfile

from flask import (Blueprint, render_template, request, jsonify,
                   session, abort, redirect, url_for, flash)

from common import listing
from . import models as m

log = logging.getLogger(__name__)
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
    """Übersicht ALLER Kataloge. Artikel nur, wenn ein Katalog
    explizit gewählt ist (``?lief=``) — sonst keine Positionen."""
    _login_check()
    lieferanten = m.lieferanten_mit_katalog()
    sel = (request.args.get('lief') or '').strip()

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


@bp.post('/loeschen')
def katalog_loeschen():
    """Entfernt einen Katalog vollständig (alle Zeilen des
    Lieferanten)."""
    _login_check()
    kuerzel = (request.form.get('lief') or '').strip()
    if not kuerzel:
        flash('Kein Katalog angegeben.', 'fehler')
        return redirect(url_for('orga_lieferantenkatalog.uebersicht'))
    try:
        n = m.katalog_loeschen(kuerzel)
        flash(f'Katalog „{kuerzel}" entfernt ({n} Positionen).', 'ok')
    except (ValueError, LookupError) as e:
        flash(f'Nicht entfernt: {e}', 'fehler')
    except Exception as e:  # noqa: BLE001
        log.exception('Katalog löschen')
        flash(f'Fehler: {e}', 'fehler')
    return redirect(url_for('orga_lieferantenkatalog.uebersicht'))


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


def create_blueprint():
    return bp
