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
from common import cao_artikel as art
from common.picker_data import warengruppen_baum

log = logging.getLogger(__name__)
bp = Blueprint('orga_stammdaten', __name__, template_folder='templates')

# ── Artikelpflege: Inline-Edit-Metadaten ──────────────────────────────
# Codiertes Feld → Lookup-Quelle (Dropdown + Klartext).
ART_SELECT_LOOKUP = {
    'ME_ID': 'einheit', 'BASISPR_ME_ID': 'einheit',
    'WARENGRUPPE': 'warengruppe', 'HERSTELLER_ID': 'hersteller',
    'LAGER_ID': 'lager', 'ARTIKELTYP': 'artikeltyp', 'STEUER_CODE': 'steuer',
}
ART_JN_COLS = {'NO_RABATT_FLAG', 'NO_VK_FLAG', 'NO_EK_FLAG',
               'FSK18_FLAG', 'SN_FLAG'}
ARTIKELTYP_LABEL = {'N': 'Normaler Artikel', 'S': 'Stückliste',
                    'L': 'Lohn', 'F': 'Freier Artikel', 'T': 'Text/Kommentar'}
# CAO STEUER_CODE → MwSt (Default-Sätze; 0/1/2/3 nach cao_faktura).
STEUER_LABEL = {0: '0 % (steuerfrei)', 1: '19 % (voll)',
                2: '7 % (ermäßigt)', 3: '0 % (frei)'}


def _art_lookup_list(name: str) -> list[dict]:
    quelle = {'einheit': art.einheiten, 'warengruppe': art.warengruppen,
              'hersteller': art.hersteller, 'lager': art.lager}.get(name)
    if quelle:
        return quelle()
    if name == 'artikeltyp':
        return [{'id': k, 'name': v} for k, v in ARTIKELTYP_LABEL.items()]
    if name == 'steuer':
        return [{'id': k, 'name': v} for k, v in STEUER_LABEL.items()]
    return []


def _art_anzeige_wert(col: str, val) -> str:
    col = col.upper()
    if col in ART_JN_COLS:
        return 'Ja' if str(val) in ('Y', 'y', '1') else 'Nein'
    if col == 'ARTIKELTYP':
        return ARTIKELTYP_LABEL.get(val, val or '—')
    if col == 'STEUER_CODE':
        return STEUER_LABEL.get(int(val), str(val)) if val not in (None, '') else '—'
    if col in ART_SELECT_LOOKUP:
        if val in (None, '', -1, '-1', 0, '0'):
            return '—'
        lk = {r['id']: r['name'] for r in _art_lookup_list(ART_SELECT_LOOKUP[col])}
        name = lk.get(int(val)) if str(val).lstrip('-').isdigit() else lk.get(val)
        return f'{val} – {name}' if name else str(val)
    return '—' if val in (None, '') else str(val)

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
        ('KUNNUM1', 'Adress-Nr (intern, fix)', 'text'),
        ('KUNNUM2', 'Kunden-Nr beim Lieferanten', 'text')]),
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


# Codierte Felder → Lookup-Quelle (Klartext + Dropdown-Optionen).
SELECT_LOOKUP = {
    'KUN_LIEFART': 'liefart', 'LIEF_LIEFART': 'liefart',
    'KUN_ZAHLART': 'zahlart', 'LIEF_ZAHLART': 'zahlart',
}
# Ja/Nein-Felder (inline als Dropdown).
JN_COLS = {'KUN_PRLISTE', 'LIEF_PRLISTE', 'BRUTTO_FLAG'}


def _lookup_dict(name: str) -> dict:
    """{id: name} der codierten Stammdaten (klein, daher pro Aufruf ok)."""
    quelle = {'liefart': adr.lieferarten, 'zahlart': adr.zahlungsarten,
              'sprache': adr.sprachen, 'vertreter': adr.vertreter}.get(name)
    if not quelle:
        return {}
    return {r['id']: r['name'] for r in quelle()}


def _anzeige_wert(col: str, val) -> str:
    """Klartext-Anzeige eines Feldwerts (codierte Felder aufgelöst)."""
    if col in JN_COLS:
        return 'Ja' if str(val) in ('Y', 'y', '1') else 'Nein'
    if col in SELECT_LOOKUP:
        if val in (None, '', -1, '-1', 0, '0'):
            return '—'
        name = _lookup_dict(SELECT_LOOKUP[col]).get(int(val))
        return f'{val} – {name}' if name else str(val)
    return '—' if val in (None, '') else str(val)


@bp.get('/adressen')
def adressen():
    """Adress-Liste — Volltext-Suche + Gruppen-Filter, KEINE Pagination
    (alle Treffer auf einer Seite, Tabelle ist eh sortierbar)."""
    _login_check()
    from common.picker_data import adressgruppen as _gruppen
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort') or 'NAME1'
    sort_dir = request.args.get('dir') or 'asc'
    grp_raw = (request.args.get('grp') or '').strip()
    gruppe_id: int | None = None
    if grp_raw and grp_raw.lower() != 'alle':
        try:
            gruppe_id = int(grp_raw)
        except ValueError:
            gruppe_id = None
    rows = adr.adressen_liste(q, gruppe_id=gruppe_id,
                               sort=sort, sort_dir=sort_dir)
    gruppen = _gruppen()
    # Aktive Gruppe für Sidebar-Hervorhebung
    gruppen_aktiv = grp_raw if grp_raw else ''
    return render_template('stammdaten_adressen.html',
                           rows=rows, suche=q,
                           sort_key=sort, sort_dir=sort_dir,
                           gruppen=gruppen, gruppen_aktiv=gruppen_aktiv,
                           gruppe_id=gruppe_id)


@bp.get('/adressen/<int:addr_id>')
def adresse_detail(addr_id: int):
    """Detail-Ansicht: Stammdaten + Merkmale + Lieferadressen + ASP +
    Sonderpreise + Datei-Links + komplette Vorgangshistorie (Journal,
    Lieferscheine, EK-Bestellungen, Preisanfragen)."""
    _login_check()
    a = adr.adresse_holen(addr_id)
    if not a:
        abort(404)
    from common.picker_data import adressgruppen as _gruppen
    grp_name = next((g['name'] for g in _gruppen()
                     if g['id'] == a.get('KUNDENGRUPPE')), None)
    liefart, zahlart = adr.lieferarten(), adr.zahlungsarten()
    lookups = {'liefart': {r['id']: r['name'] for r in liefart},
               'zahlart': {r['id']: r['name'] for r in zahlart},
               'sprache': _lookup_dict('sprache'),
               'vertreter': _lookup_dict('vertreter')}
    return render_template(
        'stammdaten_adresse_detail.html',
        a=a, gruppe_name=grp_name,
        editierbar=set(adr.EDITIERBAR) - {'KUNNUM1'},
        lookups=lookups, opt_lists={'liefart': liefart, 'zahlart': zahlart},
        merkmale=adr.merkmale_zu_adresse(addr_id),
        lieferadressen=adr.lieferadressen(addr_id),
        ansprechpartner=adr.ansprechpartner(addr_id),
        kundenpreise=adr.sonderpreise(addr_id, 3),       # PREIS_TYP 3 = Kunde
        lieferantenpreise=adr.sonderpreise(addr_id, 5),  # PREIS_TYP 5 = Lief.
        wgr_rabatte=adr.wgr_rabatte(addr_id),
        dateien=adr.links_zu_adresse(addr_id),
        historie=adr.vorgangs_historie(addr_id),
        quelle_label=adr.QUELLE_LABEL,
        stadium_label=adr.STADIUM_LABEL,
    )


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
    # KUNNUM1 ist die intern vergebene Adress-Nr → beim Ändern fix
    # (read-only). Beim Neuanlegen darf sie gesetzt werden.
    readonly_cols = {'KUNNUM1'} if rid else set()
    return render_template('stammdaten_adresse.html',
                           gruppen=FELDGRUPPEN, werte=werte, rid=rid,
                           readonly_cols=readonly_cols)


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
            # Adress-Nr (KUNNUM1) ist beim Ändern fix → nie überschreiben.
            felder.pop('KUNNUM1', None)
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


@bp.post('/adressen/<int:addr_id>/feld')
def adresse_feld_speichern(addr_id: int):
    """Inline-Edit: ein einzelnes Feld speichern (CAO-Log + HMAC + Lock).

    Erwartet ``feld`` + ``wert``. Antwort JSON mit dem (codiert
    aufgelösten) Anzeige-Wert für die Live-Aktualisierung."""
    _login_check()
    col = (request.form.get('feld') or '').strip().upper()
    wert = (request.form.get('wert') or '').strip()
    if col not in set(adr.EDITIERBAR) or col == 'KUNNUM1':
        return jsonify(ok=False, fehler='Feld nicht editierbar'), 400
    ma = (session.get('login_name') or session.get('mitarbeiter')
          or 'CAO-XT')
    try:
        adr.adresse_aendern(addr_id, {col: wert}, ma_name=ma)
    except (ValueError, LookupError, RuntimeError) as e:
        return jsonify(ok=False, fehler=str(e)), 400
    except Exception as e:  # noqa: BLE001
        log.exception('Feld inline speichern')
        return jsonify(ok=False, fehler=str(e)), 500
    a = adr.adresse_holen(addr_id)
    neu = a.get(col) if a else wert
    return jsonify(ok=True, wert='' if neu is None else str(neu),
                   anzeige=_anzeige_wert(col, neu))


@bp.get('/api/plz')
def api_plz():
    """Ort-Vorschlag zur PLZ (CAO-PLZ-Tabelle)."""
    _login_check()
    orte = adr.plz_orte(request.args.get('land') or 'DE',
                        request.args.get('plz') or '')
    return jsonify(ok=True, orte=[
        {'ort': o.get('NAME'), 'bundesland': o.get('BUNDESLAND'),
         'vorwahl': o.get('VORWAHL')} for o in orte])


@bp.get('/artikel')
def artikel():
    """Artikel-Stammdaten: Warengruppen-Baum (ohne Marge) + Artikel-Liste."""
    _login_check()
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort') or 'KURZNAME'
    sort_dir = request.args.get('dir') or 'asc'
    wg_raw = (request.args.get('wg') or '').strip()
    wg_id = int(wg_raw) if wg_raw.isdigit() else None
    # Artikel nur laden, wenn eine WG gewählt ODER gesucht wird (sonst
    # wären es ~3000 Zeilen) — CAO verlangt ebenfalls eine WG-Auswahl.
    rows = (art.artikel_liste(q, wg_id=wg_id, sort=sort, sort_dir=sort_dir,
                              limit=1000) if (wg_id or q) else [])
    baum = warengruppen_baum()
    # Rekursive Artikel-Anzahl je Knoten (inkl. Untergruppen) wie in CAO.
    kinder: dict = {}
    for n in baum:
        kinder.setdefault(n['parent_id'], []).append(n)
    def _gesamt(node):
        s = node['artikel_anzahl']
        for c in kinder.get(node['id'], []):
            s += _gesamt(c)
        node['gesamt'] = s
        return s
    for n in baum:
        _gesamt(n)
    return render_template('stammdaten_artikel.html',
                           rows=rows, suche=q, sort_key=sort, sort_dir=sort_dir,
                           baum=baum, wg_aktiv=wg_id,
                           artikeltyp_label=ARTIKELTYP_LABEL)


@bp.get('/artikel/<int:rec_id>')
def artikel_detail(rec_id: int):
    """Detail-Ansicht im CAO-Tab-Layout (Allgemein/Lager/Erweitert/Shop/
    Preise/Dateien/Historie/Bestand-Historie)."""
    _login_check()
    a = art.artikel_holen(rec_id)
    if not a:
        abort(404)
    lookups = {n: {r['id']: r['name'] for r in _art_lookup_list(n)}
               for n in ('einheit', 'warengruppe', 'hersteller', 'lager',
                         'artikeltyp', 'steuer')}
    opt_lists = {n: _art_lookup_list(n)
                 for n in ('einheit', 'warengruppe', 'hersteller', 'lager',
                           'artikeltyp', 'steuer')}
    return render_template(
        'stammdaten_artikel_detail.html',
        a=a, editierbar=art.EDITIERBAR, lookups=lookups, opt_lists=opt_lists,
        jn_cols=ART_JN_COLS, select_lookup=ART_SELECT_LOOKUP,
        merkmale=art.merkmale(rec_id),
        lieferantenpreise=art.lieferantenpreise(rec_id),
        kundenpreise=art.kundenpreise(rec_id),
        aktionspreis=art.aktionspreis(rec_id),
        lagerbestaende=art.lagerbestaende(rec_id),
        dateien=art.dateien(rec_id),
        historie=art.vorgangs_historie(rec_id),
        bestand_historie=art.bestand_historie(rec_id),
        quelle_label=art.QUELLE_LABEL)


@bp.post('/artikel/<int:rec_id>/feld')
def artikel_feld_speichern(rec_id: int):
    """Inline-Edit: ein ARTIKEL-Stammdatenfeld speichern (direktes UPDATE)."""
    _login_check()
    col = (request.form.get('feld') or '').strip().upper()
    wert = (request.form.get('wert') or '').strip()
    if col not in art.EDITIERBAR:
        return jsonify(ok=False, fehler='Feld nicht editierbar'), 400
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    try:
        art.artikel_feld_aendern(rec_id, col, wert, ma_name=ma)
    except (ValueError, LookupError, RuntimeError) as e:
        return jsonify(ok=False, fehler=str(e)), 400
    except Exception as e:  # noqa: BLE001
        log.exception('Artikel-Feld inline speichern')
        return jsonify(ok=False, fehler=str(e)), 500
    a = art.artikel_holen(rec_id)
    neu = a.get(col) if a else wert
    return jsonify(ok=True, wert='' if neu is None else str(neu),
                   anzeige=_art_anzeige_wert(col, neu))


def create_blueprint():
    return bp
