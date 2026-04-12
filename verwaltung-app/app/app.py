"""
CAO-XT Verwaltungs-App – Flask-Hauptanwendung
Starten: cd verwaltung-app/app && python3 app.py
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session)
from functools import wraps
from datetime import datetime
import configparser
import hashlib
import os
import socket
import subprocess
import sys
import logging
import config
import db as db_modul
from db import get_db, get_db_transaction, test_verbindung, reset_pool

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── DB-Migrationen ──────────────────────────────────────────────

def _migrationen_ausfuehren():
    """Erstellt benötigte Tabellen falls nicht vorhanden."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_DRUCKER_CONFIG (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    terminal_nr  INT NOT NULL,
                    ip_adresse   VARCHAR(64) NOT NULL,
                    port         INT DEFAULT 9100,
                    bezeichnung  VARCHAR(128),
                    geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_terminal (terminal_nr)
                )
            """)
            log.info("Migration: XT_DRUCKER_CONFIG geprüft/erstellt.")
    except Exception as e:
        log.warning("Migration fehlgeschlagen (DB evtl. nicht erreichbar): %s", e)


_migrationen_ausfuehren()


# ── Git-Commit-Hash (einmalig beim Start) ─────────────────────

try:
    _r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=5, cwd=BASE_DIR,
    )
    GIT_COMMIT_SHORT = _r.stdout.strip() if _r.returncode == 0 else ""
except Exception:
    GIT_COMMIT_SHORT = ""


# ── Authentifizierung ────────────────────────────────────────────

def _mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """
    Prüft Credentials gegen MITARBEITER-Tabelle.
    CAO speichert Passwörter als MD5-Hash (Großbuchstaben).
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


# ── Context-Processor ────────────────────────────────────────────

@app.context_processor
def _inject_globals():
    kasse_url = config.KASSE_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
        if config.KASSE_PORT else '')
    kiosk_url = config.KIOSK_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
        if config.KIOSK_PORT else '')
    wawi_url = config.WAWI_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.WAWI_PORT}'
        if config.WAWI_PORT else '')
    return {
        "firma_name":       config.FIRMA_NAME,
        "kasse_url":        kasse_url,
        "kiosk_url":        kiosk_url,
        "wawi_url":         wawi_url,
        "db_ok":            test_verbindung(),
        "current_user": {
            "ma_id":      session.get('ma_id'),
            "login_name": session.get('login_name'),
            "vname":      session.get('vname'),
            "name":       session.get('ma_name'),
        } if session.get('ma_id') else None,
        "git_commit_short": GIT_COMMIT_SHORT,
    }


# ── Login / Logout ──────────────────────────────────────────────

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
        return redirect(url_for('dashboard'))
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Dashboard ────────────────────────────────────────────────────

@app.route('/')
@_login_required
def dashboard():
    return render_template('dashboard.html')


# ── Phase B: Datenbank-Zugangsdaten ─────────────────────────────

def _read_ini_config() -> dict:
    """Liest die caoxt.ini und gibt die Datenbank-Sektion zurück."""
    cfg = configparser.ConfigParser()
    cfg.read(config.INI_PATH)
    if not cfg.has_section('Datenbank'):
        return {}
    return dict(cfg.items('Datenbank'))


@app.route('/db-config')
@_login_required
def db_config():
    ini = _read_ini_config()
    return render_template('db_config.html', ini=ini)


@app.post('/db-config')
@_login_required
def db_config_save():
    cfg = configparser.ConfigParser()
    cfg.read(config.INI_PATH)
    if not cfg.has_section('Datenbank'):
        cfg.add_section('Datenbank')
    cfg.set('Datenbank', 'db_loc',  request.form.get('db_loc', '').strip())
    cfg.set('Datenbank', 'db_port', request.form.get('db_port', '3306').strip())
    cfg.set('Datenbank', 'db_name', request.form.get('db_name', '').strip())
    cfg.set('Datenbank', 'db_user', request.form.get('db_user', '').strip())
    pw = request.form.get('db_pass', '').strip()
    if pw:
        cfg.set('Datenbank', 'db_pass', pw)
    try:
        with open(config.INI_PATH, 'w') as f:
            cfg.write(f)
        log.info("caoxt.ini aktualisiert durch %s", session.get('login_name'))
        # In-Memory-Config und DB-Pool mit neuen Werten neu laden
        config.reload_db_config()
        reset_pool()
        # Migrationen erneut versuchen (beim Start evtl. fehlgeschlagen)
        _migrationen_ausfuehren()
        return jsonify(ok=True, msg='Konfiguration gespeichert.')
    except Exception as e:
        log.error("caoxt.ini schreiben fehlgeschlagen: %s", e)
        return jsonify(ok=False, msg=f'Fehler: {e}'), 500


@app.post('/db-config/test')
@_login_required
def db_config_test():
    """Testet die aktuelle DB-Verbindung."""
    ok = test_verbindung()
    return jsonify(ok=ok, msg='Verbindung erfolgreich.' if ok else 'Verbindung fehlgeschlagen.')


# ── Phase C: Bondrucker-Verwaltung ──────────────────────────────

@app.route('/drucker')
@_login_required
def drucker():
    return render_template('drucker.html')


@app.get('/api/drucker')
@_login_required
def api_drucker_list():
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM XT_DRUCKER_CONFIG ORDER BY terminal_nr")
            return jsonify(ok=True, drucker=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/drucker')
@_login_required
def api_drucker_create():
    d = request.get_json(force=True)
    try:
        with get_db() as cur:
            cur.execute(
                "INSERT INTO XT_DRUCKER_CONFIG (terminal_nr, ip_adresse, port, bezeichnung) "
                "VALUES (%s, %s, %s, %s)",
                (d['terminal_nr'], d['ip_adresse'], d.get('port', 9100), d.get('bezeichnung', '')),
            )
        return jsonify(ok=True, msg='Drucker angelegt.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.put('/api/drucker/<int:drucker_id>')
@_login_required
def api_drucker_update(drucker_id):
    d = request.get_json(force=True)
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE XT_DRUCKER_CONFIG SET terminal_nr=%s, ip_adresse=%s, port=%s, bezeichnung=%s "
                "WHERE id=%s",
                (d['terminal_nr'], d['ip_adresse'], d.get('port', 9100), d.get('bezeichnung', ''), drucker_id),
            )
        return jsonify(ok=True, msg='Drucker aktualisiert.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.delete('/api/drucker/<int:drucker_id>')
@_login_required
def api_drucker_delete(drucker_id):
    try:
        with get_db() as cur:
            cur.execute("DELETE FROM XT_DRUCKER_CONFIG WHERE id=%s", (drucker_id,))
        return jsonify(ok=True, msg='Drucker gelöscht.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/drucker/<int:drucker_id>/test')
@_login_required
def api_drucker_test(drucker_id):
    """Socket-Ping auf den Drucker (Verbindungstest)."""
    try:
        with get_db() as cur:
            cur.execute("SELECT ip_adresse, port FROM XT_DRUCKER_CONFIG WHERE id=%s", (drucker_id,))
            row = cur.fetchone()
        if not row:
            return jsonify(ok=False, msg='Drucker nicht gefunden.'), 404
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((row['ip_adresse'], row['port']))
        s.close()
        if result == 0:
            return jsonify(ok=True, msg=f"Verbindung zu {row['ip_adresse']}:{row['port']} erfolgreich.")
        return jsonify(ok=False, msg=f"Keine Verbindung zu {row['ip_adresse']}:{row['port']}.")
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase D: Terminal-Verwaltung ────────────────────────────────

@app.route('/terminals')
@_login_required
def terminals():
    return render_template('terminals.html')


@app.get('/api/terminals')
@_login_required
def api_terminals_list():
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM XT_KASSE_TERMINALS ORDER BY TERMINAL_NR")
            return jsonify(ok=True, terminals=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.put('/api/terminals/<int:terminal_nr>')
@_login_required
def api_terminal_update(terminal_nr):
    d = request.get_json(force=True)
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE XT_KASSE_TERMINALS SET BEZEICHNUNG=%s WHERE TERMINAL_NR=%s",
                (d.get('bezeichnung', ''), terminal_nr),
            )
        return jsonify(ok=True, msg='Terminal aktualisiert.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase D: TSE-Verwaltung ─────────────────────────────────────

@app.route('/tse')
@_login_required
def tse():
    return render_template('tse.html')


@app.get('/api/tse')
@_login_required
def api_tse_list():
    """TSE-Geräte aus XT_KASSE_TSE_GERAETE mit zugeordneten Terminals."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT g.*,
                       GROUP_CONCAT(t.TERMINAL_NR ORDER BY t.TERMINAL_NR) AS TERMINAL_NRS
                  FROM XT_KASSE_TSE_GERAETE g
                  LEFT JOIN XT_KASSE_TERMINALS t ON t.TSE_ID = g.REC_ID
                 GROUP BY g.REC_ID
                 ORDER BY g.REC_ID DESC
            """)
            return jsonify(ok=True, geraete=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase E: Backwaren/Artikel-Verwaltung ───────────────────────

@app.route('/artikel')
@_login_required
def artikel():
    return render_template('artikel.html')


# ── System: Updates ──────────────────────────────────────────────

@app.route('/system/updates')
@_login_required
def system_updates():
    return render_template('system_updates.html')


@app.route('/api/system/update-status')
@_login_required
def api_update_status():
    """Prüft auf Updates (git fetch + VERSION.json-Vergleich)."""
    import json as _json
    import subprocess as _sp

    repo_root = os.path.normpath(os.path.join(BASE_DIR, '..', '..'))
    version_file = os.path.join(repo_root, 'VERSION.json')

    def _git(*args):
        return _sp.run(
            ['git'] + list(args),
            cwd=repo_root, capture_output=True, text=True, timeout=30
        )

    def _load_json(path):
        try:
            with open(path, encoding='utf-8') as fh:
                return _json.load(fh)
        except Exception:
            return None

    # Lokale Version
    local_data = _load_json(version_file)
    local_v = local_data.get('version', 'unbekannt') if local_data else 'unbekannt'

    # git fetch
    fetch = _git('fetch', 'origin', 'master')
    if fetch.returncode != 0:
        return jsonify({
            'error': f"git fetch fehlgeschlagen: {fetch.stderr.strip()}",
            'local_version': local_v,
        }), 200

    # Remote VERSION.json
    show = _git('show', 'origin/master:VERSION.json')
    if show.returncode != 0:
        return jsonify({
            'error': 'VERSION.json auf Remote nicht lesbar',
            'local_version': local_v,
        }), 200

    try:
        remote_data = _json.loads(show.stdout)
    except _json.JSONDecodeError:
        return jsonify({'error': 'VERSION.json ungültig', 'local_version': local_v}), 200

    remote_v = remote_data.get('version', 'unbekannt')
    impact   = remote_data.get('impact', {})
    changelog = remote_data.get('changelog_summary', '')

    # Versionsvergleich
    def _sv(v):
        try:
            return tuple(int(x) for x in v.split('.'))
        except ValueError:
            return (0, 0, 0)

    available = _sv(remote_v) > _sv(local_v)

    # Neue Commits
    commits = []
    if available:
        log_r = _git('log', '--oneline', 'HEAD..origin/master')
        if log_r.returncode == 0:
            commits = [l for l in log_r.stdout.splitlines() if l.strip()]

    return jsonify({
        'available': available,
        'local_version': local_v,
        'remote_version': remote_v,
        'changelog_summary': changelog,
        'commits': commits[:30],
        'impact': impact,
        'error': None,
    })


@app.route('/api/system/update', methods=['POST'])
@_login_required
def api_system_update():
    """
    Startet das Update im Hintergrund.
    Das Script loggt nach /tmp/caoxt-update.log.
    """
    repo_root = os.path.normpath(os.path.join(BASE_DIR, '..', '..'))
    venv_python = os.path.join(repo_root, '.venv', 'bin', 'python3')
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    try:
        subprocess.Popen(
            [venv_python, '-m', 'installer.updater', '--update'],
            cwd=repo_root,
            stdout=open('/tmp/caoxt-update.log', 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({'ok': True, 'log': '/tmp/caoxt-update.log'})


# ── App starten ──────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Verwaltungs-App startet auf %s:%s", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
