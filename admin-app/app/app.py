"""
CAO-XT Admin-App – Flask-Hauptanwendung
Starten: cd admin-app/app && python3 app.py
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_from_directory)
from jinja2 import ChoiceLoader, FileSystemLoader
from functools import wraps
from datetime import datetime
import base64
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
from common.auth import mitarbeiter_login_karte

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DOKU_DIR = os.path.join(BASE_DIR, 'doku')

# Zusaetzliche Template-Quelle: common/templates/ fuer gemeinsame Bausteine
# (Navbar, Toast, Touch-Widgets, Login-Shell). Wird mit App-eigenen Templates
# ueber ChoiceLoader kombiniert (App-Templates haben Vorrang).
_COMMON_TEMPLATES = os.path.normpath(
    os.path.join(BASE_DIR, '..', '..', 'common', 'templates')
)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(_COMMON_TEMPLATES),
])


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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINSTELLUNGEN (
                    schluessel   VARCHAR(100) NOT NULL PRIMARY KEY,
                    wert         VARCHAR(500) NOT NULL DEFAULT '',
                    beschreibung VARCHAR(255),
                    geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    geaendert_von VARCHAR(100)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Systemweite Einstellungen (key-value)'
            """)
            # Standardwerte für Parken-Schalter (INSERT IGNORE → nur beim ersten Mal)
            cur.execute("""
                INSERT IGNORE INTO XT_EINSTELLUNGEN (schluessel, wert, beschreibung)
                VALUES
                    ('kiosk_parken_aktiv', '1', 'Parken-Funktion in der Kiosk-App aktiv'),
                    ('kasse_parken_aktiv', '1', 'Parken-Funktion in der Kasse-App aktiv'),
                    ('personal_bundesland', 'BY', 'Bundesland fuer gesetzliche Feiertage (BY, BW, BE, BB, HB, HH, HE, MV, NI, NW, RP, SL, SN, ST, SH, TH)'),
                    ('personal_urlaub_uebertrag_verfall', '03-31', 'Stichtag (Format MM-TT) im Folgejahr, bis zu dem Urlaubsuebertraege aus dem Vorjahr genommen werden muessen – danach verfallen sie ersatzlos')
            """)
            log.info("Migration: XT_EINSTELLUNGEN geprüft/erstellt.")
            # Benachrichtigungs-Empfaenger (E-Mail-Verteiler je Bereich).
            # Spiegel des Schemas in modules/orga/personal/schema.sql –
            # idempotent, damit die Admin auch ohne orga-Start laeuft.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_BENACHRICHTIGUNG_EMPFAENGER (
                    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    BEREICH      VARCHAR(40)  NOT NULL,
                    EMAIL        VARCHAR(150) NOT NULL,
                    NAME         VARCHAR(100) NULL,
                    AKTIV        TINYINT UNSIGNED NOT NULL DEFAULT 1,
                    ERSTELLT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ERSTELLT_VON INT UNSIGNED NULL,
                    UNIQUE KEY uq_bereich_email (BEREICH, EMAIL),
                    INDEX idx_bereich_aktiv (BEREICH, AKTIV)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='E-Mail-Verteiler fuer Hinweis-Benachrichtigungen'
            """)
            log.info("Migration: XT_BENACHRICHTIGUNG_EMPFAENGER geprüft/erstellt.")
            # Spalte VERFAELLT_AM in XT_PERSONAL_URLAUB_KORREKTUR –
            # fuer Urlaubsuebertrag-Verfall (Spiegel zu
            # modules/orga/personal/schema.sql). Nur ausfuehren, wenn die
            # Zieltabelle bereits existiert (sonst legt das orga-Modul sie
            # beim ersten Personal-Zugriff an und die Spalte kommt dort mit).
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                " WHERE TABLE_SCHEMA = DATABASE() "
                "   AND TABLE_NAME = 'XT_PERSONAL_URLAUB_KORREKTUR'"
            )
            if cur.fetchone()['n']:
                cur.execute("""
                    ALTER TABLE XT_PERSONAL_URLAUB_KORREKTUR
                      ADD COLUMN IF NOT EXISTS VERFAELLT_AM DATE NULL
                      COMMENT 'Stichtag, bis zu dem diese Korrektur verbraucht sein muss'
                      AFTER KOMMENTAR
                """)
                log.info("Migration: XT_PERSONAL_URLAUB_KORREKTUR.VERFAELLT_AM geprüft.")
            # Log-Tabelle fuer Stunden-Korrekturen (GoBD, append-only) –
            # Spiegel zu modules/orga/personal/schema.sql.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_PERSONAL_STUNDEN_KORREKTUR_LOG (
                    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    PERS_ID          INT UNSIGNED NOT NULL,
                    REF_REC_ID       INT UNSIGNED NOT NULL,
                    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
                    FELDER_ALT_JSON  JSON         NULL,
                    FELDER_NEU_JSON  JSON         NULL,
                    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    GEAEND_VON       INT UNSIGNED NULL,
                    INDEX idx_pers_id   (PERS_ID),
                    INDEX idx_geaend_at (GEAEND_AT)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_STUNDEN_KORREKTUR'
            """)
            log.info("Migration: XT_PERSONAL_STUNDEN_KORREKTUR_LOG geprüft/erstellt.")
            # Spalte IN_ZEITERFASSUNG in XT_PERSONAL_LOHNART + Seed-Eintrag
            # fuer 'Leitende Angestellte / GF' (Spiegel zu
            # modules/orga/personal/schema.sql).
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                " WHERE TABLE_SCHEMA = DATABASE() "
                "   AND TABLE_NAME = 'XT_PERSONAL_LOHNART'"
            )
            if cur.fetchone()['n']:
                cur.execute("""
                    ALTER TABLE XT_PERSONAL_LOHNART
                      ADD COLUMN IF NOT EXISTS IN_ZEITERFASSUNG TINYINT(1)
                         NOT NULL DEFAULT 1
                         COMMENT '1 = nimmt an Zeiterfassung teil, 0 = nicht'
                         AFTER SV_PFLICHTIG_FLAG
                """)
                cur.execute("""
                    INSERT IGNORE INTO XT_PERSONAL_LOHNART
                      (LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG,
                       SV_PFLICHTIG_FLAG, IN_ZEITERFASSUNG, SORT)
                    VALUES (7, 'Leitende Angestellte / GF', 0, 1, 0, 70)
                """)
                log.info("Migration: XT_PERSONAL_LOHNART.IN_ZEITERFASSUNG geprüft.")
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
    orga_url = config.ORGA_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.ORGA_PORT}'
        if config.ORGA_PORT else '')
    return {
        "firma_name":       config.FIRMA_NAME,
        "kasse_url":        kasse_url,
        "kiosk_url":        kiosk_url,
        "orga_url":         orga_url,
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


@app.post('/login/karte')
def login_karte():
    """Login per Mitarbeiter-Karte (Barcode-Scan)."""
    guid = request.form.get('guid', '').strip()
    if not guid:
        return render_template('login.html', fehler='Kein Barcode erkannt.')
    ma = mitarbeiter_login_karte(guid)
    if ma:
        session['ma_id']      = ma['MA_ID']
        session['login_name'] = ma['LOGIN_NAME']
        session['vname']      = ma['VNAME']
        session['ma_name']    = ma['NAME']
        return redirect(url_for('dashboard'))
    return render_template('login.html',
                           fehler='Karte nicht erkannt oder keine Mitarbeiterkarte.')


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


# ── Phase C: Bondrucker-Admin ──────────────────────────────

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


# ── Phase D: Terminal-Admin ────────────────────────────────

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


# ── Phase D: TSE-Admin ─────────────────────────────────────

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


# ── Phase E: Backwaren/Artikel-Admin ───────────────────────

# Produktbilder-Verzeichnis: standardmäßig im kiosk-app/app/produktbilder/.
# Beide Apps (Kiosk zur Anzeige, Admin zum Verwalten) greifen auf dasselbe Verzeichnis zu.
PRODUKTBILDER_DIR = os.environ.get('PRODUKTBILDER_DIR') or os.path.join(
    BASE_DIR, '..', '..', 'kiosk-app', 'app', 'produktbilder')
PRODUKTBILDER_DIR = os.path.abspath(PRODUKTBILDER_DIR)
ERLAUBTE_BILD_ENDUNGEN = {"jpg", "jpeg", "png", "webp"}
MAX_BILD_GROESSE = 5 * 1024 * 1024  # 5 MB


def _cent_zu_euro_str(cent: int) -> str:
    """Hilfsfunktion für Template-Formatierung."""
    return f"{cent / 100:.2f} €"


@app.route('/artikel')
@_login_required
def artikel():
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KIOSK_V_ARTIKEL_VERWALTUNG")
        artikel_liste = cur.fetchall()
        cur.execute("SELECT * FROM XT_KIOSK_KATEGORIEN ORDER BY sort_order")
        kategorien = cur.fetchall()
    return render_template(
        'artikel.html',
        artikel=artikel_liste,
        kategorien=kategorien,
        cent_zu_euro=_cent_zu_euro_str,
    )


@app.route('/artikel/<int:artikel_id>', methods=['POST'])
@_login_required
def artikel_speichern(artikel_id):
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify(ok=False, msg='Keine Daten empfangen'), 400
    try:
        with get_db() as cur:
            cur.execute("SELECT id FROM XT_KIOSK_PRODUKTE WHERE id=%s", (artikel_id,))
            exists = cur.fetchone()
            if exists:
                cur.execute(
                    """UPDATE XT_KIOSK_PRODUKTE
                       SET kategorie_id=%s, einheit=%s, wochentage=%s,
                           zutaten=%s, aktiv=%s, hinweis=%s
                       WHERE id=%s""",
                    (data.get("kategorie_id"), data.get("einheit", "Stck."),
                     data.get("wochentage", ""), data.get("zutaten"),
                     data.get("aktiv", 1), data.get("hinweis"), artikel_id))
            else:
                cur.execute(
                    """INSERT INTO XT_KIOSK_PRODUKTE
                       (id, kategorie_id, einheit, wochentage, zutaten, aktiv, hinweis)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (artikel_id, data.get("kategorie_id"), data.get("einheit", "Stck."),
                     data.get("wochentage", ""), data.get("zutaten"),
                     data.get("aktiv", 1), data.get("hinweis")))
    except Exception as e:
        log.error("artikel_speichern ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True)


@app.route('/artikel/<int:artikel_id>/bild', methods=['POST'])
@_login_required
def artikel_bild_hochladen(artikel_id):
    """Bild für einen Artikel hochladen."""
    datei = request.files.get('bild')
    if not datei or not datei.filename:
        return jsonify(ok=False, msg='Keine Datei ausgewählt'), 400
    endung = datei.filename.rsplit('.', 1)[-1].lower() if '.' in datei.filename else ''
    if endung not in ERLAUBTE_BILD_ENDUNGEN:
        return jsonify(ok=False, msg=f"Nur {', '.join(sorted(ERLAUBTE_BILD_ENDUNGEN))} erlaubt"), 400
    datei.seek(0, 2)
    if datei.tell() > MAX_BILD_GROESSE:
        return jsonify(ok=False, msg='Datei zu groß (max. 5 MB)'), 400
    datei.seek(0)

    os.makedirs(PRODUKTBILDER_DIR, exist_ok=True)
    for alt_endung in ERLAUBTE_BILD_ENDUNGEN:
        alt_pfad = os.path.join(PRODUKTBILDER_DIR, f"{artikel_id}.{alt_endung}")
        if os.path.exists(alt_pfad):
            os.remove(alt_pfad)

    dateiname = f"{artikel_id}.{endung}"
    datei.save(os.path.join(PRODUKTBILDER_DIR, dateiname))

    bild_url_pfad = f"/produktbilder/{dateiname}"
    try:
        with get_db() as cur:
            cur.execute("SELECT id FROM XT_KIOSK_PRODUKTE WHERE id=%s", (artikel_id,))
            if cur.fetchone():
                cur.execute("UPDATE XT_KIOSK_PRODUKTE SET bild_pfad=%s WHERE id=%s",
                            (bild_url_pfad, artikel_id))
            else:
                cur.execute("INSERT INTO XT_KIOSK_PRODUKTE (id, bild_pfad, aktiv) VALUES (%s, %s, 1)",
                            (artikel_id, bild_url_pfad))
    except Exception as e:
        log.error("Bild-DB-Update ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, bild_url=bild_url_pfad)


@app.route('/artikel/<int:artikel_id>/bild', methods=['DELETE'])
@_login_required
def artikel_bild_loeschen(artikel_id):
    """Bild eines Artikels löschen."""
    geloescht = False
    for endung in ERLAUBTE_BILD_ENDUNGEN:
        pfad = os.path.join(PRODUKTBILDER_DIR, f"{artikel_id}.{endung}")
        if os.path.exists(pfad):
            os.remove(pfad)
            geloescht = True
    try:
        with get_db() as cur:
            cur.execute("UPDATE XT_KIOSK_PRODUKTE SET bild_pfad=NULL WHERE id=%s", (artikel_id,))
    except Exception as e:
        log.error("Bild-löschen DB ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, geloescht=geloescht)


@app.route('/artikel/bereinigen', methods=['POST'])
@_login_required
def artikel_bereinigen():
    """Verwaiste Kiosk-Produkte (ohne CAO-Artikel) entfernen."""
    with get_db() as cur:
        cur.execute("SELECT id FROM XT_KIOSK_V_VERWAISTE")
        ids = [r['id'] for r in cur.fetchall()]
        geloescht = 0
        for pid in ids:
            try:
                cur.execute("DELETE FROM XT_KIOSK_PRODUKTE WHERE id=%s", (pid,))
                geloescht += 1
            except Exception:
                pass
    return jsonify(ok=True, geloescht=geloescht)


@app.route('/produktbilder/<path:dateiname>')
def produktbild(dateiname):
    """Liefert Produktbilder (für Vorschau in der Admin)."""
    from flask import send_from_directory
    return send_from_directory(PRODUKTBILDER_DIR, dateiname)


# ── Phase F: Funktionen (Feature-Toggles) ─────────────────────────

@app.route('/funktionen')
@_login_required
def funktionen():
    return render_template('funktionen.html')


@app.get('/api/einstellungen')
@_login_required
def api_einstellungen_list():
    """Gibt alle Einstellungen als Dict zurück."""
    try:
        with get_db() as cur:
            cur.execute("SELECT schluessel, wert, beschreibung FROM XT_EINSTELLUNGEN")
            rows = cur.fetchall()
        return jsonify(ok=True, einstellungen={r['schluessel']: r for r in rows})
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.put('/api/einstellungen/<schluessel>')
@_login_required
def api_einstellung_setzen(schluessel: str):
    """Setzt eine Einstellung. Body: { "wert": "1" }"""
    d = request.get_json(force=True)
    wert = str(d.get('wert', ''))
    benutzer = session.get('login_name', '')
    try:
        with get_db() as cur:
            # Validierung: Parken kann nur deaktiviert werden, wenn kein Bon geparkt ist
            if schluessel == 'kiosk_parken_aktiv' and wert == '0':
                cur.execute(
                    "SELECT COUNT(*) AS n FROM XT_KIOSK_WARENKOERBE WHERE status='geparkt'"
                )
                if cur.fetchone()['n'] > 0:
                    return jsonify(ok=False,
                                   msg='Kann nicht deaktiviert werden: Es gibt noch geparkte Warenkörbe.'), 409
            if schluessel == 'kasse_parken_aktiv' and wert == '0':
                cur.execute(
                    "SELECT COUNT(*) AS n FROM XT_KASSE_VORGAENGE WHERE STATUS='GEPARKT'"
                )
                if cur.fetchone()['n'] > 0:
                    return jsonify(ok=False,
                                   msg='Kann nicht deaktiviert werden: Es gibt noch geparkte Bons.'), 409
            cur.execute(
                "UPDATE XT_EINSTELLUNGEN SET wert=%s, geaendert_von=%s WHERE schluessel=%s",
                (wert, benutzer, schluessel),
            )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase G: Feiertage (Personal-Modul) ──────────────────────────
#
# Verwaltet XT_PERSONAL_FEIERTAG (gesetzlich via holidays-Paket + manuell).
# Das aktive Bundesland liegt in XT_EINSTELLUNGEN.personal_bundesland.
#

BUNDESLAENDER = (
    ('BW', 'Baden-Wuerttemberg'), ('BY', 'Bayern'), ('BE', 'Berlin'),
    ('BB', 'Brandenburg'),        ('HB', 'Bremen'),  ('HH', 'Hamburg'),
    ('HE', 'Hessen'),             ('MV', 'Mecklenburg-Vorpommern'),
    ('NI', 'Niedersachsen'),      ('NW', 'Nordrhein-Westfalen'),
    ('RP', 'Rheinland-Pfalz'),    ('SL', 'Saarland'),
    ('SN', 'Sachsen'),            ('ST', 'Sachsen-Anhalt'),
    ('SH', 'Schleswig-Holstein'), ('TH', 'Thueringen'),
)


def _aktuelles_bundesland() -> str:
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT wert FROM XT_EINSTELLUNGEN WHERE schluessel='personal_bundesland'"
            )
            row = cur.fetchone()
            if row and row.get('wert'):
                return str(row['wert']).strip().upper()
    except Exception:
        pass
    return 'BY'


@app.route('/feiertage')
@_login_required
def feiertage():
    jahr_str = request.args.get('jahr', '')
    try:
        jahr = int(jahr_str) if jahr_str else datetime.now().year
    except (TypeError, ValueError):
        jahr = datetime.now().year
    bundesland = _aktuelles_bundesland()
    eintraege = []
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_AT
                     FROM XT_PERSONAL_FEIERTAG
                    WHERE YEAR(DATUM) = %s AND BUNDESLAND IN (%s, 'BUND')
                    ORDER BY DATUM, QUELLE='manuell' DESC, REC_ID""",
                (int(jahr), bundesland),
            )
            eintraege = cur.fetchall() or []
    except Exception as e:
        log.warning("Feiertage laden fehlgeschlagen: %s", e)
    return render_template(
        'feiertage.html',
        jahr=jahr,
        bundesland=bundesland,
        bundeslaender=BUNDESLAENDER,
        eintraege=eintraege,
    )


@app.post('/api/feiertage/bundesland')
@_login_required
def api_feiertage_bundesland():
    """Setzt das aktive Bundesland."""
    d = request.get_json(force=True)
    neu = str(d.get('bundesland', '')).strip().upper()
    if neu not in {k for k, _ in BUNDESLAENDER}:
        return jsonify(ok=False, msg='Unbekanntes Bundesland.'), 400
    benutzer = session.get('login_name', '')
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE XT_EINSTELLUNGEN SET wert=%s, geaendert_von=%s "
                " WHERE schluessel='personal_bundesland'",
                (neu, benutzer),
            )
        return jsonify(ok=True, bundesland=neu)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/feiertage/sync')
@_login_required
def api_feiertage_sync():
    """Synchronisiert gesetzliche Feiertage aus dem holidays-Paket fuer
    (jahr, aktuelles_bundesland). INSERT IGNORE – vorhandene Eintraege
    bleiben unveraendert."""
    d = request.get_json(force=True) or {}
    try:
        jahr = int(d.get('jahr') or datetime.now().year)
    except (TypeError, ValueError):
        return jsonify(ok=False, msg='Ungueltige Jahresangabe.'), 400
    bundesland = _aktuelles_bundesland()
    try:
        import holidays
    except ImportError:
        return jsonify(ok=False,
                       msg='Python-Paket "holidays" nicht installiert.'), 500
    try:
        try:
            kal = holidays.country_holidays('DE', subdiv=bundesland, years=jahr)
        except Exception:
            kal = holidays.country_holidays('DE', years=jahr)
        eingefuegt = 0
        with get_db_transaction() as cur:
            for tag, name in sorted(kal.items()):
                cur.execute(
                    """INSERT IGNORE INTO XT_PERSONAL_FEIERTAG
                         (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
                       VALUES (%s, %s, %s, 'paket', NULL)""",
                    (tag, str(name), bundesland),
                )
                eingefuegt += cur.rowcount
        return jsonify(ok=True, eingefuegt=eingefuegt, jahr=jahr, bundesland=bundesland)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/feiertage/manuell')
@_login_required
def api_feiertag_manuell_anlegen():
    """Legt einen manuellen Feiertag an. Body: {datum, name}"""
    d = request.get_json(force=True) or {}
    datum = str(d.get('datum', '')).strip()
    name = str(d.get('name', '')).strip()
    if not datum or not name:
        return jsonify(ok=False, msg='Datum und Name erforderlich.'), 400
    try:
        datetime.strptime(datum, '%Y-%m-%d')
    except ValueError:
        return jsonify(ok=False, msg='Datum im Format JJJJ-MM-TT angeben.'), 400
    bundesland = _aktuelles_bundesland()
    ma_id = session.get('ma_id') or 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                """INSERT INTO XT_PERSONAL_FEIERTAG
                     (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
                   VALUES (%s, %s, %s, 'manuell', %s)""",
                (datum, name, bundesland, int(ma_id)),
            )
        return jsonify(ok=True)
    except Exception as e:
        # Duplikat via UNIQUE-Key ist der haeufigste Fehler
        return jsonify(ok=False, msg=str(e)), 400


@app.delete('/api/feiertage/<int:rec_id>')
@_login_required
def api_feiertag_loeschen(rec_id: int):
    """Loescht einen manuellen Feiertag. Paket-Eintraege lassen sich
    so nicht entfernen (re-Sync wuerde sie ohnehin wiederherstellen)."""
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM XT_PERSONAL_FEIERTAG "
                " WHERE REC_ID=%s AND QUELLE='manuell'",
                (int(rec_id),),
            )
            anz = cur.rowcount
        if not anz:
            return jsonify(ok=False,
                           msg='Nicht gefunden oder kein manueller Eintrag.'), 404
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Benachrichtigungs-Empfaenger (E-Mails fuer Hinweis-Hooks) ────────

# Bereiche, fuer die aktuell Hinweis-Mails verschickt werden. Ergaenzend
# hinzufuegen, sobald eine neue Benachrichtigungs-Kategorie auftaucht.
BENACHRICHTIGUNG_BEREICHE: tuple[tuple[str, str], ...] = (
    ('abwesenheit_antrag',  'Abwesenheit: neuer Antrag vom MA'),
    ('urlaub_antrag',       'Urlaub: neuer Antrag vom MA'),
)


def _benachrichtigung_bereich_ok(bereich: str) -> bool:
    return bereich in {k for k, _ in BENACHRICHTIGUNG_BEREICHE}


@app.get('/benachrichtigungen')
@_login_required
def benachrichtigungen():
    eintraege = []
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, BEREICH, EMAIL, NAME, AKTIV, ERSTELLT_AT
                     FROM XT_BENACHRICHTIGUNG_EMPFAENGER
                    ORDER BY BEREICH, EMAIL"""
            )
            eintraege = cur.fetchall() or []
    except Exception as e:
        log.warning("Benachrichtigungs-Empfaenger laden fehlgeschlagen: %s", e)
    return render_template(
        'benachrichtigungen.html',
        bereiche=BENACHRICHTIGUNG_BEREICHE,
        eintraege=eintraege,
    )


@app.post('/api/benachrichtigungen')
@_login_required
def api_benachrichtigung_anlegen():
    d = request.get_json(force=True) or {}
    bereich = str(d.get('bereich', '')).strip()
    email = str(d.get('email', '')).strip()
    name = str(d.get('name', '')).strip() or None
    if not _benachrichtigung_bereich_ok(bereich):
        return jsonify(ok=False, msg='Unbekannter Bereich.'), 400
    if '@' not in email or len(email) > 150:
        return jsonify(ok=False, msg='Ungueltige E-Mail-Adresse.'), 400
    ma_id = session.get('ma_id') or 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                """INSERT INTO XT_BENACHRICHTIGUNG_EMPFAENGER
                     (BEREICH, EMAIL, NAME, ERSTELLT_VON)
                   VALUES (%s, %s, %s, %s)""",
                (bereich, email, name, int(ma_id) if ma_id else None),
            )
        return jsonify(ok=True)
    except Exception as e:
        # UNIQUE (BEREICH, EMAIL) ist der haeufige Fehlerfall
        return jsonify(ok=False, msg=str(e)), 400


@app.post('/api/benachrichtigungen/<int:rec_id>/aktiv')
@_login_required
def api_benachrichtigung_aktiv(rec_id: int):
    """Toggelt den AKTIV-Schalter eines Empfaengers."""
    d = request.get_json(force=True) or {}
    aktiv = 1 if d.get('aktiv') else 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "UPDATE XT_BENACHRICHTIGUNG_EMPFAENGER SET AKTIV=%s "
                " WHERE REC_ID=%s",
                (aktiv, int(rec_id)),
            )
            if cur.rowcount == 0:
                return jsonify(ok=False, msg='Nicht gefunden.'), 404
        return jsonify(ok=True, aktiv=aktiv)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.delete('/api/benachrichtigungen/<int:rec_id>')
@_login_required
def api_benachrichtigung_loeschen(rec_id: int):
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM XT_BENACHRICHTIGUNG_EMPFAENGER WHERE REC_ID=%s",
                (int(rec_id),),
            )
            if cur.rowcount == 0:
                return jsonify(ok=False, msg='Nicht gefunden.'), 404
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Handbuch ─────────────────────────────────────────────────────

@app.get('/admin/doku/<path:dateiname>')
@_login_required
def admin_doku_datei(dateiname):
    """Statische Dateien aus dem doku/-Verzeichnis (Bilder für Handbuch)."""
    return send_from_directory(os.path.abspath(_DOKU_DIR), dateiname)


@app.get('/admin/handbuch')
@_login_required
def admin_handbuch():
    """Mitarbeiter-Handbuch – alle eingeloggten User dürfen lesen,
    Administratoren dürfen bearbeiten."""
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


@app.post('/admin/handbuch/speichern')
@_login_required
def admin_handbuch_speichern():
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


@app.post('/admin/handbuch/upload')
@_login_required
def admin_handbuch_upload():
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
    return jsonify({'ok': True, 'filename': f'/admin/doku/{dateiname}'})


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

    # Aktuellen Branch ermitteln (Fallback: master)
    branch_r = _git('rev-parse', '--abbrev-ref', 'HEAD')
    branch = branch_r.stdout.strip() if branch_r.returncode == 0 else 'master'
    if not branch or branch == 'HEAD':
        branch = 'master'

    # git fetch
    fetch = _git('fetch', 'origin', branch)
    if fetch.returncode != 0:
        return jsonify({
            'error': f"git fetch fehlgeschlagen: {fetch.stderr.strip()}",
            'local_version': local_v,
        }), 200

    # Remote VERSION.json
    show = _git('show', f'origin/{branch}:VERSION.json')
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


# ── Zeiten-CSV Import (ShiftJuggler Attendance-Export) ───────────

@app.route('/zeiten-import', methods=['GET', 'POST'])
@_login_required
def zeiten_import():
    """Upload-Formular fuer eine ShiftJuggler-Attendance-CSV.

    GET  → Formular mit Format-Infos (Template: zeiten_import.html).
    POST → Datei parsen und entweder Dry-Run-Report oder scharf importieren.

    Der eigentliche Import liegt in
    ``modules.orga.personal.tools.import_zeiten`` – die Admin-App ruft
    ihn nur auf und zeigt den Report an.
    """
    if request.method == 'GET':
        return render_template('zeiten_import.html',
                               stats=None, dry_run=None, fehler=None)

    datei = request.files.get('csv')
    dry_run = bool(request.form.get('dry_run'))
    if not datei or not datei.filename:
        return render_template('zeiten_import.html',
                               stats=None, dry_run=dry_run,
                               fehler='Keine Datei ausgewaehlt.')

    import tempfile
    from modules.orga.personal.tools.import_zeiten import importiere_csv

    suffix = '.csv' if datei.filename.lower().endswith('.csv') else ''
    fd, tmp_path = tempfile.mkstemp(prefix='zeiten_import_', suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as fh:
            datei.save(fh)
        try:
            stats = importiere_csv(tmp_path,
                                   benutzer_ma_id=session['ma_id'],
                                   dry_run=dry_run)
        except Exception as e:
            log.warning("Zeiten-Import fehlgeschlagen: %s", e)
            return render_template('zeiten_import.html',
                                   stats=None, dry_run=dry_run,
                                   fehler=f'Import fehlgeschlagen: {e}')
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return render_template('zeiten_import.html',
                           stats=stats, dry_run=dry_run, fehler=None,
                           dateiname=datei.filename)


# ── Gemeinsame Brand-Assets (common/brand/*) ──────────────────
_BRAND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'brand')
)


@app.route('/brand/<path:dateiname>')
def _brand_asset(dateiname):
    """Liefert Dorfkern-Logo-Assets (dorfkern-logo.js etc.) aus common/brand/."""
    return send_from_directory(_BRAND_DIR, dateiname,
                               max_age=60 * 60 * 24)


# ── Legacy-Redirects (Dorfkern v2 Rename /verwaltung → /admin) ─
# Bestehende Bookmarks / Druck-QR-Codes treffen weiterhin auf /verwaltung/...
# Wir antworten 301 auf /admin/...  Soll in Dorfkern v2.1 entfernt werden.
@app.route('/verwaltung', defaults={'pfad': ''}, strict_slashes=False)
@app.route('/verwaltung/<path:pfad>')
def _legacy_verwaltung_redirect(pfad):
    ziel = '/admin' + (('/' + pfad) if pfad else '')
    if request.query_string:
        ziel += '?' + request.query_string.decode('utf-8', 'ignore')
    return redirect(ziel, code=301)


# ── App starten ──────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Admin-App startet auf %s:%s", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
