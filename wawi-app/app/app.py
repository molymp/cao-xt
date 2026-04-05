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


def _fmt_eur(value, dp=2):
    """Zahl als deutsche Währungsangabe formatieren: 1.234,56"""
    try:
        v = float(value)
        formatted = f'{v:,.{dp}f}'   # US: "1,234,567.89"
        # Komma→Tausenderpunkt, Punkt→Dezimalkomma
        return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    except (TypeError, ValueError):
        return str(value)

app.jinja_env.filters['eur'] = _fmt_eur


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


@app.route('/wawi', strict_slashes=False)
@_login_required
def artikel():
    """Artikel-Übersicht und Preispflege (Stammdaten)."""
    return render_template('artikel.html')


# ── Reporting ─────────────────────────────────────────────────

def _mwst_monatlich(monate: int = 12) -> list[dict]:
    """MwSt-Aufschlüsselung pro Monat (letzte N Monate) aus JOURNAL."""
    sql = """
        SELECT
            DATE_FORMAT(j.RDATUM, '%Y-%m')  AS monat,
            DATE_FORMAT(j.RDATUM, '%b %Y')  AS label,
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
            return cur.fetchall()
    except Exception as e:
        log.warning("MwSt-Abfrage fehlgeschlagen: %s", e)
        return []


def _umsatz_warengruppen(monat: str) -> list[dict]:
    """Umsatz nach Warengruppen für einen Monat (YYYY-MM) via JOURNALPOS + WARENGRUPPEN.
    Bekannte WGR-IDs werden auf COGS-Kategorien gemappt (HAB-15).
    Unbekannte IDs verwenden WARENGRUPPEN.NAME aus der Datenbank als Fallback.
    """
    sql = """
        SELECT
            COALESCE(jp.WARENGRUPPE, 0)          AS wgr_id,
            MAX(wg.NAME)                         AS wgr_name,
            ROUND(SUM(jp.GPREIS), 2)             AS umsatz_brutto
        FROM JOURNALPOS jp
        JOIN JOURNAL j ON jp.JOURNAL_ID = j.REC_ID
        LEFT JOIN WARENGRUPPEN wg ON jp.WARENGRUPPE = wg.WARENGRUPPE
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
        # COGS-Kategorie-Mapping gemäß CFO-Analyse (HAB-15).
        # Warengruppen-IDs, die hier nicht aufgeführt sind, werden über
        # WARENGRUPPEN.NAME aus der CAO-Datenbank aufgelöst.
        _WGR_COGS = {
            **{wgr: 'Lebensmittel' for wgr in [1,2,3,4,6,8,9,12,200,300,500,600,800]},
            15: 'Habacher Erzeugnisse',
            5:  'Verzehr / Café',
            **{wgr: 'Getränke alkoholfrei' for wgr in [711,712,713,714]},
            **{wgr: 'Getränke alkoholisch' for wgr in [731,732,733,734,740]},
            **{wgr: 'Non-Food' for wgr in [400,410,420,430,460,470,490,499]},
            450: 'Tabakwaren',
            990: 'Gutscheine',
            900: 'Pfand',
        }
        # Aggregation auf COGS-Kategorien
        kategorien: dict[str, float] = {}
        for r in rows:
            wgr_id = int(r['wgr_id'])
            # Priorität: COGS-Mapping → DB-Name → numerische Fallback-Bezeichnung
            kat = _WGR_COGS.get(wgr_id, r.get('wgr_name') or f"WGR {wgr_id}")
            kategorien[kat] = round(kategorien.get(kat, 0.0) + float(r['umsatz_brutto']), 2)
        return [{'kategorie': k, 'umsatz_brutto': v}
                for k, v in sorted(kategorien.items(), key=lambda x: -x[1])]
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
    monate_liste = [r['monat'] for r in mwst_daten]
    # Monat-Parameter: URL-Param bevorzugen, sonst neuesten Monat mit Daten nehmen.
    # Verhindert, dass laufender Monat (ohne Buchungen) als Default angezeigt wird.
    monat_param = request.args.get('monat', '')
    if not monat_param or monat_param not in monate_liste:
        monat_param = monate_liste[0] if monate_liste else date.today().strftime('%Y-%m')
    warengruppen = _umsatz_warengruppen(monat_param)
    kpis         = _finance_kpis()
    return render_template(
        'reporting.html',
        mwst_daten=mwst_daten,
        warengruppen=warengruppen,
        kpis=kpis,
        monat_param=monat_param,
        monate_liste=monate_liste,
        heute=date.today().strftime('%d.%m.%Y'),
    )


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
