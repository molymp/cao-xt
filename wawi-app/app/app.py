"""
CAO-XT WaWi-App – Flask-Hauptanwendung
Starten: cd wawi-app/app && python3 app.py
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, date
from functools import wraps
import hashlib
import os
import sys
import logging
import config
import db as db_modul
from db import get_db, test_verbindung

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False


# ── Authentifizierung ─────────────────────────────────────────

def _mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """
    Prüft Credentials gegen MITARBEITER-Tabelle.
    CAO speichert Passwörter als MD5-Hash (Großbuchstaben).
    Gibt {MA_ID, LOGIN_NAME, VNAME, NAME} zurück oder None.
    """
    pw_hash = hashlib.md5(passwort.encode('utf-8')).hexdigest().upper()
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT MA_ID, LOGIN_NAME, VNAME, NAME FROM MITARBEITER "
                "WHERE LOGIN_NAME = %s AND USER_PASSWORD = %s",
                (login_name, pw_hash),
            )
            return cur.fetchone()
    except Exception as e:
        log.warning("Login-Abfrage fehlgeschlagen: %s", e)
        return None


def _login_required(f):
    @wraps(f)
    def _wrapper(*args, **kwargs):
        if not session.get('ma_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return _wrapper


# ── WaWi-Blueprint einbinden ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', '..', 'modules', 'wawi'))
try:
    import routes as wawi_routes
    app.register_blueprint(wawi_routes.bp, url_prefix='/wawi')
    log.info("WaWi-Blueprint registriert.")
except Exception as e:
    log.warning("WaWi-Blueprint konnte nicht geladen werden: %s", e)


# ── Context-Processor ─────────────────────────────────────────

@app.context_processor
def _inject_globals():
    kasse_url = config.KASSE_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
        if config.KASSE_PORT else '')
    kiosk_url = config.KIOSK_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
        if config.KIOSK_PORT else '')
    return {
        "firma_name":    config.FIRMA_NAME,
        "kasse_url":     kasse_url,
        "kiosk_url":     kiosk_url,
        "db_ok":         test_verbindung(),
        "current_user":  {
            "ma_id":      session.get('ma_id'),
            "login_name": session.get('login_name'),
            "vname":      session.get('vname'),
            "name":       session.get('ma_name'),
        } if session.get('ma_id') else None,
    }


# ── Dashboard-Abfragen ────────────────────────────────────────

def _monatsumsatz_6_monate() -> list[dict]:
    """Monatsumsatz (Brutto) der letzten 6 Monate aus CAO-Journal.
    Quelle: JOURNAL mit QUELLE=3 (Kasse) und QUELLE_SUB=2 (Kassenbuchung),
    gemäß CFO-Analyse (HAB-15).
    """
    sql = """
        SELECT
            DATE_FORMAT(j.RDATUM, '%Y-%m') AS monat,
            DATE_FORMAT(j.RDATUM, '%b %Y') AS label,
            ROUND(SUM(j.BSUMME), 2)        AS brutto
        FROM JOURNAL j
        WHERE j.QUELLE = 3
          AND j.QUELLE_SUB = 2
          AND j.RDATUM >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
        GROUP BY DATE_FORMAT(j.RDATUM, '%Y-%m')
        ORDER BY monat ASC
    """
    try:
        with get_db() as cur:
            cur.execute(sql)
            return cur.fetchall()
    except Exception as e:
        log.warning("Monatsumsatz-Abfrage fehlgeschlagen: %s", e)
        return []


def _tageseinnahmen_heute() -> float:
    """Heutige Tageseinnahmen (Brutto) in Euro aus CAO-Journal."""
    sql = """
        SELECT COALESCE(ROUND(SUM(j.BSUMME), 2), 0.0) AS einnahmen
        FROM JOURNAL j
        WHERE j.QUELLE = 3
          AND j.QUELLE_SUB = 2
          AND DATE(j.RDATUM) = CURDATE()
    """
    try:
        with get_db() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return float(row['einnahmen']) if row else 0.0
    except Exception as e:
        log.warning("Tageseinnahmen-Abfrage fehlgeschlagen: %s", e)
        return 0.0


def _offene_vorgaenge() -> int:
    """Anzahl offener Vorgänge (Lieferscheine ohne Rechnung)."""
    sql = """
        SELECT COUNT(*) AS anzahl
        FROM VORGANG
        WHERE STATUS = 'O'
    """
    try:
        with get_db() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row['anzahl']) if row else 0
    except Exception as e:
        log.warning("Offene-Vorgänge-Abfrage fehlgeschlagen: %s", e)
        return 0


# ── Login / Logout ────────────────────────────────────────────

@app.get('/login')
def login():
    if session.get('ma_id'):
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.post('/login')
def login_post():
    login_name = request.form.get('login_name', '').strip()
    passwort   = request.form.get('passwort', '')
    ma = _mitarbeiter_login(login_name, passwort)
    if ma:
        session['ma_id']      = ma['MA_ID']
        session['login_name'] = ma['LOGIN_NAME']
        session['vname']      = ma['VNAME']
        session['ma_name']    = ma['NAME']
        session['mitarbeiter'] = ma['LOGIN_NAME']   # für WaWi-Blueprint
        return redirect(url_for('dashboard'))
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Routen ───────────────────────────────────────────────────

@app.route('/')
@_login_required
def dashboard():
    monatsumsatz   = _monatsumsatz_6_monate()
    tageseinnahmen = _tageseinnahmen_heute()
    offene_vorgaenge = _offene_vorgaenge()
    return render_template(
        'dashboard.html',
        monatsumsatz=monatsumsatz,
        tageseinnahmen=tageseinnahmen,
        offene_vorgaenge=offene_vorgaenge,
        heute=date.today().strftime('%d.%m.%Y'),
    )


@app.route('/coming-soon')
@_login_required
def coming_soon():
    modul = request.args.get('modul', 'Dieses Modul')
    return render_template('coming_soon.html', modul=modul)


@app.route('/api/status')
@_login_required
def api_status():
    return jsonify({
        'app': 'wawi-app',
        'db':  test_verbindung(),
        'ts':  datetime.now().isoformat(),
    })


# ── Start ────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("WaWi-App startet auf %s:%s (debug=%s)", config.HOST, config.PORT, config.DEBUG)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
