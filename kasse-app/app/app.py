"""
CAO-XT Kassen-App – Flask-Hauptanwendung
Starten: cd kasse-app/app && python3 app.py
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_file, abort)
from datetime import datetime, date
import io
import json
import config
import db as db_modul
import kasse_logik as kl
import druck
import dsfinvk
import logging

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
        'terminal_nr':   config.TERMINAL_NR,
        'firma_name':    config.FIRMA_NAME,
        'jetzt':         datetime.now(),
    }


# ── Auth-Hilfsfunktionen ──────────────────────────────────────
def _ist_eingeloggt() -> bool:
    return bool(session.get('ma_id'))


def _mitarbeiter() -> dict:
    return {
        'MA_ID':       session.get('ma_id'),
        'LOGIN_NAME':  session.get('login_name'),
        'VNAME':       session.get('vname'),
        'NAME':        session.get('ma_name'),
    }


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _ist_eingeloggt():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def _serial(obj):
    """JSON-serialisierbares Dict/List."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if hasattr(obj, '__float__'):
        return float(obj)
    return str(obj)


def _jsonify_rows(rows):
    """Wandelt DB-Rows (mit Datetime-Feldern) in JSON-safe Dicts."""
    if isinstance(rows, list):
        return [{k: _serial(v) for k, v in row.items()} for row in rows]
    return {k: _serial(v) for k, v in rows.items()}


# ── Login / Logout ────────────────────────────────────────────

@app.get('/login')
def login():
    return render_template('login.html')


@app.post('/login')
def login_post():
    login_name = request.form.get('login_name', '').strip()
    passwort   = request.form.get('passwort', '')
    ma = kl.mitarbeiter_login(login_name, passwort)
    if ma:
        session['ma_id']      = ma['MA_ID']
        session['login_name'] = ma['LOGIN_NAME']
        session['vname']      = ma['VNAME']
        session['ma_name']    = ma['NAME']
        return redirect(url_for('kasse'))
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Hauptkasse ────────────────────────────────────────────────

@app.get('/')
def index():
    return redirect(url_for('kasse'))


@app.get('/kasse')
@_login_required
def kasse():
    terminal_nr = config.TERMINAL_NR
    geparkt     = kl.geparkte_vorgaenge(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('kasse.html',
                           geparkte_vorgaenge=geparkt,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


# ── API: Vorgang ──────────────────────────────────────────────

@app.post('/api/vorgang/neu')
@_login_required
def api_vorgang_neu():
    terminal_nr = config.TERMINAL_NR
    vorgang = kl.vorgang_neu(terminal_nr, _mitarbeiter())
    return jsonify({'ok': True, 'vorgang_id': vorgang['ID'],
                    'bon_nr': vorgang['BON_NR']})


@app.get('/api/vorgang/offen')
@_login_required
def api_vorgang_offen():
    """Gibt den aktuell offenen Vorgang dieses Terminals zurück (oder null)."""
    from db import get_db
    terminal_nr = config.TERMINAL_NR
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_VORGAENGE "
            "WHERE TERMINAL_NR=%s AND STATUS='OFFEN' ORDER BY ID DESC LIMIT 1",
            (terminal_nr,)
        )
        vorgang = cur.fetchone()
    if not vorgang:
        return jsonify({'vorgang': None, 'positionen': []})
    positionen = kl.vorgang_positionen(vorgang['ID'])
    return jsonify({
        'vorgang':    _jsonify_rows(vorgang),
        'positionen': _jsonify_rows(positionen),
    })


@app.get('/api/vorgang/<int:vid>')
@_login_required
def api_vorgang_laden(vid):
    vorgang    = kl.vorgang_laden(vid)
    positionen = kl.vorgang_positionen(vid)
    zahlungen  = kl.vorgang_zahlungen(vid)
    if not vorgang:
        abort(404)
    return jsonify({
        'vorgang':    _jsonify_rows(vorgang),
        'positionen': _jsonify_rows(positionen),
        'zahlungen':  _jsonify_rows(zahlungen),
    })


@app.post('/api/vorgang/<int:vid>/position')
@_login_required
def api_position_hinzufuegen(vid):
    d = request.get_json()
    result = kl.position_hinzufuegen(
        vorgang_id=vid,
        artikel_id=d.get('artikel_id'),
        bezeichnung=d['bezeichnung'],
        menge=float(d.get('menge', 1)),
        einzelpreis_brutto=int(d['einzelpreis_brutto']),
        steuer_code=int(d.get('steuer_code', 1)),
        rabatt_prozent=float(d.get('rabatt_prozent', 0)),
        ist_gutschein=bool(d.get('ist_gutschein', False)),
    )
    vorgang = kl.vorgang_laden(vid)
    return jsonify({'ok': True, 'pos_id': result['id'],
                    'betrag_brutto': vorgang['BETRAG_BRUTTO']})


@app.delete('/api/vorgang/<int:vid>/position/<int:pos_id>')
@_login_required
def api_position_entfernen(vid, pos_id):
    kl.position_entfernen(vid, pos_id)
    vorgang = kl.vorgang_laden(vid)
    return jsonify({'ok': True, 'betrag_brutto': vorgang['BETRAG_BRUTTO']})


@app.patch('/api/vorgang/<int:vid>/position/<int:pos_id>/menge')
@_login_required
def api_position_menge(vid, pos_id):
    d = request.get_json()
    kl.position_menge_aendern(vid, pos_id, float(d['menge']))
    vorgang = kl.vorgang_laden(vid)
    return jsonify({'ok': True, 'betrag_brutto': vorgang['BETRAG_BRUTTO']})


@app.post('/api/vorgang/<int:vid>/parken')
@_login_required
def api_vorgang_parken(vid):
    kl.vorgang_parken(vid)
    return jsonify({'ok': True})


@app.post('/api/vorgang/<int:vid>/entparken')
@_login_required
def api_vorgang_entparken(vid):
    kl.vorgang_entparken(vid)
    return jsonify({'ok': True})


@app.get('/api/geparkte')
@_login_required
def api_geparkte():
    rows = kl.geparkte_vorgaenge(config.TERMINAL_NR)
    return jsonify(_jsonify_rows(rows))


@app.post('/api/vorgang/<int:vid>/abbrechen')
@_login_required
def api_vorgang_abbrechen(vid):
    """Bricht einen offenen Vorgang ab (löscht alle Positionen, storniert TSE)."""
    import tse as tse_modul
    vorgang = kl.vorgang_laden(vid)
    if vorgang and vorgang.get('TSE_TX_ID') and vorgang['STATUS'] == 'OFFEN':
        tse_modul.tse_cancel_transaktion(
            config.TERMINAL_NR, vid,
            vorgang['TSE_TX_ID'], vorgang['TSE_TX_REVISION']
        )
    from db import get_db
    with get_db() as cur:
        cur.execute("DELETE FROM XT_KASSE_VORGAENGE_POS WHERE VORGANG_ID=%s", (vid,))
        cur.execute("DELETE FROM XT_KASSE_VORGAENGE WHERE ID=%s AND STATUS='OFFEN'", (vid,))
    return jsonify({'ok': True})


# ── Zahlung ───────────────────────────────────────────────────

@app.get('/kasse/zahlung/<int:vid>')
@_login_required
def zahlung_seite(vid):
    vorgang    = kl.vorgang_laden(vid)
    positionen = kl.vorgang_positionen(vid)
    if not vorgang or vorgang['STATUS'] != 'OFFEN':
        return redirect(url_for('kasse'))
    return render_template('zahlung.html',
                           vorgang=_jsonify_rows(vorgang),
                           positionen=_jsonify_rows(positionen),
                           mitarbeiter=_mitarbeiter())


@app.post('/api/vorgang/<int:vid>/zahlung')
@_login_required
def api_zahlung(vid):
    d = request.get_json()
    zahlungen = d.get('zahlungen', [])
    terminal_nr = config.TERMINAL_NR

    try:
        vorgang = kl.zahlung_abschliessen(vid, terminal_nr, zahlungen)
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    except Exception as e:
        log.exception("Zahlung fehlgeschlagen vid=%d", vid)
        return jsonify({'ok': False, 'fehler': 'Interner Fehler'}), 500

    # Bon drucken
    try:
        positionen  = kl.vorgang_positionen(vid)
        zahl_rows   = kl.vorgang_zahlungen(vid)
        mwst_saetze = kl.mwst_saetze_laden()
        druck.drucke_bon(vorgang, positionen, zahl_rows,
                         mwst_saetze, terminal_nr)
        # Kassenlade öffnen wenn BAR-Zahlung
        if any(z['zahlart'] == 'BAR' for z in zahlungen):
            druck.oeffne_kassenlade(terminal_nr)
    except Exception as e:
        log.warning("Bondruck fehlgeschlagen: %s", e)
        return jsonify({'ok': True, 'warnung': f'Druck fehlgeschlagen: {e}',
                        'vorgang_id': vid})

    return jsonify({'ok': True, 'vorgang_id': vid,
                    'bon_nr': vorgang['BON_NR']})


@app.post('/api/vorgang/<int:vid>/bon_nochmal')
@_login_required
def api_bon_nochmal(vid):
    vorgang    = kl.vorgang_laden(vid)
    positionen = kl.vorgang_positionen(vid)
    zahlungen  = kl.vorgang_zahlungen(vid)
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        druck.drucke_bon(vorgang, positionen, zahlungen,
                         mwst_saetze, config.TERMINAL_NR, ist_kopie=True)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


# ── Storno ────────────────────────────────────────────────────

@app.get('/kasse/journal')
@_login_required
def journal():
    return render_template('journal.html', mitarbeiter=_mitarbeiter(),
                           heute=date.today().isoformat())


@app.get('/kasse/storno')
def storno_redirect():
    return redirect(url_for('journal'))


@app.get('/api/vorgang/suche')
@_login_required
def api_vorgang_suche():
    bon_nr      = request.args.get('bon_nr', '')
    datum_von   = request.args.get('datum_von', date.today().isoformat())
    datum_bis   = request.args.get('datum_bis', date.today().isoformat())
    terminal_nr = config.TERMINAL_NR

    from db import get_db
    with get_db() as cur:
        bedingungen = ["v.TERMINAL_NR = %s", "DATE(v.BON_DATUM) BETWEEN %s AND %s",
                       "v.STATUS IN ('ABGESCHLOSSEN','STORNIERT')"]
        params = [terminal_nr, datum_von, datum_bis]
        if bon_nr:
            bedingungen.append("v.BON_NR = %s")
            params.append(int(bon_nr))
        cur.execute(
            f"SELECT v.ID, v.BON_NR, v.BON_DATUM, v.BETRAG_BRUTTO, "
            f"       v.STATUS, "
            f"       (SELECT GROUP_CONCAT(DISTINCT z.ZAHLART ORDER BY z.ZAHLART SEPARATOR '/') "
            f"        FROM XT_KASSE_ZAHLUNGEN z WHERE z.VORGANG_ID = v.ID) AS ZAHLARTEN "
            f"FROM XT_KASSE_VORGAENGE v "
            f"WHERE {' AND '.join(bedingungen)} ORDER BY v.BON_DATUM DESC LIMIT 100",
            params
        )
        rows = cur.fetchall()
    return jsonify(_jsonify_rows(rows))


@app.post('/api/vorgang/<int:vid>/kopieren')
@_login_required
def api_vorgang_kopieren(vid):
    """Neuen Bon mit identischen Positionen anlegen."""
    terminal_nr = config.TERMINAL_NR
    try:
        neuer = kl.vorgang_kopieren(vid, terminal_nr, _mitarbeiter())
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'vorgang_id': neuer['ID'], 'bon_nr': neuer['BON_NR']})


@app.post('/api/vorgang/<int:vid>/storno')
@_login_required
def api_storno(vid):
    terminal_nr = config.TERMINAL_NR
    try:
        storno_vorgang = kl.vorgang_stornieren(vid, terminal_nr, _mitarbeiter())
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400

    # Storno-Bon drucken
    try:
        positionen  = kl.vorgang_positionen(storno_vorgang['ID'])
        zahl_rows   = kl.vorgang_zahlungen(vid)
        mwst_saetze = kl.mwst_saetze_laden()
        druck.drucke_bon(storno_vorgang, positionen, zahl_rows,
                         mwst_saetze, terminal_nr, ist_storno=True)
    except Exception as e:
        log.warning("Storno-Bondruck fehlgeschlagen: %s", e)

    return jsonify({'ok': True, 'storno_id': storno_vorgang['ID']})


# ── Artikel-Suche ─────────────────────────────────────────────

@app.get('/api/artikel/suche')
@_login_required
def api_artikel_suche():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(kl.artikel_suchen(q))


@app.get('/api/artikel/barcode/<barcode>')
@_login_required
def api_artikel_barcode(barcode):
    art = kl.artikel_per_barcode(barcode)
    if not art:
        return jsonify(None), 404
    return jsonify(art)


@app.get('/api/schnelltasten')
@_login_required
def api_schnelltasten():
    return jsonify(kl.schnelltasten_laden())


# ── Kunden-Suche ─────────────────────────────────────────────

@app.get('/api/kunden/suche')
@_login_required
def api_kunden_suche():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    rows = kl.kunden_suchen(q)
    return jsonify(_jsonify_rows(rows))


# ── Kassenbuch ────────────────────────────────────────────────

@app.get('/kasse/kassenbuch')
@_login_required
def kassenbuch_seite():
    terminal_nr  = config.TERMINAL_NR
    eintraege    = kl.kassenbuch_heute(terminal_nr)
    saldo        = kl.kassenbuch_saldo(terminal_nr)
    return render_template('kassenbuch.html',
                           eintraege=_jsonify_rows(eintraege),
                           saldo=saldo,
                           mitarbeiter=_mitarbeiter())


@app.post('/api/kassenbuch')
@_login_required
def api_kassenbuch():
    d   = request.get_json()
    typ = d.get('typ', '').upper()
    if typ not in ('EINLAGE', 'ENTNAHME', 'ANFANGSBESTAND'):
        return jsonify({'ok': False, 'fehler': 'Ungültiger Typ'}), 400

    from db import euro_zu_cent
    betrag = int(d.get('betrag_cent', 0)) or euro_zu_cent(d.get('betrag', 0))
    kl.kassenbuch_eintrag(config.TERMINAL_NR, typ, betrag,
                          session['ma_id'], d.get('notiz', ''))
    saldo = kl.kassenbuch_saldo(config.TERMINAL_NR)
    return jsonify({'ok': True, 'saldo': saldo})


# ── X-Bon ─────────────────────────────────────────────────────

@app.get('/kasse/xbon')
@_login_required
def xbon_seite():
    terminal_nr = config.TERMINAL_NR
    daten       = kl.xbon_daten(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('xbon.html', daten=daten,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


@app.post('/api/xbon/drucken')
@_login_required
def api_xbon_drucken():
    terminal_nr = config.TERMINAL_NR
    daten       = kl.xbon_daten(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        druck.drucke_xbon(terminal_nr, daten, mwst_saetze)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


# ── Tagesabschluss ────────────────────────────────────────────

@app.get('/kasse/tagesabschluss')
@_login_required
def tagesabschluss_seite():
    terminal_nr = config.TERMINAL_NR
    daten       = kl.xbon_daten(terminal_nr)   # gleiche Zahlen, ohne Z-Bon zu erstellen
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('tagesabschluss.html', daten=daten,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


@app.post('/api/tagesabschluss')
@_login_required
def api_tagesabschluss():
    terminal_nr = config.TERMINAL_NR
    try:
        ta = kl.tagesabschluss_erstellen(terminal_nr, session['ma_id'])
    except Exception as e:
        log.exception("Tagesabschluss fehlgeschlagen")
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    mwst_saetze = kl.mwst_saetze_laden()
    try:
        druck.drucke_zbon(terminal_nr, ta, mwst_saetze)
    except Exception as e:
        log.warning("Z-Bon Druck fehlgeschlagen: %s", e)
        return jsonify({'ok': True, 'warnung': f'Druck fehlgeschlagen: {e}',
                        'z_nr': ta['Z_NR']})

    return jsonify({'ok': True, 'z_nr': ta['Z_NR']})


# ── Bon → Lieferschein ────────────────────────────────────────

@app.post('/api/vorgang/<int:vid>/lieferschein')
@_login_required
def api_zu_lieferschein(vid):
    d = request.get_json()
    adressen_id = d.get('adressen_id')
    if not adressen_id:
        return jsonify({'ok': False, 'fehler': 'Keine Kundenadresse angegeben'}), 400
    ma  = _mitarbeiter()
    name = f"{ma.get('VNAME','')} {ma.get('NAME','')}".strip()
    try:
        result = kl.vorgang_zu_lieferschein(vid, adressen_id, name)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, **result})


# ── Admin-Bereich ─────────────────────────────────────────────

@app.get('/admin/')
@_login_required
def admin_index():
    from db import get_db, test_verbindung
    import tse as tse_modul
    terminal_nr = config.TERMINAL_NR
    db_ok  = test_verbindung()
    tse_ok = tse_modul.tse_verfuegbar(terminal_nr)
    drucker_ok = druck.test_drucker(terminal_nr)

    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
                    (terminal_nr,))
        terminal = cur.fetchone()
        cur.execute(
            """SELECT * FROM XT_KASSE_TAGESABSCHLUSS WHERE TERMINAL_NR = %s
               ORDER BY ZEITPUNKT DESC LIMIT 5""",
            (terminal_nr,)
        )
        letzte_abschluesse = cur.fetchall()

    return render_template('admin/index.html',
                           db_ok=db_ok, tse_ok=tse_ok, drucker_ok=drucker_ok,
                           terminal=terminal or {},
                           letzte_abschluesse=_jsonify_rows(letzte_abschluesse),
                           mitarbeiter=_mitarbeiter())


@app.get('/admin/terminal')
@_login_required
def admin_terminal():
    from db import get_db
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
                    (config.TERMINAL_NR,))
        terminal = cur.fetchone() or {}
    return render_template('admin/terminal.html',
                           terminal=terminal,
                           mitarbeiter=_mitarbeiter())


@app.post('/admin/terminal')
@_login_required
def admin_terminal_speichern():
    from db import get_db
    f = request.form
    tnr = config.TERMINAL_NR
    with get_db() as cur:
        # PIN/PUK nur überschreiben wenn neu eingegeben
        new_pin = f.get('admin_pin', '').strip()
        new_puk = f.get('admin_puk', '').strip()
        cur.execute(
            """INSERT INTO XT_KASSE_TERMINALS
               (TERMINAL_NR, BEZEICHNUNG, FISKALY_API_KEY, FISKALY_API_SECRET,
                FISKALY_TSS_ID, FISKALY_CLIENT_ID, FISKALY_ENV,
                FISKALY_ADMIN_PIN, FISKALY_ADMIN_PUK,
                DRUCKER_IP, DRUCKER_PORT, KASSENLADE,
                FIRMA_NAME, FIRMA_STRASSE, FIRMA_ORT,
                FIRMA_UST_ID, FIRMA_STEUERNUMMER)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
               BEZEICHNUNG=%s, FISKALY_API_KEY=%s, FISKALY_API_SECRET=%s,
               FISKALY_TSS_ID=%s, FISKALY_CLIENT_ID=%s, FISKALY_ENV=%s,
               FISKALY_ADMIN_PIN=IF(%s != '', %s, FISKALY_ADMIN_PIN),
               FISKALY_ADMIN_PUK=IF(%s != '', %s, FISKALY_ADMIN_PUK),
               DRUCKER_IP=%s, DRUCKER_PORT=%s, KASSENLADE=%s,
               FIRMA_NAME=%s, FIRMA_STRASSE=%s, FIRMA_ORT=%s,
               FIRMA_UST_ID=%s, FIRMA_STEUERNUMMER=%s""",
            (tnr,
             f['bezeichnung'], f.get('api_key',''), f.get('api_secret',''),
             f.get('tss_id',''), f.get('client_id',''),
             f.get('fiskaly_env','test'), new_pin, new_puk,
             f.get('drucker_ip',''), int(f.get('drucker_port',9100)),
             int(f.get('kassenlade',0)),
             f.get('firma_name',''), f.get('firma_strasse',''),
             f.get('firma_ort',''), f.get('firma_ust_id',''),
             f.get('firma_steuernummer',''),
             # ON DUPLICATE KEY
             f['bezeichnung'], f.get('api_key',''), f.get('api_secret',''),
             f.get('tss_id',''), f.get('client_id',''),
             f.get('fiskaly_env','test'),
             new_pin, new_pin,
             new_puk, new_puk,
             f.get('drucker_ip',''), int(f.get('drucker_port',9100)),
             int(f.get('kassenlade',0)),
             f.get('firma_name',''), f.get('firma_strasse',''),
             f.get('firma_ort',''), f.get('firma_ust_id',''),
             f.get('firma_steuernummer',''))
        )
    # Token-Cache invalidieren nach Konfigurationsänderung
    import tse as tse_modul
    tse_modul._token_cache.pop(tnr, None)

    # Client automatisch registrieren, wenn API-Key + TSS-ID vorhanden,
    # aber noch keine Client-ID eingetragen wurde
    if (f.get('api_key') and f.get('tss_id') and not f.get('client_id')):
        try:
            new_client_id = tse_modul.tse_client_registrieren(tnr)
            session['tse_hinweis'] = f'Fiskaly-Client automatisch angelegt: {new_client_id}'
        except Exception as e:
            log.error("Fiskaly Client-Registrierung fehlgeschlagen: %s", e)
            session['tse_fehler'] = f'Client-Registrierung fehlgeschlagen: {e}'

    return redirect(url_for('admin_index'))


@app.get('/admin/export')
@_login_required
def admin_export():
    return render_template('admin/export.html', mitarbeiter=_mitarbeiter())


@app.post('/admin/export/starten')
@_login_required
def admin_export_starten():
    datum_von = request.form['datum_von']
    datum_bis = request.form['datum_bis']
    terminal_nr = config.TERMINAL_NR
    try:
        result = dsfinvk.dsfinvk_export_starten(terminal_nr, datum_von, datum_bis)
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})


@app.get('/admin/export/status/<export_id>')
@_login_required
def admin_export_status(export_id):
    try:
        status = dsfinvk.dsfinvk_export_status(config.TERMINAL_NR, export_id)
        return jsonify(status)
    except Exception as e:
        return jsonify({'state': 'ERROR', 'fehler': str(e)})


@app.get('/admin/export/download/<export_id>')
@_login_required
def admin_export_download(export_id):
    try:
        inhalt = dsfinvk.dsfinvk_export_herunterladen(config.TERMINAL_NR, export_id)
        return send_file(
            io.BytesIO(inhalt),
            mimetype='application/x-tar',
            as_attachment=True,
            download_name=f'dsfinvk_{export_id}.tar'
        )
    except Exception as e:
        return str(e), 500


@app.get('/admin/export/lokal')
@_login_required
def admin_export_lokal():
    datum_von = request.args.get('von', date.today().isoformat())
    datum_bis = request.args.get('bis', date.today().isoformat())
    daten = dsfinvk.lokale_export_daten(config.TERMINAL_NR, datum_von, datum_bis)
    return jsonify(daten)


@app.post('/admin/drucker/test')
@_login_required
def admin_drucker_test():
    ok = druck.test_drucker(config.TERMINAL_NR)
    if ok:
        # Testseite senden
        from db import get_db
        import socket
        try:
            with get_db() as cur:
                cur.execute(
                    "SELECT DRUCKER_IP, DRUCKER_PORT FROM XT_KASSE_TERMINALS "
                    "WHERE TERMINAL_NR = %s", (config.TERMINAL_NR,)
                )
                row = cur.fetchone()
            if row:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((row['DRUCKER_IP'], row['DRUCKER_PORT']))
                sock.sendall(
                    b'\x1b\x40'                          # Reset
                    b'\x1b\x61\x01'                      # zentriert
                    b'\x1b\x45\x01'                      # Fett
                    b'CAO-XT Kassen-App\n'
                    b'\x1b\x45\x00'
                    b'Druckertest erfolgreich!\n'
                    b'\n\n\n\n\n\n'
                    b'\x1d\x56\x01'                      # Schnitt
                )
                sock.close()
        except Exception:
            pass
    return jsonify({'ok': ok})


# ── Tagesabschluss-Übersicht ──────────────────────────────────

@app.get('/kasse/abschluesse')
@_login_required
def abschluesse_seite():
    from db import get_db
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_TAGESABSCHLUSS
               WHERE TERMINAL_NR = %s
               ORDER BY DATUM DESC LIMIT 30""",
            (config.TERMINAL_NR,)
        )
        rows = cur.fetchall()
    return render_template('abschluesse.html',
                           abschluesse=_jsonify_rows(rows),
                           mitarbeiter=_mitarbeiter())


@app.post('/api/tagesabschluss/<int:ta_id>/drucken')
@_login_required
def api_zbon_nochmal(ta_id):
    from db import get_db
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TAGESABSCHLUSS WHERE ID=%s", (ta_id,))
        ta = cur.fetchone()
    if not ta:
        return jsonify({'ok': False, 'fehler': 'Nicht gefunden'}), 404
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        druck.drucke_zbon(config.TERMINAL_NR, ta, mwst_saetze)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


# ── Start ─────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("CAO-XT Kassen-App startet auf %s:%d (Terminal %d)",
             config.HOST, config.PORT, config.TERMINAL_NR)
    if not db_modul.test_verbindung():
        log.error("Datenbankverbindung fehlgeschlagen! Bitte config.py prüfen.")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
