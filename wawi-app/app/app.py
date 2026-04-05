"""
CAO-XT WaWi-App – Flask-Hauptanwendung
Starten: cd wawi-app/app && python3 app.py
"""
import io
import logging
from datetime import datetime, date

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, flash, send_file)

import config
import db as db_modul
import preise as pr
import berichte as bericht_modul

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False


# ── Context-Processor ─────────────────────────────────────────
@app.context_processor
def _globals():
    return {
        'firma_name': config.FIRMA_NAME,
        'jetzt':      datetime.now(),
    }


def _benutzer() -> str:
    """Gibt den aktuellen Benutzernamen zurück (aus Session oder Default)."""
    return config.WAWI_BENUTZER_DEFAULT


def _serial(obj):
    """JSON-serialisierbares Objekt."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if hasattr(obj, '__float__'):
        return float(obj)
    return str(obj)


def _jsonify_rows(rows):
    """Wandelt DB-Rows (mit Datetime/Decimal) in JSON-safe Dicts."""
    if isinstance(rows, list):
        return [{k: _serial(v) for k, v in row.items()} for row in rows]
    return {k: _serial(v) for k, v in rows.items()}


# ── Startseite ────────────────────────────────────────────────

@app.get('/')
def index():
    return redirect(url_for('artikel_liste'))


# ── Artikelliste ──────────────────────────────────────────────

@app.get('/wawi/artikel')
def artikel_liste():
    """Artikelliste mit Suche, Filter (Warengruppe/Lieferant) und Pagination."""
    seite          = int(request.args.get('seite', 1))
    suche          = request.args.get('q', '').strip()
    warengruppe_id = request.args.get('wg') or None
    lieferant_id   = request.args.get('lf') or None
    preisgruppe_id = int(request.args.get('pg', 1))

    if warengruppe_id:
        warengruppe_id = int(warengruppe_id)
    if lieferant_id:
        lieferant_id = int(lieferant_id)

    ergebnis    = pr.artikel_liste(
        seite=seite, suche=suche,
        warengruppe_id=warengruppe_id,
        lieferant_id=lieferant_id,
        preisgruppe_id=preisgruppe_id,
    )
    warengruppen = pr.warengruppen_liste()
    lieferanten  = pr.lieferanten_liste()
    preisgruppen = pr.preisgruppen_liste()

    return render_template(
        'artikel_liste.html',
        **ergebnis,
        warengruppen=warengruppen,
        lieferanten=lieferanten,
        preisgruppen=preisgruppen,
        filter_q=suche,
        filter_wg=warengruppe_id,
        filter_lf=lieferant_id,
        filter_pg=preisgruppe_id,
    )


# ── Preis-Editor ──────────────────────────────────────────────

@app.get('/wawi/artikel/<int:artikel_id>/preis')
def preis_editor(artikel_id: int):
    """Zeigt den Preis-Editor für einen Artikel."""
    art = pr.artikel_detail(artikel_id)
    if not art:
        flash('Artikel nicht gefunden.', 'error')
        return redirect(url_for('artikel_liste'))

    aktuelle_preise = pr.aktuelle_preise_artikel(artikel_id)
    preisgruppen    = pr.preisgruppen_liste()

    return render_template(
        'preis_editor.html',
        artikel=art,
        aktuelle_preise=_jsonify_rows(aktuelle_preise),
        preisgruppen=preisgruppen,
    )


@app.post('/wawi/artikel/<int:artikel_id>/preis')
def preis_speichern(artikel_id: int):
    """Speichert einen neuen Preis (INSERT in Preishistorie)."""
    art = pr.artikel_detail(artikel_id)
    if not art:
        return jsonify({'ok': False, 'fehler': 'Artikel nicht gefunden'}), 404

    d = request.get_json()
    preisgruppe_id  = int(d.get('preisgruppe_id', 1))
    ek_preis        = float(d['ek_preis']) if d.get('ek_preis') else None
    vk_preis        = float(d['vk_preis'])
    mwst_satz       = float(art['MWST_SATZ'])
    aenderungsgrund = d.get('aenderungsgrund', '').strip()

    if vk_preis <= 0:
        return jsonify({'ok': False, 'fehler': 'VK-Preis muss > 0 sein'}), 400

    try:
        neue_id = pr.preis_speichern(
            artikel_id=artikel_id,
            preisgruppe_id=preisgruppe_id,
            ek_preis=ek_preis,
            vk_preis=vk_preis,
            mwst_satz=mwst_satz,
            erstellt_von=_benutzer(),
            aenderungsgrund=aenderungsgrund,
        )
    except Exception as e:
        log.exception("Preis speichern fehlgeschlagen artikel_id=%d", artikel_id)
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    return jsonify({'ok': True, 'id': neue_id})


# ── Preishistorie ─────────────────────────────────────────────

@app.get('/wawi/artikel/<int:artikel_id>/historie')
def preishistorie(artikel_id: int):
    """Zeigt die Preishistorie eines Artikels."""
    art  = pr.artikel_detail(artikel_id)
    if not art:
        flash('Artikel nicht gefunden.', 'error')
        return redirect(url_for('artikel_liste'))

    tage           = int(request.args.get('tage', 90))
    preisgruppe_id = request.args.get('pg') or None
    if preisgruppe_id:
        preisgruppe_id = int(preisgruppe_id)

    historie     = pr.preishistorie_artikel(artikel_id, tage, preisgruppe_id)
    preisgruppen = pr.preisgruppen_liste()

    return render_template(
        'preishistorie.html',
        artikel=art,
        historie=_jsonify_rows(historie),
        preisgruppen=preisgruppen,
        filter_tage=tage,
        filter_pg=preisgruppe_id,
    )


@app.get('/wawi/artikel/<int:artikel_id>/historie/export')
def preishistorie_export(artikel_id: int):
    """Exportiert die Preishistorie als CSV-Download."""
    art = pr.artikel_detail(artikel_id)
    if not art:
        return 'Artikel nicht gefunden', 404

    tage     = int(request.args.get('tage', 365))
    historie = pr.preishistorie_artikel(artikel_id, tage)

    output = io.StringIO()
    output.write('Datum;Preisgruppe;EK netto;VK brutto;Marge %;MwSt %;Geändert von;Grund\n')
    for h in historie:
        output.write(
            f"{h['erstellt_am']};{h['preisgruppe_name']};"
            f"{str(h['ek_preis'] or '').replace('.', ',')};"
            f"{str(h['vk_preis']).replace('.', ',')};"
            f"{str(h['marge_prozent'] or '').replace('.', ',')};"
            f"{str(h['mwst_satz']).replace('.', ',')};"
            f"{h['erstellt_von']};{h['aenderungsgrund'] or ''}\n"
        )

    inhalt = output.getvalue().encode('utf-8-sig')
    return send_file(
        io.BytesIO(inhalt),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'preishistorie_{art["ART_NR"]}.csv',
    )


# ── Massenaktualisierung ──────────────────────────────────────

@app.get('/wawi/massenupdate')
def massenupdate_seite():
    """Zeigt das Massenupdate-Formular."""
    warengruppen = pr.warengruppen_liste()
    lieferanten  = pr.lieferanten_liste()
    preisgruppen = pr.preisgruppen_liste()
    return render_template(
        'massenaktualisierung.html',
        warengruppen=warengruppen,
        lieferanten=lieferanten,
        preisgruppen=preisgruppen,
    )


@app.post('/wawi/massenupdate/vorschau')
def massenupdate_vorschau():
    """Berechnet Vorher/Nachher ohne zu speichern (JSON)."""
    d              = request.get_json()
    prozent        = float(d.get('prozent', 0))
    warengruppe_id = int(d['warengruppe_id']) if d.get('warengruppe_id') else None
    lieferant_id   = int(d['lieferant_id'])   if d.get('lieferant_id')   else None
    preisgruppe_id = int(d.get('preisgruppe_id', 1))

    if not warengruppe_id and not lieferant_id:
        return jsonify({'ok': False, 'fehler': 'Warengruppe oder Lieferant erforderlich'}), 400

    vorschau = pr.massenupdate_vorschau(prozent, warengruppe_id, lieferant_id, preisgruppe_id)
    return jsonify({'ok': True, 'zeilen': vorschau, 'anzahl': len(vorschau)})


@app.post('/wawi/massenupdate/ausfuehren')
def massenupdate_ausfuehren():
    """Führt Massenupdate durch und speichert neue Preise."""
    d              = request.get_json()
    prozent        = float(d.get('prozent', 0))
    warengruppe_id = int(d['warengruppe_id']) if d.get('warengruppe_id') else None
    lieferant_id   = int(d['lieferant_id'])   if d.get('lieferant_id')   else None
    preisgruppe_id = int(d.get('preisgruppe_id', 1))

    if not warengruppe_id and not lieferant_id:
        return jsonify({'ok': False, 'fehler': 'Warengruppe oder Lieferant erforderlich'}), 400

    try:
        anzahl = pr.massenupdate_ausfuehren(
            prozent=prozent,
            warengruppe_id=warengruppe_id,
            lieferant_id=lieferant_id,
            preisgruppe_id=preisgruppe_id,
            erstellt_von=_benutzer(),
        )
    except Exception as e:
        log.exception("Massenupdate fehlgeschlagen")
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    return jsonify({'ok': True, 'aktualisiert': anzahl})


# ── CSV-Import ────────────────────────────────────────────────

@app.get('/wawi/import')
def csv_import_seite():
    """Zeigt das CSV-Import-Formular."""
    preisgruppen = pr.preisgruppen_liste()
    return render_template('csv_import.html', preisgruppen=preisgruppen)


@app.post('/wawi/import/vorschau')
def csv_import_vorschau():
    """Parst hochgeladene CSV-Datei und gibt Vorschau zurück."""
    if 'datei' not in request.files:
        return jsonify({'ok': False, 'fehler': 'Keine Datei hochgeladen'}), 400

    datei = request.files['datei']
    preisgruppe_id = int(request.form.get('preisgruppe_id', 1))

    try:
        inhalt   = datei.read()
        vorschau = pr.csv_import_vorschau(inhalt, preisgruppe_id)
    except Exception as e:
        log.exception("CSV-Vorschau fehlgeschlagen")
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    return jsonify({'ok': True, **vorschau, 'dateiname': datei.filename})


@app.post('/wawi/import/ausfuehren')
def csv_import_ausfuehren():
    """Führt validierten CSV-Import durch."""
    d              = request.get_json()
    zeilen         = d.get('zeilen', [])
    preisgruppe_id = int(d.get('preisgruppe_id', 1))
    dateiname      = d.get('dateiname', 'unbekannt.csv')

    if not zeilen:
        return jsonify({'ok': False, 'fehler': 'Keine Zeilen zum Importieren'}), 400

    try:
        ergebnis = pr.csv_import_ausfuehren(
            vorschau_zeilen=zeilen,
            preisgruppe_id=preisgruppe_id,
            dateiname=dateiname,
            erstellt_von=_benutzer(),
        )
    except Exception as e:
        log.exception("CSV-Import fehlgeschlagen")
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    return jsonify({'ok': True, **ergebnis})


# ── Preisgruppen-Verwaltung ───────────────────────────────────

@app.get('/wawi/preisgruppen')
def preisgruppen_seite():
    """Zeigt die Preisgruppen-Verwaltung."""
    from db import get_wawi_db
    with get_wawi_db() as cur:
        cur.execute("SELECT * FROM WAWI_PREISGRUPPEN ORDER BY id")
        preisgruppen = cur.fetchall()
    return render_template('preisgruppen.html', preisgruppen=preisgruppen)


@app.post('/wawi/preisgruppen')
def preisgruppe_erstellen():
    """Erstellt eine neue Preisgruppe."""
    from db import get_wawi_db
    name         = request.form.get('name', '').strip()
    beschreibung = request.form.get('beschreibung', '').strip()
    if not name:
        flash('Name ist erforderlich.', 'error')
        return redirect(url_for('preisgruppen_seite'))

    with get_wawi_db() as cur:
        cur.execute(
            "INSERT INTO WAWI_PREISGRUPPEN (name, beschreibung) VALUES (%s, %s)",
            (name, beschreibung)
        )
    flash(f'Preisgruppe „{name}" erstellt.', 'success')
    return redirect(url_for('preisgruppen_seite'))


# ── API: Preis-Berechnung (clientseitig validieren) ───────────

@app.get('/api/preis/berechne_vk')
def api_berechne_vk():
    """Berechnet VK brutto aus EK + Marge + MwSt."""
    ek    = float(request.args.get('ek', 0))
    marge = float(request.args.get('marge', 0))
    mwst  = float(request.args.get('mwst', 19))
    vk    = pr.berechne_vk(ek, marge, mwst)
    return jsonify({'vk': vk})


@app.get('/api/preis/berechne_marge')
def api_berechne_marge():
    """Berechnet Marge aus EK + VK + MwSt."""
    ek   = float(request.args.get('ek', 0))
    vk   = float(request.args.get('vk', 0))
    mwst = float(request.args.get('mwst', 19))
    marge = pr.berechne_marge(ek, vk, mwst)
    return jsonify({'marge': marge})


# ── CFO-Berichte ──────────────────────────────────────────────

def _parse_datum(s: str | None, fallback: date) -> date:
    """Parst YYYY-MM-DD oder gibt fallback zurück."""
    if s:
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass
    return fallback


@app.get('/wawi/berichte')
def berichte_seite():
    """Übersichtsseite CFO-Berichte."""
    return render_template('berichte.html')


# ── Tagesumsatz ────────────────────────────────────────────────

@app.get('/wawi/berichte/tagesumsatz')
def tagesumsatz_seite():
    """Tagesumsatz-Bericht (HTML)."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute)
    bis   = _parse_datum(request.args.get('bis'), heute)
    try:
        zeilen = bericht_modul.tagesumsatz(von, bis)
    except Exception as e:
        log.exception("Tagesumsatz-Fehler")
        zeilen = []
        flash(f'Datenbankfehler: {e}', 'error')
    return render_template('berichte.html', bericht='tagesumsatz',
                           zeilen=zeilen, von=von, bis=bis)


@app.get('/wawi/berichte/tagesumsatz/export')
def tagesumsatz_export():
    """Tagesumsatz als CSV."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute)
    bis   = _parse_datum(request.args.get('bis'), heute)
    inhalt = bericht_modul.tagesumsatz_csv(von, bis)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'tagesumsatz_{von}_{bis}.csv')


# ── Monatsübersicht ────────────────────────────────────────────

@app.get('/wawi/berichte/monatsuebersicht')
def monatsuebersicht_seite():
    """Monatsübersicht (HTML + Chart-Daten als JSON)."""
    jahr = int(request.args.get('jahr', date.today().year))
    try:
        zeilen = bericht_modul.monatsuebersicht(jahr)
        trend  = bericht_modul.monatstrend(jahr)
    except Exception as e:
        log.exception("Monatsübersicht-Fehler")
        zeilen = []
        trend  = []
        flash(f'Datenbankfehler: {e}', 'error')
    return render_template('berichte.html', bericht='monatsuebersicht',
                           zeilen=zeilen, trend=trend, jahr=jahr)


@app.get('/wawi/berichte/monatsuebersicht/export')
def monatsuebersicht_export():
    """Monatsübersicht als CSV."""
    jahr   = int(request.args.get('jahr', date.today().year))
    inhalt = bericht_modul.monatsuebersicht_csv(jahr)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'monatsuebersicht_{jahr}.csv')


# ── Kassenbuch ─────────────────────────────────────────────────

@app.get('/wawi/berichte/kassenbuch')
def kassenbuch_seite():
    """Kassenbuch-Bericht (HTML)."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute.replace(day=1))
    bis   = _parse_datum(request.args.get('bis'), heute)
    try:
        zeilen = bericht_modul.kassenbuch(von, bis)
    except Exception as e:
        log.exception("Kassenbuch-Fehler")
        zeilen = []
        flash(f'Datenbankfehler: {e}', 'error')
    return render_template('berichte.html', bericht='kassenbuch',
                           zeilen=zeilen, von=von, bis=bis)


@app.get('/wawi/berichte/kassenbuch/export')
def kassenbuch_export():
    """Kassenbuch als CSV."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute.replace(day=1))
    bis   = _parse_datum(request.args.get('bis'), heute)
    inhalt = bericht_modul.kassenbuch_csv(von, bis)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'kassenbuch_{von}_{bis}.csv')


# ── EC-Umsätze ─────────────────────────────────────────────────

@app.get('/wawi/berichte/ec-umsaetze')
def ec_umsaetze_seite():
    """EC-Umsätze-Bericht (HTML)."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute.replace(day=1))
    bis   = _parse_datum(request.args.get('bis'), heute)
    try:
        zeilen = bericht_modul.ec_umsaetze(von, bis)
    except Exception as e:
        log.exception("EC-Umsätze-Fehler")
        zeilen = []
        flash(f'Datenbankfehler: {e}', 'error')
    return render_template('berichte.html', bericht='ec_umsaetze',
                           zeilen=zeilen, von=von, bis=bis)


@app.get('/wawi/berichte/ec-umsaetze/export')
def ec_umsaetze_export():
    """EC-Umsätze als CSV."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute.replace(day=1))
    bis   = _parse_datum(request.args.get('bis'), heute)
    inhalt = bericht_modul.ec_umsaetze_csv(von, bis)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'ec_umsaetze_{von}_{bis}.csv')


# ── Admin ─────────────────────────────────────────────────────

@app.get('/wawi/admin')
def admin_seite():
    """Admin-Übersicht mit DB-Status."""
    verbindungen = db_modul.test_verbindungen()
    return render_template('admin.html', verbindungen=verbindungen, config=config)


# ── Start ─────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("CAO-XT WaWi-App startet auf %s:%d", config.HOST, config.PORT)
    status = db_modul.test_verbindungen()
    if not status['cao']:
        log.error("CAO-DB nicht erreichbar! config.py prüfen.")
    if not status['wawi']:
        log.error("WaWi-DB nicht erreichbar! config.py prüfen.")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
