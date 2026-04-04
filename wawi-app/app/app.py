"""
CAO-XT WaWi-App – Flask-Hauptanwendung
Starten: cd wawi-app/app && python3 app.py
"""
from flask import Flask, render_template, request, jsonify
from datetime import datetime, date
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
        "firma_name": config.FIRMA_NAME,
        "kasse_url":  kasse_url,
        "kiosk_url":  kiosk_url,
        "db_ok":      test_verbindung(),
    }


# ── Dashboard-Abfragen ────────────────────────────────────────

def _monatsumsatz_6_monate() -> list[dict]:
    """Monatsumsatz (Brutto) der letzten 6 Monate aus CAO-Kassenbuch."""
    sql = """
        SELECT
            DATE_FORMAT(BUCHUNGSDATUM, '%Y-%m') AS monat,
            DATE_FORMAT(BUCHUNGSDATUM, '%b %Y') AS label,
            ROUND(SUM(BETRAG) / 100.0, 2)       AS brutto
        FROM KASSABUCH
        WHERE BUCHUNGSDATUM >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
          AND BETRAG > 0
        GROUP BY DATE_FORMAT(BUCHUNGSDATUM, '%Y-%m')
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
    """Heutige Tageseinnahmen (Brutto) in Euro."""
    sql = """
        SELECT COALESCE(ROUND(SUM(BETRAG) / 100.0, 2), 0.0) AS einnahmen
        FROM KASSABUCH
        WHERE DATE(BUCHUNGSDATUM) = CURDATE()
          AND BETRAG > 0
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


# ── Routen ───────────────────────────────────────────────────

@app.route('/')
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
def coming_soon():
    modul = request.args.get('modul', 'Dieses Modul')
    return render_template('coming_soon.html', modul=modul)


@app.route('/api/status')
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
