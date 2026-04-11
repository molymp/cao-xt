"""
CAO-XT Kassen-App – Flask-Hauptanwendung
Starten: cd kasse-app/app && python3 app.py
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_file, abort,
                   send_from_directory)
from functools import wraps
from datetime import datetime, date
import io
import json
import os
import base64
import subprocess
import sys
import threading
import time
import config
import db as db_modul
from db import get_db, get_db_transaction, euro_zu_cent, test_verbindung
import kasse_logik as kl
import druck
import dsfinvk
import tse as tse_modul
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False

# Schema-Migrationen beim Start ausführen (inkl. virtuelle Terminal-Nummer falls Sandbox-Modus)
kl.migrationen_ausfuehren()


# ── GitHub-Update-Prüfung ─────────────────────────────────────

def _find_git_root() -> str | None:
    """Sucht das .git-Verzeichnis/-Datei ab app/ aufwärts (max. 6 Ebenen).
    Unterstützt normale Repos und Git-Worktrees (.git als Datei)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        git_path = os.path.join(d, ".git")
        if os.path.isdir(git_path) or os.path.isfile(git_path):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None

GIT_ROOT = _find_git_root()

# Ältester Commit, der die Update-/Rollback-Funktion bereits enthält.
# Rollback auf ältere Versionen wird nicht angeboten.
ROLLBACK_MIN_COMMIT = "1d3cb33"

_update_status: dict = {
    "verfuegbar":    False,
    "local_hash":    None,
    "local_short":   None,
    "local_msg":     None,
    "remote_hash":   None,
    "letzter_check": None,
    "fehler":        None,
}


def _git(args: list[str], timeout: int = 25) -> str:
    """Führt einen git-Befehl in GIT_ROOT aus und gibt stdout zurück."""
    if not GIT_ROOT:
        raise RuntimeError("Kein Git-Repository gefunden")
    r = subprocess.run(
        ["git"] + args,
        cwd=GIT_ROOT, capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    return r.stdout.strip()


try:
    GIT_COMMIT_SHORT = _git(["rev-parse", "--short", "HEAD"]) if GIT_ROOT else ""
except Exception:
    GIT_COMMIT_SHORT = ""


def _pruefe_update_loop():
    """Hintergrund-Daemon: prüft alle 10 Minuten auf neue Commits in origin/master."""
    while True:
        try:
            _git(["fetch", "origin", "master"])
            local  = _git(["rev-parse", "HEAD"])
            remote = _git(["rev-parse", "origin/master"])
            info   = _git(["log", "-1", "--format=%h|%s", "HEAD"]).split("|", 1)
            # Nur "verfügbar" wenn origin/master Commits hat, die lokal fehlen.
            incoming = int(_git(["rev-list", "--count", "HEAD..origin/master"]))
            _update_status.update({
                "verfuegbar":    incoming > 0,
                "local_hash":    local,
                "local_short":   info[0] if info else local[:7],
                "local_msg":     info[1] if len(info) > 1 else "",
                "remote_hash":   remote,
                "letzter_check": datetime.now().strftime("%H:%M"),
                "fehler":        None,
            })
        except Exception as exc:
            _update_status["fehler"] = str(exc)
            _update_status["letzter_check"] = datetime.now().strftime("%H:%M")
        time.sleep(600)   # 10 Minuten


threading.Thread(target=_pruefe_update_loop, daemon=True, name="update-checker").start()

# ── Context-Processor ─────────────────────────────────────────
@app.context_processor
def _globals():
    trainings_modus     = False
    tse_nicht_produktiv = False
    ec_modus            = 'manuell'
    ec_tagesabschluss   = 'manuell'
    try:
        ts = _terminal_settings(config.TERMINAL_NR)
        trainings_modus     = ts['trainings_modus']
        tse_nicht_produktiv = ts['tse_nicht_produktiv']
        ec_modus            = ts['ec_modus']
        ec_tagesabschluss   = ts['ec_tagesabschluss']
    except Exception:
        pass
    return {
        'terminal_nr':         config.TERMINAL_NR,
        'firma_name':          config.FIRMA_NAME,
        'db_name':             config.DB_NAME,
        'jetzt':               datetime.now(),
        'trainings_modus':     trainings_modus,
        'tse_nicht_produktiv': tse_nicht_produktiv,
        'ec_modus':            ec_modus,
        'ec_tagesabschluss':   ec_tagesabschluss,
        'kiosk_url':           config.KIOSK_URL or (
                                   f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
                                   if config.KIOSK_PORT else ''),
        'wawi_url':            config.WAWI_URL or (
                                   f'{request.scheme}://{request.host.split(":")[0]}:{config.WAWI_PORT}'
                                   if config.WAWI_PORT else ''),
        'ma_login_name':       session.get('login_name', ''),
        'update_verfuegbar':   _update_status["verfuegbar"],
        'git_commit_short':    GIT_COMMIT_SHORT,
    }


# ── Auth-Hilfsfunktionen ──────────────────────────────────────
def _ist_eingeloggt() -> bool:
    return bool(session.get('ma_id'))


def _terminal_settings(terminal_nr: int) -> dict:
    """Liest Terminal-Einstellungen inkl. TSE-Typ aus XT_KASSE_TERMINALS + XT_KASSE_TSE_GERAETE."""
    with get_db() as cur:
        cur.execute(
            """SELECT t.QR_CODE, t.TRAININGS_MODUS, t.SOFORT_DRUCKEN,
                      t.SCHUBLADE_AUTO_OEFFNEN, t.KASSENLADE,
                      t.EC_MODUS, t.EC_TERMINAL_IP, t.EC_TERMINAL_PORT,
                      t.EC_TAGESABSCHLUSS,
                      g.TYP AS TSE_TYP, g.FISKALY_ENV
               FROM XT_KASSE_TERMINALS t
               LEFT JOIN XT_KASSE_TSE_GERAETE g ON g.REC_ID = t.TSE_ID
               WHERE t.TERMINAL_NR = %s""",
            (terminal_nr,)
        )
        row = cur.fetchone() or {}
    tse_typ     = (row.get('TSE_TYP') or '').upper()
    fiskaly_env = (row.get('FISKALY_ENV') or '').lower()
    # Nicht-produktiv: Fiskaly-Test/Sandbox oder DEMO-TSE
    tse_nicht_produktiv = (
        (tse_typ == 'FISKALY' and fiskaly_env != 'live') or
        tse_typ == 'DEMO'
    )
    return {
        'qr_code':                bool(row.get('QR_CODE', 0)),
        'trainings_modus':        bool(row.get('TRAININGS_MODUS', 0)),
        'sofort_drucken':         bool(row.get('SOFORT_DRUCKEN', 1)),
        'schublade_auto_oeffnen': bool(row.get('SCHUBLADE_AUTO_OEFFNEN', 1)),
        'kassenlade':             int(row.get('KASSENLADE', 0)) > 0,
        'tse_nicht_produktiv':    tse_nicht_produktiv,
        # EC-Terminal
        'ec_modus':               (row.get('EC_MODUS') or 'manuell').lower(),
        'ec_terminal_ip':         row.get('EC_TERMINAL_IP') or '',
        'ec_terminal_port':       int(row.get('EC_TERMINAL_PORT') or 20007),
        'ec_tagesabschluss':      (row.get('EC_TAGESABSCHLUSS') or 'manuell').lower(),
        'ec_zvt_passwort':        row.get('EC_ZVT_PASSWORT') or '010203',
    }


def _eff_terminal_nr() -> int:
    """Effektive Terminal-Nummer für DB-Operationen.
    Im Trainings-/Sandbox-Modus wird terminal_nr + 10000 verwendet,
    damit Live- und Trainingsdaten vollständig getrennt in denselben Tabellen liegen.
    Die echte Terminal-Nummer (config.TERMINAL_NR) wird nur für Anzeige/Druck verwendet."""
    ts = _terminal_settings(config.TERMINAL_NR)
    if ts['trainings_modus'] or ts['tse_nicht_produktiv']:
        return config.TERMINAL_NR + 10000
    return config.TERMINAL_NR


def _mitarbeiter() -> dict:
    return {
        'MA_ID':       session.get('ma_id'),
        'LOGIN_NAME':  session.get('login_name'),
        'VNAME':       session.get('vname'),
        'NAME':        session.get('ma_name'),
    }


def _login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _ist_eingeloggt():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def _bon_drucken(vid: int, *, ist_kopie: bool = False, ist_storno: bool = False,
                 vorgang=None, positionen=None, zahlungen=None):
    """
    Lädt alle Bon-Daten (wenn nicht übergeben) und druckt den Bon.
    Gibt den Vorgang zurück. Wirft Exception bei Druckfehler.
    """
    if vorgang    is None: vorgang    = kl.vorgang_laden(vid)
    if positionen is None: positionen = kl.vorgang_positionen(vid)
    if zahlungen  is None: zahlungen  = kl.vorgang_zahlungen(vid)
    mwst_saetze = kl.mwst_saetze_laden()
    ts = _terminal_settings(config.TERMINAL_NR)
    druck.drucke_bon(vorgang, positionen, zahlungen,
                     mwst_saetze, config.TERMINAL_NR,
                     ist_kopie=ist_kopie, ist_storno=ist_storno,
                     qr_code=ts['qr_code'],
                     trainings_modus=ts['trainings_modus'],
                     nicht_produktiv=ts['tse_nicht_produktiv'])
    return vorgang


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
    terminal_nr = _eff_terminal_nr()
    geparkt     = kl.geparkte_vorgaenge(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                    (config.TERMINAL_NR,))
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
    terminal_nr = _eff_terminal_nr()
    vorgang = kl.vorgang_neu(terminal_nr, _mitarbeiter())
    return jsonify({'ok': True, 'vorgang_id': vorgang['ID'],
                    'bon_nr': vorgang['BON_NR']})


@app.get('/api/vorgang/offen')
@_login_required
def api_vorgang_offen():
    """Gibt den aktuell offenen Vorgang dieses Terminals zurück (oder null)."""
    terminal_nr = _eff_terminal_nr()
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
    rows = kl.geparkte_vorgaenge(_eff_terminal_nr())
    return jsonify(_jsonify_rows(rows))


@app.post('/api/vorgang/<int:vid>/abbrechen')
@_login_required
def api_vorgang_abbrechen(vid):
    """Bricht einen offenen Vorgang ab (GoBD: Soft-Delete, keine physische Löschung)."""
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
    terminal_nr = _eff_terminal_nr()

    try:
        vorgang = kl.zahlung_abschliessen(vid, terminal_nr, zahlungen)
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    except Exception as e:
        log.exception("Zahlung fehlgeschlagen vid=%d", vid)
        return jsonify({'ok': False, 'fehler': 'Interner Fehler'}), 500

    # Terminal-Einstellungen, Bon drucken, Kassenlade öffnen
    try:
        ts = _terminal_settings(config.TERMINAL_NR)
        if ts['sofort_drucken']:
            _bon_drucken(vid, vorgang=vorgang)
        if ts['schublade_auto_oeffnen'] and ts['kassenlade'] and \
                any(z['zahlart'] == 'BAR' for z in zahlungen):
            druck.oeffne_kassenlade(config.TERMINAL_NR)
    except Exception as e:
        log.warning("Bondruck fehlgeschlagen: %s", e)
        return jsonify({'ok': True, 'warnung': f'Druck fehlgeschlagen: {e}',
                        'vorgang_id': vid})

    return jsonify({'ok': True, 'vorgang_id': vid,
                    'bon_nr': vorgang['BON_NR']})


@app.post('/api/drucker/letzter-bon')
@_login_required
def api_letzter_bon():
    """Letzten abgeschlossenen Bon nochmal drucken (Kopie).

    Bei einem Lieferschein-Vorgang wird das Lieferscheinlayout verwendet
    (ohne Preise, mit Unterschriftszeile); sonst der normale Kassenbon.
    """
    with get_db() as cur:
        cur.execute(
            "SELECT ID, BON_NR, VORGANG_TYP, ADRESSEN_ID FROM XT_KASSE_VORGAENGE "
            "WHERE TERMINAL_NR=%s AND STATUS='ABGESCHLOSSEN' "
            "ORDER BY ID DESC LIMIT 1",
            (_eff_terminal_nr(),)
        )
        row = cur.fetchone()
    if not row:
        return jsonify({'ok': False, 'fehler': 'Kein abgeschlossener Bon vorhanden'}), 404

    try:
        if (row.get('VORGANG_TYP') or '') == 'Lieferschein':
            adressen_id = int(row.get('ADRESSEN_ID') or 0)
            druck.drucke_lieferschein_bon(config.TERMINAL_NR, row['ID'], adressen_id)
            return jsonify({'ok': True, 'bon_nr': row['BON_NR']})
        vorgang = _bon_drucken(row['ID'], ist_kopie=True)
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
    try:
        _bon_drucken(vid, ist_kopie=True)
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
    terminal_nr = _eff_terminal_nr()

    with get_db() as cur:
        # Datum-Filter auf ABSCHLUSS_DATUM (Zahlungszeitpunkt), nicht BON_DATUM (Erstellzeit).
        # Fallback auf BON_DATUM für Altdaten ohne ABSCHLUSS_DATUM.
        bedingungen = [
            "v.TERMINAL_NR = %s",
            "DATE(COALESCE(v.ABSCHLUSS_DATUM, v.BON_DATUM)) BETWEEN %s AND %s",
            "v.STATUS IN ('ABGESCHLOSSEN','STORNIERT')",
        ]
        params = [terminal_nr, datum_von, datum_bis]
        if bon_nr:
            bedingungen.append("v.BON_NR = %s")
            params.append(int(bon_nr))
        cur.execute(
            f"SELECT v.ID, v.BON_NR, v.BON_DATUM, v.ABSCHLUSS_DATUM, v.BETRAG_BRUTTO, v.IST_TRAINING, "
            f"       v.STATUS, v.STORNO_VON_ID, "
            f"       (SELECT BON_NR FROM XT_KASSE_VORGAENGE "
            f"        WHERE ID = v.STORNO_VON_ID) AS STORNO_VON_BON_NR, "
            f"       (SELECT BON_NR FROM XT_KASSE_VORGAENGE "
            f"        WHERE STORNO_VON_ID = v.ID LIMIT 1) AS STORNIERT_DURCH_BON_NR, "
            f"       (SELECT GROUP_CONCAT(DISTINCT z.ZAHLART ORDER BY z.ZAHLART SEPARATOR '/') "
            f"        FROM XT_KASSE_ZAHLUNGEN z WHERE z.VORGANG_ID = v.ID) AS ZAHLARTEN, "
            f"       (SELECT ta.Z_NR FROM XT_KASSE_TAGESABSCHLUSS ta "
            f"        WHERE ta.TERMINAL_NR = v.TERMINAL_NR "
            f"          AND ta.ZEITPUNKT >= COALESCE(v.ABSCHLUSS_DATUM, v.BON_DATUM) "
            f"        ORDER BY ta.ZEITPUNKT ASC LIMIT 1) AS Z_BON_NR "
            f"FROM XT_KASSE_VORGAENGE v "
            f"WHERE {' AND '.join(bedingungen)} "
            f"ORDER BY COALESCE(v.ABSCHLUSS_DATUM, v.BON_DATUM) DESC LIMIT 100",
            params
        )
        rows = cur.fetchall()
    return jsonify(_jsonify_rows(rows))


@app.post('/api/vorgang/<int:vid>/kopieren')
@_login_required
def api_vorgang_kopieren(vid):
    """Neuen Bon mit identischen Positionen anlegen."""
    terminal_nr = _eff_terminal_nr()
    try:
        neuer = kl.vorgang_kopieren(vid, terminal_nr, _mitarbeiter())
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    return jsonify({'ok': True, 'vorgang_id': neuer['ID'], 'bon_nr': neuer['BON_NR']})


@app.post('/api/vorgang/<int:vid>/storno')
@_login_required
def api_storno(vid):
    terminal_nr = _eff_terminal_nr()
    try:
        storno_vorgang = kl.vorgang_stornieren(vid, terminal_nr, _mitarbeiter())
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400

    # Storno-Bon drucken
    try:
        positionen  = kl.vorgang_positionen(storno_vorgang['ID'])
        zahl_rows   = kl.vorgang_zahlungen(vid)
        mwst_saetze = kl.mwst_saetze_laden()
        ts = _terminal_settings(config.TERMINAL_NR)
        druck.drucke_bon(storno_vorgang, positionen, zahl_rows,
                         mwst_saetze, config.TERMINAL_NR, ist_storno=True,
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


@app.get('/api/artikel/warengruppen')
@_login_required
def api_artikel_warengruppen():
    return jsonify(kl.warengruppen_alle_laden())


@app.get('/api/artikel/browser')
@_login_required
def api_artikel_browser():
    wg = request.args.get('wg', '').strip()
    wg_id = int(wg) if wg.isdigit() else None
    return jsonify(kl.artikel_nach_warengruppe(wg_id))


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
    with get_db() as cur:
        if grp_id == -1:
            cur.execute(
                """SELECT a.REC_ID, a.NAME1, a.NAME2, a.ORT, a.KUNNUM1,
                          a.KUNDENGRUPPE, a.PR_EBENE,
                          a.KUN_ZAHLART, za.NAME AS ZAHLART_NAME
                   FROM ADRESSEN a
                   LEFT JOIN ZAHLUNGSARTEN za ON za.REC_ID = a.KUN_ZAHLART
                   WHERE a.NAME1 != '' ORDER BY a.NAME1 LIMIT 300"""
            )
        else:
            cur.execute(
                """SELECT a.REC_ID, a.NAME1, a.NAME2, a.ORT, a.KUNNUM1,
                          a.KUNDENGRUPPE, a.PR_EBENE,
                          a.KUN_ZAHLART, za.NAME AS ZAHLART_NAME
                   FROM ADRESSEN a
                   LEFT JOIN ZAHLUNGSARTEN za ON za.REC_ID = a.KUN_ZAHLART
                   WHERE a.KUNDENGRUPPE=%s AND a.NAME1 != ''
                   ORDER BY a.NAME1 LIMIT 300""",
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
    terminal_nr = _eff_terminal_nr()
    eintraege   = kl.kassenbuch_liste(terminal_nr, kasse='HAUPT', tage=30)
    info        = kl.kassenbuch_info(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('kassenbuch.html',
                           eintraege=_jsonify_rows(eintraege),
                           info=info,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


@app.get('/kasse/kassenbuch/buchung')
@_login_required
def kassenbuch_buchung_seite():
    terminal_nr = _eff_terminal_nr()
    info        = kl.kassenbuch_info(terminal_nr)
    # mwst_saetze_laden() → {code: satz_float}; Template erwartet Liste mit .CODE/.SATZ
    mwst_saetze = [{'CODE': k, 'SATZ': v}
                   for k, v in sorted(kl.mwst_saetze_laden().items())]
    naechste_nr      = kl.kassenbuch_belegnummer_naechste(terminal_nr)
    min_datum        = kl.letzter_abschluss_datum(terminal_nr)
    fibu_bankkonten  = kl.fibu_konten_laden(kontoart=20)   # Bankkonten
    fibu_kassenkonten = kl.fibu_konten_laden(kontoart=3)   # Kassenkonten
    from datetime import date as _date
    return render_template('kassenbuch_buchung.html',
                           info=info,
                           mwst_saetze=mwst_saetze,
                           fibu_bankkonten=fibu_bankkonten,
                           fibu_kassenkonten=fibu_kassenkonten,
                           naechste_belegnummer=naechste_nr,
                           min_datum=min_datum.isoformat() if min_datum else None,
                           heute=_date.today().isoformat(),
                           mitarbeiter=_mitarbeiter())


@app.post('/api/kassenbuch')
@_login_required
def api_kassenbuch():
    d           = request.get_json()
    typ         = (d.get('typ') or '').upper()
    betrag_cent = int(d.get('betrag_cent', 0)) or euro_zu_cent(d.get('betrag', 0))

    if not betrag_cent or betrag_cent <= 0:
        return jsonify({'ok': False, 'fehler': 'Betrag muss größer 0 sein'}), 400

    # Überschuss-Prüfung: Entnahmen dürfen den Saldo nicht übersteigen
    if kl.KASSENBUCH_TYPEN.get(typ, {}).get('sign', 1) < 0:
        saldo = kl.kassenbuch_saldo(_eff_terminal_nr())
        if betrag_cent > saldo:
            return jsonify({'ok': False,
                            'fehler': f'Betrag ({betrag_cent/100:.2f} €) übersteigt Kassenbestand ({saldo/100:.2f} €)'}), 400

    buchungsdatum = None
    if d.get('buchungsdatum'):
        from datetime import datetime as _dt, date as _date
        today = _date.today()
        try:
            bd = _dt.fromisoformat(d['buchungsdatum']).date()
            if bd > today:
                return jsonify({'ok': False, 'fehler': 'Buchungsdatum darf nicht in der Zukunft liegen'}), 400
            buchungsdatum = _dt.combine(bd, _dt.now().time())
        except Exception:
            pass

    try:
        kl.kassenbuch_eintrag_manuell(
            _eff_terminal_nr(), typ, betrag_cent, session['ma_id'],
            buchungstext=d.get('buchungstext', ''),
            gegenkonto=d.get('gegenkonto', ''),
            mwst_code=d.get('mwst_code') or None,
            belegnummer=d.get('belegnummer', ''),
            buchungsdatum=buchungsdatum,
        )
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400

    info = kl.kassenbuch_info(_eff_terminal_nr())
    return jsonify({'ok': True, 'saldo': info['saldo_haupt'], 'saldo_neben': info['saldo_neben']})


# ── Kassenbuch Monatsansicht & Export ─────────────────────────

@app.get('/kasse/kassenbuch/monat')
@_login_required
def kassenbuch_monat_seite():
    terminal_nr = _eff_terminal_nr()
    # Jahr/Monat aus Query-String oder aktuell
    from datetime import date as _d
    heute = _d.today()
    try:
        jahr  = int(request.args.get('jahr',  heute.year))
        monat = int(request.args.get('monat', heute.month))
        if not (1 <= monat <= 12):
            raise ValueError
    except (ValueError, TypeError):
        jahr, monat = heute.year, heute.month
    daten = kl.kassenbuch_monat(terminal_nr, jahr, monat)
    return render_template('kassenbuch_monat.html',
                           daten=daten,
                           heute=heute,
                           info=kl.kassenbuch_info(terminal_nr),
                           mitarbeiter=_mitarbeiter())


@app.get('/kasse/kassenbuch/export/pdf')
@_login_required
def kassenbuch_export_pdf():
    terminal_nr = _eff_terminal_nr()
    from datetime import date as _d
    heute = _d.today()
    try:
        jahr  = int(request.args.get('jahr',  heute.year))
        monat = int(request.args.get('monat', heute.month))
    except (ValueError, TypeError):
        jahr, monat = heute.year, heute.month
    import kassenbuch_export as ke
    daten = kl.kassenbuch_monat(terminal_nr, jahr, monat)
    try:
        pdf_bytes = ke.als_pdf(daten, config.FIRMA_NAME)
    except ImportError:
        return jsonify({'ok': False,
                        'fehler': 'reportlab nicht installiert (pip install reportlab)'}), 500
    dateiname = f"Kassenbuch_{daten['monat_name']}_{jahr}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=dateiname,
    )


@app.get('/kasse/kassenbuch/export/xlsx')
@_login_required
def kassenbuch_export_xlsx():
    terminal_nr = _eff_terminal_nr()
    from datetime import date as _d
    heute = _d.today()
    try:
        jahr  = int(request.args.get('jahr',  heute.year))
        monat = int(request.args.get('monat', heute.month))
    except (ValueError, TypeError):
        jahr, monat = heute.year, heute.month
    import kassenbuch_export as ke
    daten = kl.kassenbuch_monat(terminal_nr, jahr, monat)
    try:
        xlsx_bytes = ke.als_xlsx(daten, config.FIRMA_NAME)
    except ImportError:
        return jsonify({'ok': False,
                        'fehler': 'openpyxl nicht installiert (pip install openpyxl)'}), 500
    dateiname = f"Kassenbuch_{daten['monat_name']}_{jahr}.xlsx"
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=dateiname,
    )


@app.get('/kasse/kassenbuch/export/csv')
@_login_required
def kassenbuch_export_csv():
    terminal_nr = _eff_terminal_nr()
    from datetime import date as _d
    heute = _d.today()
    try:
        jahr  = int(request.args.get('jahr',  heute.year))
        monat = int(request.args.get('monat', heute.month))
    except (ValueError, TypeError):
        jahr, monat = heute.year, heute.month
    import kassenbuch_export as ke
    daten = kl.kassenbuch_monat(terminal_nr, jahr, monat)
    csv_str = ke.als_csv(daten)
    dateiname = f"Kassenbuch_{daten['monat_name']}_{jahr}.csv"
    return send_file(
        io.BytesIO(csv_str.encode('utf-8-sig')),
        mimetype='text/csv; charset=utf-8',
        as_attachment=True,
        download_name=dateiname,
    )


# ── Zählungen (Stückelung) ──────────────────────────────────────

@app.post('/api/zaehlung')
@_login_required
def api_zaehlung_speichern():
    d   = request.get_json() or {}
    typ = (d.get('typ') or '').upper()
    if typ not in ('KASSENSTURZ', 'TRANSFER_BANK', 'TRESOR'):
        return jsonify({'ok': False, 'fehler': 'Ungültiger Typ'}), 400
    try:
        zid = kl.zaehlung_speichern(
            _eff_terminal_nr(), typ,
            bestand     = d.get('bestand', {}),
            betrag_cent = int(d.get('betrag_cent', 0)),
            kassenbuch_id = d.get('kassenbuch_id'),
        )
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 500
    return jsonify({'ok': True, 'id': zid})


@app.get('/api/zaehlung/<typ>')
@_login_required
def api_zaehlung_laden(typ):
    z = kl.zaehlung_laden(_eff_terminal_nr(), typ.upper())
    if not z:
        return jsonify({'ok': False, 'fehler': 'Keine Zählung gefunden'}), 404
    return jsonify({
        'ok':          True,
        'bestand':     z['bestand'],
        'betrag_cent': z['BETRAG_CENT'],
        'zeitpunkt':   str(z['ZEITPUNKT']),
    })


# ── Manager-Hub ───────────────────────────────────────────────

@app.get('/kasse/manager')
@_login_required
def manager_seite():
    terminal_nr  = _eff_terminal_nr()
    info         = kl.kassenbuch_info(terminal_nr)
    xbon         = kl.xbon_daten(terminal_nr)
    # mwst_saetze_laden() → {code: satz_float}; Template erwartet Liste mit .CODE/.SATZ
    mwst_saetze  = [{'CODE': k, 'SATZ': v}
                    for k, v in sorted(kl.mwst_saetze_laden().items())]
    eintraege_kb = kl.kassenbuch_liste(terminal_nr, kasse='HAUPT', tage=30)
    return render_template('manager.html',
                           info=info,
                           xbon=xbon,
                           mwst_saetze=mwst_saetze,
                           eintraege_kb=_jsonify_rows(eintraege_kb),
                           mitarbeiter=_mitarbeiter())


@app.get('/kasse/nebenkasse')
@_login_required
def nebenkasse_seite():
    terminal_nr = _eff_terminal_nr()
    eintraege   = kl.kassenbuch_liste(terminal_nr, kasse='NEBEN', tage=90)
    info        = kl.kassenbuch_info(terminal_nr)
    return render_template('nebenkasse.html',
                           eintraege=_jsonify_rows(eintraege),
                           info=info,
                           mitarbeiter=_mitarbeiter())


@app.get('/kasse/kassensturz')
@_login_required
def kassensturz_seite():
    terminal_nr = _eff_terminal_nr()
    info        = kl.kassenbuch_info(terminal_nr)
    xbon        = kl.xbon_daten(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('kassensturz.html',
                           info=info,
                           xbon=xbon,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


# ── X-Bon ─────────────────────────────────────────────────────

@app.get('/kasse/xbon')
@_login_required
def xbon_seite():
    terminal_nr = _eff_terminal_nr()
    daten       = kl.xbon_daten(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('xbon.html', daten=daten,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


@app.post('/api/xbon/drucken')
@_login_required
def api_xbon_drucken():
    terminal_nr = _eff_terminal_nr()
    daten       = kl.xbon_daten(terminal_nr)
    mwst_saetze = kl.mwst_saetze_laden()
    try:
        druck.drucke_xbon(config.TERMINAL_NR, daten, mwst_saetze)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


# ── Tagesabschluss ────────────────────────────────────────────

@app.get('/kasse/tagesabschluss')
@_login_required
def tagesabschluss_seite():
    terminal_nr = _eff_terminal_nr()
    daten       = kl.xbon_daten(terminal_nr)   # gleiche Zahlen, ohne Z-Bon zu erstellen
    mwst_saetze = kl.mwst_saetze_laden()
    return render_template('tagesabschluss.html', daten=daten,
                           mwst_saetze=mwst_saetze,
                           mitarbeiter=_mitarbeiter())


@app.post('/api/tagesabschluss')
@_login_required
def api_tagesabschluss():
    terminal_nr = _eff_terminal_nr()
    try:
        ta = kl.tagesabschluss_erstellen(terminal_nr, session['ma_id'])
    except Exception as e:
        log.exception("Tagesabschluss fehlgeschlagen")
        return jsonify({'ok': False, 'fehler': str(e)}), 500

    mwst_saetze = kl.mwst_saetze_laden()
    ts = _terminal_settings(config.TERMINAL_NR)
    try:
        druck.drucke_zbon(config.TERMINAL_NR, ta, mwst_saetze,
                          trainings_modus=ts['trainings_modus'],
                          nicht_produktiv=ts['tse_nicht_produktiv'])
    except Exception as e:
        log.warning("Z-Bon Druck fehlgeschlagen: %s", e)
        return jsonify({'ok': True, 'warnung': f'Druck fehlgeschlagen: {e}',
                        'z_nr': ta['Z_NR'], 'ta_id': ta['ID']})

    return jsonify({
        'ok':    True,
        'z_nr':  ta['Z_NR'],
        'ta_id': ta['ID'],
        # Tatsächlich gespeicherte Werte – für Aktualisierung der Bildschirm-Vorschau,
        # die beim Seitenaufruf statisch gerendert wurde und veraltet sein kann.
        'einlagen':            int(ta['EINLAGEN']            or 0),
        'entnahmen':           int(ta['ENTNAHMEN']           or 0),
        'kassenbestand_anfang':int(ta['KASSENBESTAND_ANFANG']or 0),
        'kassenbestand_ende':  int(ta['KASSENBESTAND_ENDE']  or 0),
        'umsatz_bar':          int(ta['UMSATZ_BAR']          or 0),
        'umsatz_ec':           int(ta['UMSATZ_EC']           or 0),
        'umsatz_brutto':       int(ta['UMSATZ_BRUTTO']       or 0),
        'anzahl_belege':       int(ta['ANZAHL_BELEGE']       or 0),
        'anzahl_stornos':      int(ta['ANZAHL_STORNOS']      or 0),
        'betrag_stornos':      int(ta['BETRAG_STORNOS']      or 0),
    })


# ── Bon → Lieferschein ────────────────────────────────────────

@app.post('/api/vorgang/<int:vid>/lieferschein')
@_login_required
def api_zu_lieferschein(vid):
    """Schließt Kundenvorgang als JOURNAL-Direktbuchung ab.

    Schreibt direkt in JOURNAL/JOURNALPOS (statt offener LIEFERSCHEIN-Eintrag).
    Spart manuelle Nachbearbeitung in CAO-Faktura.
    """
    d = request.get_json() or {}
    adressen_id = d.get('adressen_id')
    if adressen_id is not None:
        adressen_id = int(adressen_id)
    if not adressen_id:
        return jsonify({'ok': False, 'fehler': 'Keine Kundenadresse angegeben'}), 400
    ma    = _mitarbeiter()
    _vname = (ma.get('VNAME') or '').strip()
    _nname = (ma.get('NAME') or '').strip()
    name  = f"{_vname} {_nname}".strip() or 'Kasse'
    ma_id = int(ma.get('MA_ID') or -1)
    try:
        result = kl.lieferschein_zu_journal(
            vid, adressen_id, name,
            terminal_nr=config.TERMINAL_NR,
            ma_id=ma_id
        )
    except ValueError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 400
    except Exception as e:
        log.exception("Fehler bei Lieferschein-Journal-Erstellung: %s", e)
        return jsonify({'ok': False, 'fehler': f'Interner Fehler: {e}'}), 500

    # Lieferschein-Bon drucken (mit Unterschriftszeile, ohne Preise).
    # Druckfehler dürfen den erfolgreichen Abschluss nicht zurückrollen.
    try:
        druck.drucke_lieferschein_bon(config.TERMINAL_NR, vid, adressen_id)
    except Exception as _pe:
        log.warning("Lieferschein-Bondruck fehlgeschlagen (Vorgang trotzdem gebucht): %s", _pe)

    return jsonify({'ok': True, **result})


# ── Admin-Bereich ─────────────────────────────────────────────

@app.get('/admin/')
@_login_required
def admin_index():
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
            (_eff_terminal_nr(),)
        )
        letzte_abschluesse = cur.fetchall()
        cur.execute("SELECT * FROM FIRMA LIMIT 1")
        firma = cur.fetchone() or {}

    # Aktive TSE laden
    aktive_tse = None
    if (terminal or {}).get('TSE_ID'):
        try:
            aktive_tse = tse_modul.tse_geraet_laden(int(float(terminal['TSE_ID'])))
        except Exception:
            pass

    # TSE-Detailstatus (live abfragen, Fehler abfangen)
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
                           aktive_tse=aktive_tse,
                           firma=firma,
                           tse_status=tse_status,
                           trainings_modus=trainings_modus,
                           letzte_abschluesse=_jsonify_rows(letzte_abschluesse),
                           mitarbeiter=_mitarbeiter())


@app.get('/admin/terminal')
@_login_required
def admin_terminal():
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
    f = request.form
    tnr = config.TERMINAL_NR
    sofort_drucken         = 1 if f.get('sofort_drucken') else 0
    schublade_auto_oeffnen = 1 if f.get('schublade_auto_oeffnen') else 0
    qr_code                = 1 if f.get('qr_code') else 0
    trainings_modus        = 1 if f.get('trainings_modus') else 0
    ec_modus               = f.get('ec_modus', 'manuell')
    if ec_modus not in ('manuell', 'zvt'):
        ec_modus = 'manuell'
    ec_terminal_ip         = f.get('ec_terminal_ip', '').strip() or None
    ec_terminal_port       = int(f.get('ec_terminal_port') or 20007)
    ec_tagesabschluss      = f.get('ec_tagesabschluss', 'manuell')
    if ec_tagesabschluss not in ('manuell', 'auto', 'auto_vergleich'):
        ec_tagesabschluss = 'manuell'
    # Passwort: exakt 6 Dezimalstellen, Default 010203
    import re
    ec_zvt_passwort = re.sub(r'[^0-9]', '', f.get('ec_zvt_passwort', '010203'))
    ec_zvt_passwort = ec_zvt_passwort.zfill(6)[:6] or '010203'
    with get_db() as cur:
        cur.execute(
            """INSERT INTO XT_KASSE_TERMINALS
               (TERMINAL_NR, BEZEICHNUNG,
                DRUCKER_IP, DRUCKER_PORT, KASSENLADE,
                SOFORT_DRUCKEN, SCHUBLADE_AUTO_OEFFNEN, QR_CODE, TRAININGS_MODUS,
                FIRMA_NAME, FIRMA_ZUSATZ,
                KONTO_BANK, KONTO_NEBENKASSE, KONTO_KASSENDIFF_AUFWAND, KONTO_KASSENDIFF_ERTRAG,
                EC_MODUS, EC_TERMINAL_IP, EC_TERMINAL_PORT, EC_TAGESABSCHLUSS, EC_ZVT_PASSWORT)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
               BEZEICHNUNG=%s,
               DRUCKER_IP=%s, DRUCKER_PORT=%s, KASSENLADE=%s,
               SOFORT_DRUCKEN=%s, SCHUBLADE_AUTO_OEFFNEN=%s, QR_CODE=%s,
               TRAININGS_MODUS=%s,
               FIRMA_NAME=%s, FIRMA_ZUSATZ=%s,
               KONTO_BANK=%s, KONTO_NEBENKASSE=%s,
               KONTO_KASSENDIFF_AUFWAND=%s, KONTO_KASSENDIFF_ERTRAG=%s,
               EC_MODUS=%s, EC_TERMINAL_IP=%s, EC_TERMINAL_PORT=%s,
               EC_TAGESABSCHLUSS=%s, EC_ZVT_PASSWORT=%s""",
            (tnr,
             f.get('bezeichnung', ''),
             f.get('drucker_ip', ''), int(f.get('drucker_port', 9100)),
             int(f.get('kassenlade', 0)),
             sofort_drucken, schublade_auto_oeffnen, qr_code, trainings_modus,
             f.get('firma_name', ''), f.get('firma_zusatz', ''),
             f.get('konto_bank', '') or None, f.get('konto_nebenkasse', '') or None,
             f.get('konto_kassendiff_aufwand', '') or None,
             f.get('konto_kassendiff_ertrag', '') or None,
             ec_modus, ec_terminal_ip, ec_terminal_port, ec_tagesabschluss, ec_zvt_passwort,
             # ON DUPLICATE KEY
             f.get('bezeichnung', ''),
             f.get('drucker_ip', ''), int(f.get('drucker_port', 9100)),
             int(f.get('kassenlade', 0)),
             sofort_drucken, schublade_auto_oeffnen, qr_code, trainings_modus,
             f.get('firma_name', ''), f.get('firma_zusatz', ''),
             f.get('konto_bank', '') or None, f.get('konto_nebenkasse', '') or None,
             f.get('konto_kassendiff_aufwand', '') or None,
             f.get('konto_kassendiff_ertrag', '') or None,
             ec_modus, ec_terminal_ip, ec_terminal_port, ec_tagesabschluss, ec_zvt_passwort)
        )
    tse_modul._token_cache.pop(tnr, None)
    return redirect(url_for('admin_index'))


@app.post('/admin/terminal/trainings_modus')
@_login_required
def admin_trainings_modus():
    """Trainings-Modus für das Terminal ein- oder ausschalten."""
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
        geraet = tse_modul.tse_geraet_laden(int(float(tse_id))) or {}
    return render_template('admin/tse_form.html',
                           geraet=geraet,
                           mitarbeiter=_mitarbeiter())


@app.post('/admin/tse/neu')
@_login_required
def admin_tse_speichern():
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
    datum_von   = request.form['datum_von']
    datum_bis   = request.form['datum_bis']
    try:
        result = dsfinvk.dsfinvk_export_starten(config.TERMINAL_NR, datum_von, datum_bis)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'exporte': [], 'warnungen': [],
                        'fehler': [str(e)], 'trainings_bons': 0})


@app.get('/admin/export/status/<int:geraet_id>/<export_id>')
@_login_required
def admin_export_status(geraet_id, export_id):
    try:
        status = dsfinvk.dsfinvk_export_status(geraet_id, export_id)
        return jsonify(status)
    except Exception as e:
        return jsonify({'state': 'ERROR', 'fehler': str(e)})


@app.get('/admin/export/download/<int:geraet_id>/<export_id>')
@_login_required
def admin_export_download(geraet_id, export_id):
    try:
        inhalt = dsfinvk.dsfinvk_export_herunterladen(geraet_id, export_id)
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
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_TAGESABSCHLUSS
               WHERE TERMINAL_NR = %s
               ORDER BY DATUM DESC LIMIT 30""",
            (_eff_terminal_nr(),)
        )
        rows = cur.fetchall()
    return render_template('abschluesse.html',
                           abschluesse=_jsonify_rows(rows),
                           mitarbeiter=_mitarbeiter())


@app.post('/api/tagesabschluss/<int:ta_id>/drucken')
@_login_required
def api_zbon_nochmal(ta_id):
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TAGESABSCHLUSS WHERE ID=%s", (ta_id,))
        ta = cur.fetchone()
    if not ta:
        return jsonify({'ok': False, 'fehler': 'Nicht gefunden'}), 404
    mwst_saetze = kl.mwst_saetze_laden()
    ts = _terminal_settings(config.TERMINAL_NR)
    try:
        druck.drucke_zbon(config.TERMINAL_NR, ta, mwst_saetze,
                          trainings_modus=ts['trainings_modus'],
                          nicht_produktiv=ts['tse_nicht_produktiv'])
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)})
    return jsonify({'ok': True})


# ── EC-Terminal (ZVT) ─────────────────────────────────────────

@app.get('/api/ec/status')
@_login_required
def api_ec_status():
    """Prüft ob das konfigurierte ZVT-Terminal TCP-seitig erreichbar ist."""
    ts = _terminal_settings(config.TERMINAL_NR)
    if ts['trainings_modus']:
        return jsonify({'ok': False, 'erreichbar': False,
                        'fehler': 'Im Trainings-Modus nicht verfügbar'})
    if ts['ec_modus'] != 'zvt' or not ts['ec_terminal_ip']:
        return jsonify({'ok': False, 'erreichbar': False,
                        'fehler': 'Kein ZVT-Terminal konfiguriert'})
    import ec_zvt
    erreichbar = ec_zvt.ping(ts['ec_terminal_ip'], ts['ec_terminal_port'])
    return jsonify({'ok': True, 'erreichbar': erreichbar,
                    'ip': ts['ec_terminal_ip'], 'port': ts['ec_terminal_port']})


@app.post('/api/ec/zahlung')
@_login_required
def api_ec_zahlung():
    """
    Initiiert eine Kartenzahlung über ZVT am Desk 3500 (blockiert bis ~90 s).
    Im Trainings-Modus nicht verfügbar – das Frontend erzwingt dort manuellen Modus.
    Rückgabe: {ok, referenz, terminal_id} oder {ok: false, fehler, offline}
    """
    ts = _terminal_settings(config.TERMINAL_NR)
    if ts['trainings_modus']:
        return jsonify({'ok': False, 'offline': True,
                        'fehler': 'Im Trainings-Modus nicht verfügbar'}), 400
    if ts['ec_modus'] != 'zvt' or not ts['ec_terminal_ip']:
        return jsonify({'ok': False, 'fehler': 'ZVT nicht konfiguriert', 'offline': True}), 400
    d = request.get_json(force=True) or {}
    betrag_cent = int(d.get('betrag_cent', 0))
    if not betrag_cent:
        return jsonify({'ok': False, 'fehler': 'Kein Betrag angegeben'}), 400
    import ec_zvt
    passwort = ec_zvt.passwort_von_hex(ts['ec_zvt_passwort'])
    return jsonify(ec_zvt.authorisieren(
        ts['ec_terminal_ip'], ts['ec_terminal_port'], betrag_cent, passwort=passwort
    ))


@app.post('/api/ec/tagesabschluss')
@_login_required
def api_ec_tagesabschluss():
    """
    Führt den EC-Terminal-Tagesabschluss durch und liest die Totals aus.
    Rückgabe: {ok, totals: {gesamt_cent, anzahl, details} | null, fehler, offline}
    """
    ts = _terminal_settings(config.TERMINAL_NR)
    if ts['trainings_modus']:
        return jsonify({'ok': False, 'totals': None,
                        'fehler': 'Im Trainings-Modus nicht verfügbar', 'offline': True}), 400
    if ts['ec_modus'] != 'zvt' or not ts['ec_terminal_ip']:
        return jsonify({'ok': False, 'totals': None,
                        'fehler': 'ZVT nicht konfiguriert', 'offline': True}), 400
    import ec_zvt
    passwort = ec_zvt.passwort_von_hex(ts['ec_zvt_passwort'])
    return jsonify(ec_zvt.tagesabschluss_ausfuehren(
        ts['ec_terminal_ip'], ts['ec_terminal_port'], passwort=passwort
    ))


# ── Handbuch ──────────────────────────────────────────────────

_DOKU_DIR = os.path.join(os.path.dirname(__file__), 'doku')


@app.get('/kasse/doku/<path:dateiname>')
@_login_required
def kasse_doku_datei(dateiname):
    """Statische Dateien aus dem doku/-Verzeichnis (Bilder für Handbuch)."""
    return send_from_directory(os.path.abspath(_DOKU_DIR), dateiname)


@app.get('/kasse/handbuch')
@_login_required
def kasse_handbuch():
    """Mitarbeiter-Handbuch – alle eingeloggten User dürfen lesen,
    Administratoren (admin=True in Session) dürfen bearbeiten."""
    pfad = os.path.join(_DOKU_DIR, 'handbuch.html')
    try:
        with open(pfad, encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        return 'Handbuch nicht gefunden.', 404
    ist_admin = bool(session.get('admin') or session.get('ma_id'))
    inject = (f'<script id="hb-inject">'
              f'window.HANDBUCH_ADMIN = {"true" if ist_admin else "false"};'
              f'</script>\n')
    html = html.replace('</head>', inject + '</head>', 1)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.post('/kasse/handbuch/speichern')
@_login_required
def kasse_handbuch_speichern():
    """Speichert das bearbeitete Handbuch. Backup der alten Version wird angelegt."""
    data = request.get_json(force=True) or {}
    html = data.get('html', '').strip()
    if not html:
        return jsonify({'ok': False, 'fehler': 'Kein Inhalt'}), 400
    pfad   = os.path.join(_DOKU_DIR, 'handbuch.html')
    backup = pfad + '.bak'
    try:
        if os.path.exists(pfad):
            with open(pfad, 'rb') as f_in, open(backup, 'wb') as f_bak:
                f_bak.write(f_in.read())
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write(html)
    except OSError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 500
    return jsonify({'ok': True})


@app.post('/kasse/handbuch/upload')
@_login_required
def kasse_handbuch_upload():
    """Speichert ein hochgeladenes Bild im doku/-Verzeichnis."""
    data      = request.get_json(force=True) or {}
    dateiname = os.path.basename(data.get('filename', ''))
    b64data   = data.get('data', '')
    if not dateiname or not b64data:
        return jsonify({'ok': False, 'fehler': 'filename oder data fehlt'}), 400
    if ',' in b64data:
        b64data = b64data.split(',', 1)[1]
    try:
        bild_bytes = base64.b64decode(b64data)
        ziel = os.path.join(_DOKU_DIR, dateiname)
        with open(ziel, 'wb') as f:
            f.write(bild_bytes)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 500
    return jsonify({'ok': True, 'filename': f'/kasse/doku/{dateiname}'})


# ── App-Update ────────────────────────────────────────────────

def _parse_git_log(raw: str) -> list[dict]:
    ergebnis = []
    for zeile in raw.splitlines():
        teile = zeile.split("|", 3)
        if len(teile) == 4:
            ergebnis.append({
                "hash":  teile[0],
                "short": teile[1],
                "msg":   teile[2],
                "datum": teile[3][:16].replace("T", " ") if "T" in teile[3] else teile[3][:16],
            })
    return ergebnis


@app.get("/update")
@_login_required
def update_seite():
    commits_neu   = []
    commits_lokal = []
    fehler = _update_status.get("fehler")
    try:
        if _update_status["verfuegbar"]:
            raw = _git(["log", "HEAD..origin/master", "--format=%H|%h|%s|%ai"])
            commits_neu = _parse_git_log(raw)
        raw2 = _git(["log", f"{ROLLBACK_MIN_COMMIT}^..HEAD", "--format=%H|%h|%s|%ai"])
        commits_lokal = _parse_git_log(raw2)
    except Exception as exc:
        fehler = str(exc)
    return render_template(
        "update.html",
        status=_update_status,
        commits_neu=commits_neu,
        commits_lokal=commits_lokal,
        git_verfuegbar=bool(GIT_ROOT),
        fehler=fehler,
    )


@app.post("/api/update/ausfuehren")
@_login_required
def api_update_ausfuehren():
    try:
        ausgabe = _git(["fetch", "origin", "master"], timeout=60)
        ausgabe += "\n" + _git(["reset", "--hard", "origin/master"], timeout=30)
    except Exception as exc:
        return jsonify({"ok": False, "fehler": str(exc)})

    def _neustart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_neustart, daemon=False).start()
    return jsonify({"ok": True, "ausgabe": ausgabe, "neustart": True})


@app.post("/api/update/rollback/<commit_hash>")
@_login_required
def api_update_rollback(commit_hash):
    if not all(c in "0123456789abcdefABCDEF" for c in commit_hash) or not (7 <= len(commit_hash) <= 40):
        return jsonify({"ok": False, "fehler": "Ungültiger Commit-Hash"}), 400
    try:
        ausgabe = _git(["reset", "--hard", commit_hash], timeout=30)
    except Exception as exc:
        return jsonify({"ok": False, "fehler": str(exc)})

    def _neustart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_neustart, daemon=False).start()
    return jsonify({"ok": True, "ausgabe": ausgabe, "neustart": True})


# ── Start ─────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("CAO-XT Kassen-App startet auf %s:%d (Terminal %d)",
             config.HOST, config.PORT, config.TERMINAL_NR)
    if not db_modul.test_verbindung():
        log.error("Datenbankverbindung fehlgeschlagen! Bitte config.py prüfen.")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
