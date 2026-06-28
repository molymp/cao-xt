"""Flask-Routes für Orga – Stammdaten/Adressen.

CAO-Adresse anlegen/bearbeiten über ``common.cao_adressen``
(ADRESSEN + ADRESSEN_LOG + XT-HMAC; Record-Lock beim Ändern).
Hierher verschoben aus dem Lieferantenkatalog (Adressen sind
übergreifende Stammdaten, kein Katalog-Belang).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from flask import (Blueprint, render_template, request, jsonify,
                   session, abort, redirect, url_for, flash, Response)

from common import cao_adressen as adr
from common import cao_artikel as art
from common import preisplan as preisplan_mod
from common import etiketten as etiketten_mod
from common.druck import routing as druck_routing

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


def _preise_json(rows: list) -> list:
    """ARTIKEL_PREIS-Zeilen JSON-tauglich machen (Decimal→float, Datum→ISO)."""
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
            else:
                d[k] = v
        out.append(d)
    return out


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
    """Artikel-Stammdaten: Warengruppen-Baum + Merkmale (Filter); die
    Artikel-Tabelle lädt per AJAX (artikel_daten), damit der Baum offen
    bleibt und Spalten konfigurierbar sind."""
    _login_check()
    # Dokumenttyp im zentralen Druck-Katalog registrieren (best-effort).
    # Orga druckt die Artikel-Liste nicht via ESC/POS (Browser/HTML).
    druck_routing.register_doktyp('artikelliste', 'Artikel-Liste', 'orga')
    baum = art.warengruppen_tree()
    # Rekursive Artikel-Anzahl je Knoten (inkl. Untergruppen) wie CAO.
    kinder: dict = {}
    for n in baum:
        kinder.setdefault(n['parent_id'], []).append(n)
    def _gesamt(node):
        s = node['direkt']
        for c in kinder.get(node['id'], []):
            s += _gesamt(c)
        node['gesamt'] = s
        return s
    for n in baum:
        _gesamt(n)
    return render_template('stammdaten_artikel.html',
                           baum=baum, merkmale=art.merkmale_liste(),
                           spalten=art.liste_spalten_meta(),
                           aktion_anzahl=art.aktionspreise_anzahl(),
                           wg_aktiv=request.args.get('wg', type=int),
                           merk_aktiv=request.args.get('merk', type=int),
                           aktion_aktiv=bool(request.args.get('aktion')),
                           alle_aktiv=bool(request.args.get('alle')),
                           suche=(request.args.get('q') or '').strip())


@bp.get('/artikel/daten')
def artikel_daten():
    """JSON: Artikelzeilen für die konfigurierbare Tabelle (Filter via
    wg / merk / q; Sort via sort / dir)."""
    _login_check()
    q = (request.args.get('q') or '').strip()
    wg_id = request.args.get('wg', type=int)
    merk_id = request.args.get('merk', type=int)
    aktion = bool(request.args.get('aktion'))
    alle = bool(request.args.get('alle'))
    sort = request.args.get('sort') or 'BEZ'
    sort_dir = request.args.get('dir') or 'asc'
    if not (q or wg_id or merk_id or aktion or alle):
        return jsonify(ok=True, rows=[])
    rows = art.artikel_liste(q, wg_id=wg_id, merk_id=merk_id,
                             nur_aktion=aktion, sort=sort, sort_dir=sort_dir,
                             limit=10000 if alle else 2000)
    typ = {k: t for k, _l, _s, t, _d in art.LISTE_SPALTEN}
    out = []
    for r in rows:
        d = {'REC_ID': r['REC_ID']}
        for k, v in r.items():
            if k == 'REC_ID':
                continue
            if v is None or v == '':
                d[k] = None
            elif typ.get(k) in ('num', 'int'):
                try:
                    d[k] = float(str(v).replace(',', '.'))
                except (TypeError, ValueError):
                    d[k] = None
            elif typ.get(k) == 'date':
                d[k] = v.isoformat() if hasattr(v, 'isoformat') else str(v)
            else:
                d[k] = v
        out.append(d)
    return jsonify(ok=True, rows=out)


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
        lieferantenpreise_json=_preise_json(art.lieferantenpreise(rec_id)),
        default_lief=a.get('DEFAULT_LIEF_ID'),
        kundenpreise=art.kundenpreise(rec_id),
        aktionspreis=art.aktionspreis(rec_id),
        lagerbestaende=art.lagerbestaende(rec_id),
        dateien=art.dateien(rec_id),
        historie=art.vorgangs_historie(rec_id),
        bestand_historie=art.bestand_historie(rec_id),
        quelle_label=art.QUELLE_LABEL,
        plaene=preisplan_mod.je_artikel(rec_id))


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


@bp.get('/artikel/<int:rec_id>/etikett.svg')
def artikel_etikett(rec_id: int):
    """Artikel-Preis-Etikett als SVG (Vektor; druck-/PDF-fähig)."""
    _login_check()
    # Dokumenttyp im zentralen Druck-Katalog registrieren (best-effort).
    # Regaletikett wird als SVG ausgeliefert, nicht via ESC/POS gedruckt.
    druck_routing.register_doktyp('regaletikett', 'Regaletikett', 'orga')
    if not art.artikel_holen(rec_id):
        abort(404)
    svg = etiketten_mod.artikel_etikett_svg(rec_id)
    return Response(svg, mimetype='image/svg+xml')


@bp.get('/artikel/lieferanten')
def artikel_lieferanten():
    """Adress-Suche für den Lieferanten-Picker."""
    _login_check()
    return jsonify(ok=True, treffer=art.lieferanten_suche(
        request.args.get('q') or ''))


@bp.post('/artikel/<int:rec_id>/lieferantenpreis')
def artikel_lieferantenpreis(rec_id: int):
    """Lieferantenpreis anlegen/ändern (+ optional Standard-Lieferant)."""
    _login_check()
    from common.cao_lock import CaoLockBelegt
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    adress_id = request.form.get('adress_id', type=int)
    if not adress_id:
        return jsonify(ok=False, fehler='Kein Lieferant gewählt.'), 400
    try:
        art.lieferantenpreis_speichern(
            rec_id, adress_id,
            bestnum=request.form.get('bestnum') or '',
            vpe=request.form.get('vpe') or 0,
            preis=request.form.get('ek') or 0,
            als_standard=bool(request.form.get('standard')),
            ma_name=ma)
    except CaoLockBelegt:
        return jsonify(ok=False, fehler='Artikel ist gerade gesperrt.'), 409
    except Exception as e:  # noqa: BLE001
        log.exception('Lieferantenpreis speichern')
        return jsonify(ok=False, fehler=str(e)), 400
    return jsonify(ok=True, preise=_preise_json(art.lieferantenpreise(rec_id)),
                   default_lief=(art.artikel_holen(rec_id) or {}).get('DEFAULT_LIEF_ID'))


@bp.post('/artikel/<int:rec_id>/lieferantenpreis/loeschen')
def artikel_lieferantenpreis_loeschen(rec_id: int):
    """Lieferantenpreis löschen."""
    _login_check()
    from common.cao_lock import CaoLockBelegt
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    adress_id = request.form.get('adress_id', type=int)
    if not adress_id:
        return jsonify(ok=False, fehler='Kein Lieferant.'), 400
    try:
        art.lieferantenpreis_loeschen(rec_id, adress_id, ma_name=ma)
    except CaoLockBelegt:
        return jsonify(ok=False, fehler='Artikel ist gerade gesperrt.'), 409
    except Exception as e:  # noqa: BLE001
        log.exception('Lieferantenpreis löschen')
        return jsonify(ok=False, fehler=str(e)), 400
    return jsonify(ok=True, preise=_preise_json(art.lieferantenpreise(rec_id)),
                   default_lief=(art.artikel_holen(rec_id) or {}).get('DEFAULT_LIEF_ID'))


# ── Preisplanung (XT, mehrere Aktionen/Preisänderungen je Artikel) ─────

def _zurueck():
    return redirect(request.form.get('next') or request.referrer
                    or url_for('orga_stammdaten.preisplan'))


@bp.get('/preisplan')
def preisplan():
    """Übersicht geplante Preisänderungen/Aktionen (Schilddruck)."""
    _login_check()
    from datetime import date as _date
    offen = bool(request.args.get('offen'))
    return render_template('stammdaten_preisplan.html',
                           rows=preisplan_mod.uebersicht(nur_offen_schild=offen),
                           nur_offen=offen, heute=_date.today().isoformat())


@bp.post('/preisplan/anlegen')
def preisplan_anlegen():
    _login_check()
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    aid = request.form.get('artikel_id', type=int)
    ab = (request.form.get('gueltig_ab') or '').strip()
    if not aid or not ab:
        flash('Artikel und Stichtag sind Pflicht.', 'fehler')
        return _zurueck()
    vks = [request.form.get(f'vk{i}') for i in range(1, 6)]
    if request.form.get('brutto'):
        # Eingabe ist Brutto (Schild-Preis) → in Netto umrechnen (Speicherung
        # wie CAO-Aktionspreis netto). Satz aus STEUER_CODE des Artikels.
        a = art.artikel_holen(aid) or {}
        rate = {0: 0.0, 1: 0.19, 2: 0.07, 3: 0.0}.get(
            int(a.get('STEUER_CODE') or 0), 0.0)
        vks = [(round(float(str(v).replace(',', '.')) / (1 + rate), 4)
                if v not in (None, '') else None) for v in vks]
    try:
        preisplan_mod.anlegen(aid, request.form.get('art') or 'aktion', vks, ab,
                              (request.form.get('gueltig_bis') or '').strip() or None,
                              notiz=request.form.get('notiz') or '', ma_name=ma)
        flash('Preisplan-Eintrag angelegt.', 'ok')
    except Exception as e:  # noqa: BLE001
        log.exception('Preisplan anlegen')
        flash(f'Fehler: {e}', 'fehler')
    return _zurueck()


@bp.post('/preisplan/<int:rec_id>/loeschen')
def preisplan_loeschen(rec_id: int):
    _login_check()
    preisplan_mod.loeschen(rec_id)
    flash('Eintrag gelöscht.', 'ok')
    return _zurueck()


@bp.post('/preisplan/<int:rec_id>/anwenden')
def preisplan_anwenden(rec_id: int):
    _login_check()
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    try:
        preisplan_mod.anwenden(rec_id, ma_name=ma)
        flash('Änderung angewendet (in CAO geschrieben).', 'ok')
    except Exception as e:  # noqa: BLE001
        log.exception('Preisplan anwenden')
        flash(f'Fehler beim Anwenden: {e}', 'fehler')
    return _zurueck()


@bp.post('/preisplan/<int:rec_id>/zuruecksetzen')
def preisplan_zuruecksetzen(rec_id: int):
    _login_check()
    ma = (session.get('login_name') or session.get('mitarbeiter') or 'CAO-XT')
    try:
        preisplan_mod.zuruecksetzen(rec_id, ma_name=ma)
        flash('Änderung zurückgesetzt.', 'ok')
    except Exception as e:  # noqa: BLE001
        log.exception('Preisplan zuruecksetzen')
        flash(f'Fehler: {e}', 'fehler')
    return _zurueck()


@bp.post('/preisplan/<int:rec_id>/schild')
def preisplan_schild(rec_id: int):
    _login_check()
    gedruckt = request.form.get('gedruckt') not in (None, '0', 'false')
    preisplan_mod.schild_setzen(rec_id, gedruckt)
    return jsonify(ok=True, gedruckt=gedruckt)


def create_blueprint():
    from . import schema as _schema
    _schema.run_migration()
    return bp
