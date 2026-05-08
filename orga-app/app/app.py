"""
CAO-XT Orga-App – Flask-Hauptanwendung
Starten: cd orga-app/app && python3 app.py
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file, send_from_directory
from jinja2 import ChoiceLoader, FileSystemLoader
from datetime import datetime, date, timedelta, timezone
import base64
import io
import os
import subprocess
import sys
import logging
import config
import db as db_modul
import berichte as bericht_modul
import datev as datev_modul
from db import get_db, test_verbindung
from common.auth import (login_required as _login_required,
                         mitarbeiter_login as _mitarbeiter_login,
                         mitarbeiter_login_karte)
from common.permission import flask_helpers as _perm_flask_helpers

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False
# Fuer Blueprints (z.B. Stundenzettel-PDF im orga/personal-Modul), die den
# Firmennamen via current_app.config lesen moechten.
app.config['FIRMA_NAME'] = config.FIRMA_NAME

# Zusaetzliche Template-Quelle: common/templates/ fuer gemeinsame Widgets
# (Touch-Numpad/Keyboard/Datepicker). Wird mit App-eigenen Templates
# ueber ChoiceLoader kombiniert (App-Templates haben Vorrang).
_COMMON_TEMPLATES = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'templates')
)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(_COMMON_TEMPLATES),
])

# Gemeinsame Statik (common/static/*) – dorfkern.css et al.
from common.static_serving import register_common_static as _reg_common_static  # noqa: E402
_reg_common_static(app)

# Dorfkern-Permissions: Decorator + Jinja-Helper ``hat_recht``
_permission_required, _perm_ctx = _perm_flask_helpers()
app.context_processor(_perm_ctx)

# Pfad-Prefix -> Permission-Key fuer den Orga-before_request-Hook.
# Nur URL-Sektionen mit eigenem Permission-Objekt (Dashboard/Home
# zaehlen als 'orga.zugriff' und werden per Default gecheckt).
_ORGA_PERMISSION_MAP: list[tuple[str, str]] = [
    ('/orga/preispflege',                'orga.preispflege'),
    ('/orga/datev-export',               'orga.datev_export'),
    ('/orga/personal/schichtplan',       'orga.schichtplan'),
    ('/orga/personal/schicht',           'orga.personal.schichten'),
    ('/orga/personal/abwesenheiten',     'orga.personal.abwesenheiten'),
    ('/orga/personal/arbeitszeitkonten', 'orga.personal.arbeitszeitkonten'),
    ('/orga/personal',                   'orga.personal.mitarbeiter'),
    ('/orga/haccp',                      'orga.haccp'),
    ('/orga/handbuch',                   'orga.handbuch'),
    ('/orga',                            'orga.artikel'),
    ('/reporting',                       'orga.reporting'),
]

# Pfade ohne Permission-Check (Login, statische Ressourcen, API-Utility)
_ORGA_PERMISSION_WHITELIST: tuple[str, ...] = (
    '/login', '/logout',
    '/brand/', '/static/',
    '/coming-soon',    # Platzhalter, unnoetig zu blocken
)


@app.before_request
def _orga_permission_guard():
    from flask import request, session, redirect, url_for, flash, jsonify
    path = request.path or ''
    if any(path.startswith(w) for w in _ORGA_PERMISSION_WHITELIST):
        return None
    ma_id = session.get('ma_id')
    if not ma_id:
        return None
    from common import permission as _p
    # HTTP-Methode bestimmt LESEN vs. PFLEGEN fuer LESE_PFLEGE-Objekte:
    # GET/HEAD/OPTIONS -> LESEN, alles andere -> PFLEGEN.
    is_read = request.method in ('GET', 'HEAD', 'OPTIONS')
    lese_pflege_keys = {'orga.schichtplan'}

    # Spezifische Sektionen first-match
    for prefix, key in _ORGA_PERMISSION_MAP:
        if path.startswith(prefix):
            if key in lese_pflege_keys:
                recht = 'LESEN' if is_read else 'PFLEGEN'
            else:
                recht = 'BEIDES'
            if _p.hat_recht(ma_id, key, recht):
                return None
            return _orga_verweigern(path, f'{key} ({recht})')
    # Default: jeder angemeldete MA braucht orga.zugriff
    if _p.hat_recht(ma_id, 'orga.zugriff'):
        return None
    return _orga_verweigern(path, 'orga.zugriff')


def _orga_verweigern(path: str, key: str):
    from flask import request, redirect, url_for, flash, jsonify
    if path.startswith('/api/') or \
            'application/json' in (request.headers.get('Accept', '') or ''):
        return jsonify(ok=False,
                       msg=f'Keine Berechtigung fuer {key}'), 403
    flash(f'Keine Berechtigung ({key}).', 'error')
    try:
        return redirect(url_for('index'))
    except Exception:
        return redirect('/')


def _fmt_eur(value, dp=2):
    """Zahl als deutsche Währungsangabe formatieren: 1.234,56"""
    try:
        v = float(value)
        formatted = f'{v:,.{dp}f}'   # US: "1,234,567.89"
        # Komma→Tausenderpunkt, Punkt→Dezimalkomma
        return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return str(value)

import json as _json
app.jinja_env.filters['eur'] = _fmt_eur
app.jinja_env.filters['zip'] = lambda a, b: list(zip(a, b))
app.jinja_env.filters['fromjson'] = lambda s: _json.loads(s) if s else {}


@app.before_request
def _sync_mitarbeiter_session():
    """session['mitarbeiter'] sicherstellen wenn eingeloggt.
    Orga-Blueprint prüft diesen Key; bei Sessions ohne mitarbeiter-Key
    (z.B. Altdaten vor Migration) wird er aus login_name ergaenzt."""
    if session.get('ma_id') and not session.get('mitarbeiter'):
        session['mitarbeiter'] = session.get('login_name', '')


# ── Orga-Blueprint einbinden ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', '..', 'modules', 'orga'))
try:
    import routes as orga_routes
    app.register_blueprint(orga_routes.bp, url_prefix='/orga')
    log.info("Orga-Blueprint registriert.")
except Exception as e:
    log.warning("Orga-Blueprint konnte nicht geladen werden: %s", e)

try:
    from modules.orga.personal import create_blueprint as _personal_bp
    app.register_blueprint(_personal_bp(), url_prefix='/orga/personal')
    log.info("Orga-Personal-Blueprint registriert.")
except Exception as e:
    log.warning("Orga-Personal-Blueprint konnte nicht geladen werden: %s", e)

try:
    from modules.orga.bestellwesen import create_blueprint as _bw_bp
    app.register_blueprint(_bw_bp(), url_prefix='/orga/bestellwesen')
    log.info("Orga-Bestellwesen-Blueprint registriert.")
    # Einmalige Migration: alte EKBESTELL_POS.STADIUM=0 → 2 fuer
    # offene Bestellungen heilen (Spiegel zum 2026-05-08-Sync-Fix).
    # Idempotent — nach erstem Lauf gibt es keine STADIUM=0 mehr.
    try:
        from modules.orga.bestellwesen.models import heile_alte_positions_stadium
        ergebnis = heile_alte_positions_stadium()
        if ergebnis.get('geheilt'):
            log.info("EKBESTELL_POS-Migration: %s Positionen STADIUM 0->2",
                     ergebnis['geheilt'])
    except Exception as e:
        log.warning("EKBESTELL_POS-Migration uebersprungen: %s", e)
except Exception as e:
    log.warning("Orga-Bestellwesen-Blueprint konnte nicht geladen werden: %s", e)

try:
    from modules.haccp import create_blueprint as _haccp_bp
    app.register_blueprint(_haccp_bp(), url_prefix='/orga/haccp')
    log.info("HACCP-Blueprint registriert.")
except Exception as e:
    log.warning("HACCP-Blueprint konnte nicht geladen werden: %s", e)


# ── Git-Commit-Hash (einmalig beim Start) ─────────────────────
try:
    _r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=5, cwd=BASE_DIR,
    )
    GIT_COMMIT_SHORT = _r.stdout.strip() if _r.returncode == 0 else ""
except Exception:
    GIT_COMMIT_SHORT = ""


# ── Context-Processor ─────────────────────────────────────────

@app.context_processor
def _inject_globals():
    kasse_url = config.KASSE_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
        if config.KASSE_PORT else '')
    kiosk_url = config.KIOSK_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
        if config.KIOSK_PORT else '')
    admin_url = config.ADMIN_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.ADMIN_PORT}'
        if config.ADMIN_PORT else '')
    # Feature-Gating (Phase 7): deaktivierte Apps aus Switcher ausblenden.
    try:
        from common import aktivierung as _akt
        if not _akt.ist_aktiv('KASSE'): kasse_url = ''
        if not _akt.ist_aktiv('KIOSK'): kiosk_url = ''
    except Exception:
        pass
    return {
        "firma_name":      config.FIRMA_NAME,
        "kasse_url":       kasse_url,
        "kiosk_url":       kiosk_url,
        "admin_url":  admin_url,
        "db_ok":           test_verbindung(),
        "current_user":  {
            "ma_id":      session.get('ma_id'),
            "login_name": session.get('login_name'),
            "vname":      session.get('vname'),
            "name":       session.get('ma_name'),
        } if session.get('ma_id') else None,
        "git_commit_short": GIT_COMMIT_SHORT,
    }


# ── Dashboard-Abfragen ────────────────────────────────────────

_DE_MONATE = ['Jan','Feb','Mär','Apr','Mai','Jun',
              'Jul','Aug','Sep','Okt','Nov','Dez']


def _de_monat_label(monat: str) -> str:
    """'2026-03' → 'Mär 2026' (deutsch)"""
    try:
        y, m = monat.split('-')
        return f"{_DE_MONATE[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return monat


def _monatsumsatz_6_monate() -> list[dict]:
    """Monatsumsatz (Brutto) der letzten 6 Monate aus CAO-Journal.
    Quelle: JOURNAL mit QUELLE=3 (Kasse) und QUELLE_SUB=2 (Kassenbuchung),
    gemäß CFO-Analyse (HAB-15).
    """
    sql = """
        SELECT
            DATE_FORMAT(j.RDATUM, '%Y-%m') AS monat,
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
            rows = cur.fetchall()
        return [dict(r, label=_de_monat_label(r['monat'])) for r in rows]
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
    from common.auth import login_user, logout_user
    ma = _mitarbeiter_login(login_name, passwort)
    if ma:
        login_user(ma)
        session['mitarbeiter'] = ma['LOGIN_NAME']   # für Orga-Blueprint
        return redirect(url_for('dashboard'))
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.post('/login/karte')
def login_karte():
    """Login per Mitarbeiter-Karte (Barcode-Scan)."""
    from common.auth import login_user
    guid = request.form.get('guid', '').strip()
    if not guid:
        return render_template('login.html', fehler='Kein Barcode erkannt.')
    ma = mitarbeiter_login_karte(guid)
    if ma:
        login_user(ma)
        session['mitarbeiter'] = ma['LOGIN_NAME']
        return redirect(url_for('dashboard'))
    return render_template('login.html',
                           fehler='Karte nicht erkannt oder keine Mitarbeiterkarte.')


@app.get('/logout')
def logout():
    from common.auth import logout_user
    logout_user()
    return redirect(url_for('login'))


# ── Routen ───────────────────────────────────────────────────

@app.route('/')
@_login_required
def dashboard():
    monatsumsatz   = _monatsumsatz_6_monate()
    tageseinnahmen = _tageseinnahmen_heute()
    offene_vorgaenge = _offene_vorgaenge()
    # HACCP-Ampeln: Temperaturstatus + Sichtkontrolle.
    # Bei Fehler (DB weg, HACCP-Tabellen fehlen) nicht das Dashboard sprengen.
    try:
        from modules.haccp import models as haccp_models
        haccp = haccp_models.status_fuer_dashboard(datetime.now(timezone.utc).replace(tzinfo=None))
    except Exception as e:
        log.warning('HACCP-Status fuer Dashboard nicht ladbar: %s', e)
        haccp = None
    # Personal-Widget: Abwesenheiten heute + offene Urlaubsantraege.
    try:
        from modules.orga.personal import models as personal_models
        personal = personal_models.status_fuer_dashboard(date.today())
    except Exception as e:
        log.warning('Personal-Status fuer Dashboard nicht ladbar: %s', e)
        personal = None
    return render_template(
        'dashboard.html',
        monatsumsatz=monatsumsatz,
        tageseinnahmen=tageseinnahmen,
        offene_vorgaenge=offene_vorgaenge,
        haccp=haccp,
        personal=personal,
        heute=date.today().strftime('%d.%m.%Y'),
    )


@app.route('/coming-soon')
@_login_required
def coming_soon():
    modul = request.args.get('modul', 'Dieses Modul')
    return render_template('coming_soon.html', modul=modul)


@app.route('/orga', strict_slashes=False)
@_login_required
def artikel():
    """Artikel-Übersicht und Preispflege (Stammdaten)."""
    return render_template('artikel.html')


@app.route('/orga/preispflege')
@_login_required
def preispflege():
    """Preispflege-Tabelle: EK / VK5 / Faktor für alle aktiven Artikel (N/F/S)."""
    return render_template('preispflege.html')


# ── Reporting ─────────────────────────────────────────────────

def _mwst_monatlich(monate: int = 12) -> list[dict]:
    """MwSt-Aufschlüsselung pro Monat (letzte N Monate) aus JOURNAL."""
    sql = """
        SELECT
            DATE_FORMAT(j.RDATUM, '%Y-%m')  AS monat,
            COUNT(DISTINCT j.REC_ID)        AS belege,
            ROUND(SUM(j.NSUMME_1), 2)       AS netto_19,
            ROUND(SUM(j.NSUMME_2), 2)       AS netto_7,
            ROUND(SUM(j.MSUMME_1), 2)       AS mwst_19,
            ROUND(SUM(j.MSUMME_2), 2)       AS mwst_7,
            ROUND(SUM(j.BSUMME),   2)       AS brutto
        FROM JOURNAL j
        WHERE j.QUELLE = 3
          AND j.QUELLE_SUB = 2
          AND j.RDATUM >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY DATE_FORMAT(j.RDATUM, '%Y-%m')
        ORDER BY monat DESC
    """
    try:
        with get_db() as cur:
            cur.execute(sql, (monate,))
            rows = cur.fetchall()
        return [dict(r, label=_de_monat_label(r['monat'])) for r in rows]
    except Exception as e:
        log.warning("MwSt-Abfrage fehlgeschlagen: %s", e)
        return []


def _warengruppen_namen() -> dict[int, str]:
    """Lädt alle Warengruppen-Namen aus der WARENGRUPPEN-Tabelle.
    Gibt ein Dict {wgr_id: name} zurück; bei Fehler ein leeres Dict.
    """
    try:
        with get_db() as cur:
            cur.execute("SELECT `ID` AS wgr_id, `NAME` AS wgr_name FROM `WARENGRUPPEN`")
            return {int(r['wgr_id']): r['wgr_name'] for r in cur.fetchall() if r['wgr_name']}
    except Exception as e:
        log.warning("Warengruppen-Namen nicht ladbar: %s", e)
        return {}


def _umsatz_warengruppen(monat: str) -> list[dict]:
    """Umsatz und COGS nach Warengruppen für einen Monat (YYYY-MM).
    COGS = SUM(MENGE × jp.EK_PREIS) direkt aus JOURNALPOS.
    Einträge mit EK_PREIS=0 tragen 0 zum COGS bei (neue Kassen-App-Buchungen).
    """
    sql = """
        SELECT
            COALESCE(jp.WARENGRUPPE, 0)                           AS wgr_id,
            COALESCE(ROUND(SUM(jp.GPREIS), 2), 0)                AS umsatz_brutto,
            COALESCE(ROUND(SUM(jp.MENGE * jp.EK_PREIS), 2), 0)  AS cogs
        FROM JOURNALPOS jp
        JOIN JOURNAL j ON jp.JOURNAL_ID = j.REC_ID
        WHERE j.QUELLE     = 3
          AND j.QUELLE_SUB = 2
          AND DATE_FORMAT(j.RDATUM, '%Y-%m') = %s
        GROUP BY jp.WARENGRUPPE
        ORDER BY umsatz_brutto DESC
    """
    try:
        with get_db() as cur:
            cur.execute(sql, (monat,))
            rows = cur.fetchall()
        namen = _warengruppen_namen()
        return [
            {
                'kategorie':     namen.get(int(r['wgr_id'])) or f"WGR {r['wgr_id']}",
                'umsatz_brutto': float(r['umsatz_brutto']),
                'cogs':          float(r['cogs']),
            }
            for r in rows
        ]
    except Exception as e:
        log.warning("Warengruppen-Abfrage fehlgeschlagen: %s", e)
        return []


def _finance_kpis() -> dict:
    """Finance-KPIs für laufenden und Vormonat aus JOURNAL.

    Berechnet: Brutto-Umsatz, Beleganzahl, Tages-Ø, MwSt-Quote 7%/19%,
    Monats-Ø der letzten 6 Monate.
    Bruttomarge und Wareneinsatzquote werden als Platzhalter zurückgegeben
    (erfordern manuelle COGS-Eingabe).
    """
    sql_monat_akt = """
        SELECT
            COUNT(DISTINCT j.REC_ID)  AS belege,
            ROUND(SUM(j.BSUMME), 2)   AS brutto,
            ROUND(SUM(j.NSUMME_2 + j.MSUMME_2), 2) AS brutto_7,
            ROUND(SUM(j.NSUMME_1 + j.MSUMME_1), 2) AS brutto_19,
            COUNT(DISTINCT DATE(j.RDATUM)) AS tage
        FROM JOURNAL j
        WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2
          AND DATE_FORMAT(j.RDATUM, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m')
    """
    sql_monat_vor = """
        SELECT
            COUNT(DISTINCT j.REC_ID)  AS belege,
            ROUND(SUM(j.BSUMME), 2)   AS brutto,
            ROUND(SUM(j.NSUMME_2 + j.MSUMME_2), 2) AS brutto_7,
            ROUND(SUM(j.NSUMME_1 + j.MSUMME_1), 2) AS brutto_19,
            COUNT(DISTINCT DATE(j.RDATUM)) AS tage
        FROM JOURNAL j
        WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2
          AND DATE_FORMAT(j.RDATUM, '%Y-%m') = DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m')
    """
    sql_avg6 = """
        SELECT ROUND(AVG(monat_brutto), 2) AS avg_6
        FROM (
            SELECT DATE_FORMAT(j.RDATUM, '%Y-%m') AS m,
                   SUM(j.BSUMME) AS monat_brutto
            FROM JOURNAL j
            WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2
              AND j.RDATUM >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY DATE_FORMAT(j.RDATUM, '%Y-%m')
        ) t
    """
    try:
        with get_db() as cur:
            cur.execute(sql_monat_akt)
            akt = cur.fetchone() or {}
            cur.execute(sql_monat_vor)
            vor = cur.fetchone() or {}
            cur.execute(sql_avg6)
            avg_row = cur.fetchone() or {}
        brutto_akt  = float(akt.get('brutto')  or 0)
        brutto_vor  = float(vor.get('brutto')  or 0)
        tage_akt    = int(akt.get('tage')     or 1)
        brutto_7    = float(akt.get('brutto_7') or 0)
        brutto_19   = float(akt.get('brutto_19') or 0)
        avg_6       = float(avg_row.get('avg_6') or 0)
        abw_pct = round((brutto_akt - brutto_vor) / brutto_vor * 100, 1) if brutto_vor else None
        return {
            'brutto_akt':    brutto_akt,
            'brutto_vor':    brutto_vor,
            'abw_pct':       abw_pct,
            'tages_avg':     round(brutto_akt / tage_akt, 2) if tage_akt else 0,
            'belege_akt':    int(akt.get('belege') or 0),
            'mwst7_anteil':  round(brutto_7  / brutto_akt * 100, 1) if brutto_akt else 0,
            'mwst19_anteil': round(brutto_19 / brutto_akt * 100, 1) if brutto_akt else 0,
            'avg_6':         avg_6,
        }
    except Exception as e:
        log.warning("Finance-KPI-Abfrage fehlgeschlagen: %s", e)
        return {}


@app.route('/reporting')
@_login_required
def reporting():
    from datetime import date
    mwst_daten   = _mwst_monatlich(12)
    monate_liste  = [r['monat'] for r in mwst_daten]
    monat_labels  = {r['monat']: r['label'] for r in mwst_daten}
    # Monat-Parameter: URL-Param bevorzugen, sonst letzten abgeschlossenen Monat nehmen.
    # Laufender Monat wird übersprungen, da JOURNALPOS dort oft noch leer ist,
    # auch wenn JOURNAL bereits Einträge enthält.
    akt_monat   = date.today().strftime('%Y-%m')
    monat_param = request.args.get('monat', '')
    if not monat_param or monat_param not in monate_liste:
        abgeschlossen = [m for m in monate_liste if m < akt_monat]
        monat_param = abgeschlossen[0] if abgeschlossen else (
            monate_liste[0] if monate_liste else akt_monat
        )
    warengruppen = _umsatz_warengruppen(monat_param)
    kpis         = _finance_kpis()
    return render_template(
        'reporting.html',
        mwst_daten=mwst_daten,
        warengruppen=warengruppen,
        kpis=kpis,
        monat_param=monat_param,
        monate_liste=monate_liste,
        monat_labels=monat_labels,
        heute=date.today().strftime('%d.%m.%Y'),
    )


@app.route('/api/status')
@_login_required
def api_status():
    return jsonify({
        'app': 'orga-app',
        'db':  test_verbindung(),
        'ts':  datetime.now().isoformat(),
    })


# ── CFO-Berichte ──────────────────────────────────────────────

def _parse_datum(s: str | None, fallback: date) -> date:
    """Parst YYYY-MM-DD oder gibt fallback zurück."""
    if s:
        try:
            return date.fromisoformat(s)
        except ValueError:
            pass
    return fallback


@app.get('/orga/berichte')
def berichte_seite():
    """Übersichtsseite CFO-Berichte."""
    return render_template('berichte.html')


# ── Tagesumsatz ────────────────────────────────────────────────

@app.get('/orga/berichte/tagesumsatz')
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


@app.get('/orga/berichte/tagesumsatz/export')
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

@app.get('/orga/berichte/monatsuebersicht')
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


@app.get('/orga/berichte/monatsuebersicht/export')
def monatsuebersicht_export():
    """Monatsübersicht als CSV."""
    jahr   = int(request.args.get('jahr', date.today().year))
    inhalt = bericht_modul.monatsuebersicht_csv(jahr)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'monatsuebersicht_{jahr}.csv')


# ── Kassenbuch ─────────────────────────────────────────────────

@app.get('/orga/berichte/kassenbuch')
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


@app.get('/orga/berichte/kassenbuch/export')
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

@app.get('/orga/berichte/ec-umsaetze')
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


@app.get('/orga/berichte/ec-umsaetze/export')
def ec_umsaetze_export():
    """EC-Umsätze als CSV."""
    heute = date.today()
    von   = _parse_datum(request.args.get('von'), heute.replace(day=1))
    bis   = _parse_datum(request.args.get('bis'), heute)
    inhalt = bericht_modul.ec_umsaetze_csv(von, bis)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'ec_umsaetze_{von}_{bis}.csv')


# ── Stunden-Heatmap (Umsatz je Wochentag × Stunde) ─────────────

@app.get('/orga/berichte/umsatz-heatmap')
def umsatz_heatmap_seite():
    """Heatmap: durchschnittlicher Umsatz pro (Wochentag x Stunde) im
    angegebenen Zeitraum. Standard: aktuelle KW + letzte 4 vollstaendige
    Kalenderwochen, um saisonale Effekte abzumildern.
    """
    heute = date.today()
    # Default: letzte 4 vollstaendige Wochen + diese Woche bis heute
    default_von = heute - timedelta(days=heute.weekday() + 4 * 7)
    von = _parse_datum(request.args.get('von'), default_von)
    bis = _parse_datum(request.args.get('bis'), heute)
    try:
        heatmap = bericht_modul.umsatz_heatmap(von, bis)
    except Exception as e:
        log.exception("Umsatz-Heatmap-Fehler")
        heatmap = None
        flash(f'Datenbankfehler: {e}', 'error')
    return render_template('berichte.html', bericht='umsatz_heatmap',
                           heatmap=heatmap, von=von, bis=bis)


@app.get('/orga/berichte/umsatz-heatmap/export')
def umsatz_heatmap_export():
    heute = date.today()
    default_von = heute - timedelta(days=heute.weekday() + 4 * 7)
    von = _parse_datum(request.args.get('von'), default_von)
    bis = _parse_datum(request.args.get('bis'), heute)
    inhalt = bericht_modul.umsatz_heatmap_csv(von, bis)
    return send_file(io.BytesIO(inhalt), mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'umsatz_heatmap_{von}_{bis}.csv')


# ── Koppelkauf-Analyse ─────────────────────────────────────────

try:
    import koppelkauf as koppelkauf_modul
except ImportError as _koppelkauf_exc:
    # Koppelkauf-Modul ist optional / WIP. Fehler nur loggen; die Route
    # selbst antwortet mit Fehlermeldung wenn tatsaechlich aufgerufen.
    koppelkauf_modul = None
    log.warning("Koppelkauf-Modul nicht verfuegbar: %s. "
                "Route /orga/berichte/koppelkauf liefert Platzhalter.",
                _koppelkauf_exc)


@app.get('/orga/berichte/koppelkauf')
def koppelkauf_seite():
    """Koppelkauf-Analyse: Auswahlseite oder Analyseergebnis."""
    if koppelkauf_modul is None:
        flash('Koppelkauf-Modul ist auf diesem Server nicht verfuegbar.',
              'error')
        return redirect(url_for('index'))
    artnum     = request.args.get('artnum', '').strip()
    von_str    = request.args.get('von', '')
    bis_str    = request.args.get('bis', '')
    stichtag_s = request.args.get('stichtag', '')

    stichtag = _parse_datum(stichtag_s, date.today()) if stichtag_s else None

    try:
        aktionen = koppelkauf_modul.aktionsartikel_liste(stichtag=stichtag)
    except Exception as e:
        log.warning("Aktionsliste fehlgeschlagen: %s", e)
        aktionen = []

    if not artnum:
        return render_template('koppelkauf.html',
                               aktionen=aktionen,
                               stichtag=stichtag_s,
                               analyse=None, aktion_info=None)

    try:
        aktion_info = koppelkauf_modul.aktionszeitraum_holen(artnum, stichtag)
    except Exception as e:
        log.exception("Aktionszeitraum-Abfrage fehlgeschlagen")
        flash(f'Datenbankfehler: {e}', 'error')
        return render_template('koppelkauf.html',
                               aktionen=aktionen,
                               stichtag=stichtag_s,
                               analyse=None, aktion_info=None)

    if not aktion_info and not (von_str and bis_str):
        flash('Kein Aktionszeitraum gefunden. Bitte Zeitraum manuell angeben.', 'warn')
        return render_template('koppelkauf.html',
                               aktionen=aktionen,
                               stichtag=stichtag_s,
                               analyse=None, aktion_info=None,
                               artnum_vorgabe=artnum)

    if von_str and bis_str:
        aktions_von = _parse_datum(von_str, date.today())
        aktions_bis = _parse_datum(bis_str, date.today())
    elif aktion_info:
        aktions_von = aktion_info['datum_ab']
        aktions_bis = aktion_info['datum_bis'] or date.today()
    else:
        aktions_von = aktions_bis = date.today()

    try:
        # Preise (Aktion vs. Normal) fuer die Margen-/Rabatt-Analyse mitgeben.
        aktionspreis = (aktion_info or {}).get('aktions_preis')
        normalpreis  = (aktion_info or {}).get('normal_preis')
        analyse = koppelkauf_modul.analyse_komplett(
            artnum, aktions_von, aktions_bis,
            aktionspreis=aktionspreis, normalpreis=normalpreis)
    except Exception as e:
        log.exception("Koppelkauf-Analyse fehlgeschlagen")
        flash(f'Datenbankfehler bei der Analyse: {e}', 'error')
        analyse = None

    return render_template('koppelkauf.html',
                           aktionen=aktionen,
                           stichtag=stichtag_s,
                           aktion_info=aktion_info,
                           analyse=analyse,
                           artnum=artnum,
                           aktions_von=aktions_von,
                           aktions_bis=aktions_bis)


# ── DATEV-Export ──────────────────────────────────────────────

@app.get('/orga/datev-export')
@_login_required
def datev_seite():
    """DATEV-Export: Hauptseite mit Formular und Dateiliste."""
    heute = date.today()
    # Standardmäßig den Vormonat vorschlagen
    if heute.month == 1:
        monat, jahr = 12, heute.year - 1
    else:
        monat, jahr = heute.month - 1, heute.year
    dateien = datev_modul.datev_dateien_auflisten()
    return render_template('datev_export.html',
                           monat=monat, jahr=jahr,
                           dateien=dateien,
                           vorschau_spalten=None, vorschau_zeilen=None,
                           vorschau_datei=None,
                           erfolg=None, fehler=None)


@app.post('/orga/datev-export/generieren')
@_login_required
def datev_generieren():
    """DATEV-Export auslösen und Ergebnis anzeigen."""
    monat = int(request.form.get('monat', 0))
    jahr  = int(request.form.get('jahr', 0))

    filepath, anzahl, fehler_msg = datev_modul.datev_export_ausfuehren(jahr, monat)
    dateien = datev_modul.datev_dateien_auflisten()

    erfolg = None
    fehler = None
    vorschau_spalten = None
    vorschau_zeilen = None
    vorschau_datei = None

    if filepath:
        erfolg = f'Export erstellt: {filepath.name} ({anzahl} Buchungszeilen)'
        # Direkt Vorschau der neuen Datei zeigen
        vorschau_spalten, vorschau_zeilen, _ = datev_modul.datev_datei_lesen(filepath.name)
        vorschau_datei = filepath.name
    else:
        fehler = fehler_msg

    return render_template('datev_export.html',
                           monat=monat, jahr=jahr,
                           dateien=dateien,
                           vorschau_spalten=vorschau_spalten,
                           vorschau_zeilen=vorschau_zeilen,
                           vorschau_datei=vorschau_datei,
                           erfolg=erfolg, fehler=fehler)


@app.get('/orga/datev-export/vorschau/<filename>')
@_login_required
def datev_vorschau(filename):
    """Tabellarische Vorschau einer DATEV-Export-Datei."""
    spalten, zeilen, fehler_msg = datev_modul.datev_datei_lesen(filename)

    heute = date.today()
    if heute.month == 1:
        monat, jahr = 12, heute.year - 1
    else:
        monat, jahr = heute.month - 1, heute.year
    dateien = datev_modul.datev_dateien_auflisten()

    return render_template('datev_export.html',
                           monat=monat, jahr=jahr,
                           dateien=dateien,
                           vorschau_spalten=spalten if spalten else None,
                           vorschau_zeilen=zeilen if zeilen else None,
                           vorschau_datei=filename,
                           erfolg=None,
                           fehler=fehler_msg if fehler_msg else None)


@app.get('/orga/datev-export/download/<filename>')
@_login_required
def datev_download(filename):
    """DATEV-Export-Datei herunterladen."""
    filepath = datev_modul.datev_datei_pfad(filename)
    if not filepath:
        flash('Datei nicht gefunden.', 'error')
        return redirect(url_for('datev_seite'))
    return send_file(filepath, mimetype='text/csv',
                     as_attachment=True, download_name=filename)


# ── Handbuch (Benutzerhandbuch) ──────────────────────────────

_DOKU_DIR = os.path.join(os.path.dirname(__file__), 'doku')
# Beispiele/Mockups liegen im Repo unter docs/mockups/ – dort werden
# sie weiter gepflegt, ohne dass wir sie in orga-app/app/doku
# duplizieren muessen.
_MOCKUPS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'docs', 'mockups'))


@app.get('/orga/doku/<path:dateiname>')
@_login_required
def orga_doku_datei(dateiname):
    """Statische Dateien aus dem doku/-Verzeichnis (Bilder für Handbuch)."""
    return send_from_directory(os.path.abspath(_DOKU_DIR), dateiname)


@app.get('/orga/beispiele/<path:dateiname>')
@_login_required
def orga_beispiel_datei(dateiname):
    """Liefert die Mockup-/Beispieldateien aus docs/mockups/ aus, damit
    das Handbuch sie als realistische Demos verlinken kann (z.B.
    Koppelkauf-Erfolg vs. -Flop). Whitelist-Schutz: nur Dateien direkt
    in docs/mockups/, keine Subordner-Traversal."""
    if '..' in dateiname or '/' in dateiname or '\\' in dateiname:
        return 'Ungueltiger Pfad.', 400
    return send_from_directory(_MOCKUPS_DIR, dateiname)


@app.get('/orga/handbuch')
@_login_required
def orga_handbuch():
    """Benutzerhandbuch – alle eingeloggten User dürfen lesen,
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


@app.post('/orga/handbuch/speichern')
@_login_required
def orga_handbuch_speichern():
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


@app.post('/orga/handbuch/upload')
@_login_required
def orga_handbuch_upload():
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
    return jsonify({'ok': True, 'filename': f'/orga/doku/{dateiname}'})


# ── Gemeinsame Brand-Assets (common/brand/*) ──────────────────
_BRAND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'brand')
)


@app.route('/brand/<path:dateiname>')
def _brand_asset(dateiname):
    """Liefert Dorfkern-Logo-Assets (dorfkern-logo.js etc.) aus common/brand/."""
    return send_from_directory(_BRAND_DIR, dateiname,
                               max_age=60 * 60 * 24)  # 1 Tag Cache


# ── Legacy-Redirects (Dorfkern v2 Rename /wawi → /orga) ──────
# Bestehende Bookmarks / Druck-QR-Codes / Verweise aus CAO-Reports
# treffen weiterhin auf /wawi/... – wir antworten 301 auf /orga/...
# Soll in Dorfkern v2.1 entfernt werden.
@app.route('/wawi', defaults={'pfad': ''}, strict_slashes=False)
@app.route('/wawi/<path:pfad>')
def _legacy_wawi_redirect(pfad):
    ziel = '/orga' + (('/' + pfad) if pfad else '')
    if request.query_string:
        ziel += '?' + request.query_string.decode('utf-8', 'ignore')
    return redirect(ziel, code=301)


# ── Start ────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Orga-App startet auf %s:%s (debug=%s)", config.HOST, config.PORT, config.DEBUG)
    # Terminal-Selbstregistrierung (Phase 9).
    try:
        from common.terminal_selbstregistrierung import selbst_registrieren
        selbst_registrieren('ORGA')
    except Exception:
        pass
    if config.DEBUG:
        # Dev: Werkzeug-Dev-Server mit Auto-Reloader + Debugger
        app.run(host=config.HOST, port=config.PORT, debug=True)
    else:
        # Prod: Waitress – stabiler Threaded-WSGI-Server ohne Reloader.
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT,
              threads=8, ident='cao-xt')
