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
    trainings_modus = False
    try:
        from db import get_db as _gdb
        with _gdb() as _cur:
            _cur.execute(
                "SELECT TRAININGS_MODUS FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                (config.TERMINAL_NR,)
            )
            _row = _cur.fetchone()
        trainings_modus = bool((_row or {}).get('TRAININGS_MODUS', 0))
    except Exception:
        pass
    return {
        'terminal_nr':    config.TERMINAL_NR,
        'firma_name':     config.FIRMA_NAME,
        'db_name':        config.DB_NAME,
        'jetzt':          datetime.now(),
        'trainings_modus': trainings_modus,
    }


# ── Auth-Hilfsfunktionen ──────────────────────────────────────
def _ist_eingeloggt() -> bool:
    return bool(session.get('ma_id'))


def _terminal_settings(terminal_nr: int) -> dict:
    """Liest Druck-Einstellungen des Terminals (QR-Code, Trainings-Modus)."""
    from db import get_db
    with get_db() as cur:
        cur.execute(
            "SELECT QR_CODE, TRAININGS_MODUS FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
            (terminal_nr,)
        )
        row = cur.fetchone() or {}
    return {
        'qr_code':        bool(row.get('QR_CODE', 0)),
        'trainings_modus': bool(row.get('TRAININGS_MODUS', 0)),
    }


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
    if obj is None:
        return None
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
    from db import get_db
    terminal_nr = config.TERMINAL_NR
    geparkt     = kl.geparkte_vorgaenge(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                    (terminal_nr,))
        terminal = cur.fetchone() or {}
    return render_template('kasse.html',
                           geparkte_vorgaenge=geparkt,
                           mwst_saetze=mwst_saetze,
                           terminal=terminal,
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
        wg_id=d.get('wg_id'),
        ep_original=int(d['ep_original']) if d.get('ep_original') else None,
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


@app.patch('/api/vorgang/<int:vid>/kunde')
@_login_required
def api_vorgang_kunde(vid):
    from db import get_db_transaction
    d = request.get_json() or {}
    with get_db_transaction() as cur:
        cur.execute(
            """UPDATE XT_KASSE_VORGAENGE
               SET KUNDEN_ID=%s, KUNDEN_NR=%s, KUNDEN_NAME=%s, KUNDEN_ORT=%s,
                   KUNDEN_PR_EBENE=%s
               WHERE ID=%s""",
            (d.get('kunden_id'), d.get('kunden_nr') or None,
             d.get('kunden_name') or None, d.get('kunden_ort') or None,
             d.get('kunden_pr_ebene') or None, vid)
        )
    return jsonify({'ok': True})


@app.patch('/api/vorgang/<int:vid>/notiz')
@_login_required
def api_vorgang_notiz(vid):
    from db import get_db_transaction
    notiz = (request.get_json() or {}).get('notiz', '')
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE SET NOTIZ=%s WHERE ID=%s",
            (notiz or None, vid)
        )
    return jsonify({'ok': True})


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
    """Bricht einen offenen Vorgang ab (GoBD: Soft-Delete, keine physische Löschung)."""
    import tse as tse_modul
    vorgang = kl.vorgang_laden(vid)
    if not vorgang or vorgang['STATUS'] != 'OFFEN':
        return jsonify({'ok': False, 'fehler': 'Vorgang nicht offen'}), 400
    # TSE-Transaktion canceln (falls bereits gestartet)
    if vorgang.get('TSE_TX_ID'):
        try:
            tse_modul.tse_cancel_transaktion(
                config.TERMINAL_NR, vid,
                vorgang['TSE_TX_ID'], vorgang['TSE_TX_REVISION']
            )
        except Exception as e:
            log.warning('TSE-Cancel bei Abbruch fehlgeschlagen (vid=%s): %s', vid, e)
    # GoBD §146 Abs. 4 AO: Keine physische Löschung – Status auf ABGEBROCHEN setzen
    from db import get_db_transaction
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE_POS SET STORNIERT=1 "
            "WHERE VORGANG_ID=%s AND STORNIERT=0",
            (vid,)
        )
        cur.execute(
            "UPDATE XT_KASSE_VORGAENGE "
            "SET STATUS='ABGEBROCHEN', ABGEBROCHEN_AM=NOW() "
            "WHERE ID=%s AND STATUS='OFFEN'",
            (vid,)
        )
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

    # Terminal-Einstellungen lesen
    from db import get_db as _get_db
    with _get_db() as cur:
        cur.execute(
            "SELECT SOFORT_DRUCKEN, SCHUBLADE_AUTO_OEFFNEN, KASSENLADE, "
            "QR_CODE, TRAININGS_MODUS "
            "FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s", (terminal_nr,)
        )
        t_cfg = cur.fetchone() or {}
    sofort_drucken         = bool(t_cfg.get('SOFORT_DRUCKEN', 1))
    schublade_auto_oeffnen = bool(t_cfg.get('SCHUBLADE_AUTO_OEFFNEN', 1))
    hat_kassenlade         = int(t_cfg.get('KASSENLADE', 0)) > 0
    qr_code                = bool(t_cfg.get('QR_CODE', 0))
    trainings_modus        = bool(t_cfg.get('TRAININGS_MODUS', 0))

    # Bon drucken (wenn Einstellung aktiv)
    try:
        positionen  = kl.vorgang_positionen(vid)
        zahl_rows   = kl.vorgang_zahlungen(vid)
        mwst_saetze = kl.mwst_saetze_laden()
        if sofort_drucken:
            druck.drucke_bon(vorgang, positionen, zahl_rows,
                             mwst_saetze, terminal_nr, qr_code=qr_code,
                             trainings_modus=trainings_modus)
        # Kassenlade öffnen wenn BAR-Zahlung und Einstellung aktiv
        if schublade_auto_oeffnen and hat_kassenlade and \
                any(z['zahlart'] == 'BAR' for z in zahlungen):
            druck.oeffne_kassenlade(terminal_nr)
    except Exception as e:
        log.warning("Bondruck fehlgeschlagen: %s", e)
        return jsonify({'ok': True, 'warnung': f'Druck fehlgeschlagen: {e}',
                        'vorgang_id': vid})

    return jsonify({'ok': True, 'vorgang_id': vid,
                    'bon_nr': vorgang['BON_NR']})


@app.post('/api/drucker/letzter-bon')
@_login_required
def api_letzter_bon():
    """Letzten abgeschlossenen Bon nochmal drucken (Kopie)."""
    from db import get_db
    with get_db() as cur:
        cur.execute(
            "SELECT ID FROM XT_KASSE_VORGAENGE "
            "WHERE TERMINAL_NR=%s AND STATUS='ABGESCHLOSSEN' "
            "ORDER BY ID DESC LIMIT 1",
            (config.TERMINAL_NR,)
        )
        row = cur.fetchone()
    if not row:
        return jsonify({'ok': False, 'fehler': 'Kein abgeschlossener Bon vorhanden'}), 404
    vid = row['ID']
    vorgang     = kl.vorgang_laden(vid)
    positionen  = kl.vorgang_positionen(vid)
    zahl_rows   = kl.vorgang_zahlungen(vid)
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        ts = _terminal_settings(config.TERMINAL_NR)
        druck.drucke_bon(vorgang, positionen, zahl_rows,
                         mwst_saetze, config.TERMINAL_NR, ist_kopie=True,
                         qr_code=ts['qr_code'],
                         trainings_modus=ts['trainings_modus'])
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True, 'bon_nr': vorgang['BON_NR']})


@app.post('/api/lade/oeffnen')
@_login_required
def api_lade_oeffnen():
    """Kassenlade manuell öffnen."""
    try:
        druck.oeffne_kassenlade(config.TERMINAL_NR)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


@app.post('/api/vorgang/<int:vid>/bon_nochmal')
@_login_required
def api_bon_nochmal(vid):
    vorgang    = kl.vorgang_laden(vid)
    positionen = kl.vorgang_positionen(vid)
    zahlungen  = kl.vorgang_zahlungen(vid)
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        ts = _terminal_settings(config.TERMINAL_NR)
        druck.drucke_bon(vorgang, positionen, zahlungen,
                         mwst_saetze, config.TERMINAL_NR, ist_kopie=True,
                         qr_code=ts['qr_code'],
                         trainings_modus=ts['trainings_modus'])
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
        ts = _terminal_settings(terminal_nr)
        druck.drucke_bon(storno_vorgang, positionen, zahl_rows,
                         mwst_saetze, terminal_nr, ist_storno=True,
                         qr_code=ts['qr_code'],
                         trainings_modus=ts['trainings_modus'])
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
    # 1. Normaler Artikel-Lookup
    art = kl.artikel_per_barcode(barcode)
    if art:
        return jsonify(art)
    # 2. Sonder-EAN (Zeitschrift / Preis-EAN / Gewichts-EAN)
    sonder = kl.ean_sonder_erkennen(barcode)
    if sonder:
        return jsonify(sonder)
    return jsonify(None), 404


# ── EAN-Regeln (Admin) ────────────────────────────────────────

@app.get('/api/ean-regeln')
@_login_required
def api_ean_regeln_liste():
    return jsonify(kl.ean_regeln_liste())


@app.post('/api/ean-regeln')
@_login_required
def api_ean_regel_speichern():
    d = request.get_json()
    rec_id = kl.ean_regel_speichern(
        praefix       = d['ean_praefix'].strip(),
        typ           = d['typ'],
        bezeichnung   = d['bezeichnung'].strip(),
        artikel_lookup = bool(d.get('artikel_lookup', False)),
        wg_id         = d.get('wg_id'),
        artikel_id    = d.get('artikel_id'),
        steuer_code   = int(d.get('steuer_code', 1)),
        preis_pro_kg  = int(d['preis_pro_kg']) if d.get('preis_pro_kg') else None,
    )
    return jsonify({'ok': True, 'rec_id': rec_id})


@app.delete('/api/ean-regeln/<int:rid>')
@_login_required
def api_ean_regel_loeschen(rid):
    kl.ean_regel_loeschen(rid)
    return jsonify({'ok': True})


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


@app.get('/api/kundengruppen')
@_login_required
def api_kundengruppen():
    from db import get_db
    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, NAME FROM ADRESSGRUPPEN "
            "WHERE DURCHSUCHEN='Y' ORDER BY NAME"
        )
        rows = cur.fetchall()
    return jsonify(_jsonify_rows(rows))


@app.get('/api/kunden/gruppe/<int:grp_id>')
@_login_required
def api_kunden_gruppe(grp_id):
    from db import get_db
    with get_db() as cur:
        if grp_id == -1:
            cur.execute(
                "SELECT REC_ID, NAME1, NAME2, ORT, KUNNUM1, KUNDENGRUPPE, PR_EBENE "
                "FROM ADRESSEN WHERE NAME1 != '' ORDER BY NAME1 LIMIT 300"
            )
        else:
            cur.execute(
                "SELECT REC_ID, NAME1, NAME2, ORT, KUNNUM1, KUNDENGRUPPE, PR_EBENE "
                "FROM ADRESSEN WHERE KUNDENGRUPPE=%s AND NAME1 != '' "
                "ORDER BY NAME1 LIMIT 300",
                (grp_id,)
            )
        rows = cur.fetchall()
    return jsonify(_jsonify_rows(rows))


@app.post('/api/vorgang/<int:vid>/neuberechnen')
@_login_required
def api_vorgang_neuberechnen(vid):
    """Preise aller Artikelpositionen auf neue Preisebene anpassen."""
    d = request.get_json() or {}
    pr_ebene = int(d.get('pr_ebene', 5))
    kl.vorgang_preise_neuberechnen(vid, pr_ebene)
    vorgang = kl.vorgang_laden(vid)
    positionen = kl.vorgang_positionen(vid)
    return jsonify({
        'ok': True,
        'betrag_brutto': vorgang['BETRAG_BRUTTO'],
        'positionen': _jsonify_rows(positionen),
    })


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
    try:
        tse_ok = tse_modul.tse_verfuegbar(terminal_nr)
    except Exception as _e:
        log.warning("tse_verfuegbar() fehlgeschlagen: %s", _e)
        tse_ok = False
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
        cur.execute("SELECT * FROM FIRMA LIMIT 1")
        firma = cur.fetchone() or {}

    # TSE-Detailstatus (live von Fiskaly, Fehler abfangen)
    tse_status = {}
    if tse_ok:
        try:
            tse_status = tse_modul.tse_tss_status(terminal_nr)
        except Exception:
            pass

    trainings_modus = bool((terminal or {}).get('TRAININGS_MODUS', 0))
    return render_template('admin/index.html',
                           db_ok=db_ok, tse_ok=tse_ok, drucker_ok=drucker_ok,
                           terminal=terminal or {},
                           firma=firma,
                           tse_status=tse_status,
                           trainings_modus=trainings_modus,
                           letzte_abschluesse=_jsonify_rows(letzte_abschluesse),
                           mitarbeiter=_mitarbeiter())


@app.get('/admin/terminal')
@_login_required
def admin_terminal():
    from db import get_db
    import tse as tse_modul
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
                    (config.TERMINAL_NR,))
        terminal = cur.fetchone() or {}
    # Aktive TSE laden (für Info-Anzeige)
    aktive_tse = None
    if terminal.get('TSE_ID'):
        try:
            aktive_tse = tse_modul.tse_geraet_laden(int(terminal['TSE_ID']))
        except Exception:
            pass
    return render_template('admin/terminal.html',
                           terminal=terminal,
                           aktive_tse=aktive_tse,
                           mitarbeiter=_mitarbeiter())


@app.post('/admin/terminal')
@_login_required
def admin_terminal_speichern():
    from db import get_db
    f = request.form
    tnr = config.TERMINAL_NR
    sofort_drucken         = 1 if f.get('sofort_drucken') else 0
    schublade_auto_oeffnen = 1 if f.get('schublade_auto_oeffnen') else 0
    qr_code                = 1 if f.get('qr_code') else 0
    trainings_modus        = 1 if f.get('trainings_modus') else 0
    with get_db() as cur:
        cur.execute(
            """INSERT INTO XT_KASSE_TERMINALS
               (TERMINAL_NR, BEZEICHNUNG,
                DRUCKER_IP, DRUCKER_PORT, KASSENLADE,
                SOFORT_DRUCKEN, SCHUBLADE_AUTO_OEFFNEN, QR_CODE, TRAININGS_MODUS,
                FIRMA_NAME, FIRMA_STRASSE, FIRMA_ORT,
                FIRMA_UST_ID, FIRMA_STEUERNUMMER)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
               BEZEICHNUNG=%s,
               DRUCKER_IP=%s, DRUCKER_PORT=%s, KASSENLADE=%s,
               SOFORT_DRUCKEN=%s, SCHUBLADE_AUTO_OEFFNEN=%s, QR_CODE=%s,
               TRAININGS_MODUS=%s,
               FIRMA_NAME=%s, FIRMA_STRASSE=%s, FIRMA_ORT=%s,
               FIRMA_UST_ID=%s, FIRMA_STEUERNUMMER=%s""",
            (tnr,
             f.get('bezeichnung', ''),
             f.get('drucker_ip', ''), int(f.get('drucker_port', 9100)),
             int(f.get('kassenlade', 0)),
             sofort_drucken, schublade_auto_oeffnen, qr_code, trainings_modus,
             f.get('firma_name', ''), f.get('firma_strasse', ''),
             f.get('firma_ort', ''), f.get('firma_ust_id', ''),
             f.get('firma_steuernummer', ''),
             # ON DUPLICATE KEY
             f.get('bezeichnung', ''),
             f.get('drucker_ip', ''), int(f.get('drucker_port', 9100)),
             int(f.get('kassenlade', 0)),
             sofort_drucken, schublade_auto_oeffnen, qr_code, trainings_modus,
             f.get('firma_name', ''), f.get('firma_strasse', ''),
             f.get('firma_ort', ''), f.get('firma_ust_id', ''),
             f.get('firma_steuernummer', ''))
        )
    import tse as tse_modul
    tse_modul._token_cache.pop(tnr, None)
    return redirect(url_for('admin_index'))


@app.post('/admin/terminal/trainings_modus')
@_login_required
def admin_trainings_modus():
    """Trainings-Modus für das Terminal ein- oder ausschalten."""
    import tse as tse_modul
    aktiv = request.form.get('trainings_modus') == '1'
    tse_modul.tse_trainings_modus_setzen(config.TERMINAL_NR, aktiv)
    session['tse_hinweis'] = (
        'Trainings-Modus aktiviert – Bons werden als TRAININGSBON gedruckt.'
        if aktiv else
        'Trainings-Modus deaktiviert – Bons werden mit echter TSE-Signatur erstellt.'
    )
    return redirect(url_for('admin_index'))


# ── TSE-Verwaltung ────────────────────────────────────────────

@app.get('/admin/tse')
@_login_required
def admin_tse_liste():
    import tse as tse_modul
    from db import get_db
    geraete = tse_modul.tse_geraete_liste()
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                    (config.TERMINAL_NR,))
        terminal = cur.fetchone() or {}
    return render_template('admin/tse.html',
                           geraete=_jsonify_rows(geraete),
                           terminal=terminal,
                           mitarbeiter=_mitarbeiter())


@app.get('/admin/tse/neu')
@_login_required
def admin_tse_neu():
    tse_id = request.args.get('edit')
    geraet = {}
    if tse_id:
        import tse as tse_modul
        geraet = tse_modul.tse_geraet_laden(int(float(tse_id))) or {}
    return render_template('admin/tse_form.html',
                           geraet=geraet,
                           mitarbeiter=_mitarbeiter())


@app.post('/admin/tse/neu')
@_login_required
def admin_tse_speichern():
    import tse as tse_modul
    f = request.form
    # PIN/PUK nur überschreiben wenn neu eingegeben
    rec_id = f.get('rec_id', '').strip()
    new_admin_pin = f.get('fiskaly_admin_pin', '').strip()
    new_admin_puk = f.get('fiskaly_admin_puk', '').strip()
    new_sw_pin    = f.get('swissbit_admin_pin', '').strip()
    new_sw_puk    = f.get('swissbit_admin_puk', '').strip()

    data = {
        'REC_ID':                  rec_id,
        'TYP':                     f.get('typ', 'FISKALY'),
        'BEZEICHNUNG':             f.get('bezeichnung', '').strip(),
        'BSI_ZERTIFIZIERUNG':      f.get('bsi_zertifizierung', '').strip(),
        'ZERTIFIKAT_GUELTIG_BIS':  f.get('zertifikat_gueltig_bis', '').strip() or None,
        'FISKALY_ENV':             f.get('fiskaly_env', 'test'),
        'FISKALY_API_KEY':         f.get('fiskaly_api_key', '').strip(),
        'FISKALY_API_SECRET':      f.get('fiskaly_api_secret', '').strip(),
        'FISKALY_TSS_ID':          f.get('fiskaly_tss_id', '').strip(),
        'FISKALY_ADMIN_PIN':       new_admin_pin,
        'FISKALY_ADMIN_PUK':       new_admin_puk,
        'SWISSBIT_PFAD':           f.get('swissbit_pfad', '').strip(),
        'SWISSBIT_ADMIN_PIN':      new_sw_pin,
        'SWISSBIT_ADMIN_PUK':      new_sw_puk,
        'IN_BETRIEB_SEIT':         f.get('in_betrieb_seit', '').strip() or None,
        'BEMERKUNG':               f.get('bemerkung', '').strip(),
    }
    try:
        neue_id = tse_modul.tse_geraet_speichern(data)
        session['tse_hinweis'] = f'TSE-Gerät gespeichert (ID {neue_id}).'
    except Exception as e:
        log.error("TSE-Gerät speichern fehlgeschlagen: %s", e)
        session['tse_fehler'] = f'Fehler: {e}'
    return redirect(url_for('admin_tse_liste'))


@app.post('/admin/tse/<int:tse_id>/aktivieren')
@_login_required
def admin_tse_aktivieren(tse_id: int):
    """Setzt die aktive TSE für das aktuelle Terminal."""
    import tse as tse_modul
    try:
        tse_modul.tse_geraet_aktivieren(config.TERMINAL_NR, tse_id)
        session['tse_hinweis'] = f'TSE-Gerät {tse_id} ist jetzt aktiv für Terminal {config.TERMINAL_NR}.'
    except Exception as e:
        session['tse_fehler'] = f'Fehler: {e}'
    return redirect(url_for('admin_tse_liste'))


@app.post('/admin/tse/<int:tse_id>/ausser_betrieb')
@_login_required
def admin_tse_ausser_betrieb(tse_id: int):
    """Setzt ein TSE-Gerät auf 'außer Betrieb' (Datum = heute)."""
    from db import get_db
    from datetime import date
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_TSE_GERAETE SET AUSSER_BETRIEB=%s WHERE REC_ID=%s",
            (date.today().isoformat(), tse_id)
        )
    session['tse_hinweis'] = f'TSE-Gerät {tse_id} als außer Betrieb markiert.'
    return redirect(url_for('admin_tse_liste'))


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
