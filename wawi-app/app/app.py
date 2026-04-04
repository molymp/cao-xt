"""
CAO-XT WaWi-App – Flask-Hauptanwendung
Starten: cd wawi-app/app && python3 app.py
"""
from flask import Flask, render_template, request
from datetime import datetime, date
import os
import sys
import config
from db import get_db, test_verbindung
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False

# ── WaWi-Blueprint einbinden ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WAWI_MODULE_DIR = os.path.join(BASE_DIR, '..', '..', 'modules', 'wawi')
sys.path.insert(0, os.path.normpath(WAWI_MODULE_DIR))
try:
    import routes as wawi_routes
    app.register_blueprint(wawi_routes.bp, url_prefix='/wawi')
    log.info("WaWi-Blueprint registriert unter /wawi")
except ImportError as e:
    log.warning("WaWi-Blueprint konnte nicht geladen werden: %s", e)


# ── Globale Template-Variablen ────────────────────────────────

@app.context_processor
def _globals():
    return {
        'firma_name': config.FIRMA_NAME,
        'jetzt':      datetime.now(),
        'kasse_url':  config.KASSE_URL or (
                          f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
                          if config.KASSE_PORT else ''),
        'kiosk_url':  config.KIOSK_URL or (
                          f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
                          if config.KIOSK_PORT else ''),
    }


# ── Dashboard-Daten ───────────────────────────────────────────

def _monatsumsatz_6monate() -> list[dict]:
    """
    Brutto-Umsatz der letzten 6 Monate aus der Kassenbuch-Tabelle XT_KASSE_BELEGE.
    Gibt eine Liste von {monat: 'YYYY-MM', umsatz_ct: int} zurück.
    """
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT
                    DATE_FORMAT(DATUM, '%Y-%m')         AS monat,
                    SUM(BRUTTO_GESAMT_CT)               AS umsatz_ct
                FROM XT_KASSE_BELEGE
                WHERE
                    DATUM >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 5 MONTH), '%Y-%m-01')
                    AND STORNO = 0
                GROUP BY monat
                ORDER BY monat ASC
            """)
            rows = cur.fetchall()
        return [{'monat': r['monat'], 'umsatz_ct': int(r['umsatz_ct'] or 0)} for r in rows]
    except Exception as e:
        log.warning("Monatsumsatz-Abfrage fehlgeschlagen: %s", e)
        return []


def _tageseinnahmen_heute() -> int:
    """Heutige Tageseinnahmen (Brutto) in Cent aus XT_KASSE_BELEGE."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT COALESCE(SUM(BRUTTO_GESAMT_CT), 0) AS summe_ct
                FROM XT_KASSE_BELEGE
                WHERE DATE(DATUM) = CURDATE() AND STORNO = 0
            """)
            row = cur.fetchone()
        return int(row['summe_ct'] or 0)
    except Exception as e:
        log.warning("Tageseinnahmen-Abfrage fehlgeschlagen: %s", e)
        return 0


def _offene_vorgaenge() -> int:
    """Anzahl offener Vorgänge (angefangene, noch nicht abgeschlossene Belege) in XT_KASSE_BELEGE."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT COUNT(*) AS anzahl
                FROM XT_KASSE_BELEGE
                WHERE ABGESCHLOSSEN = 0 AND STORNO = 0
            """)
            row = cur.fetchone()
        return int(row['anzahl'] or 0)
    except Exception as e:
        log.warning("Offene-Vorgänge-Abfrage fehlgeschlagen: %s", e)
        return 0


def _cent_zu_euro_str(ct: int) -> str:
    """Formatiert Cent-Betrag als Euro-String mit Komma, z.B. '1.234,56 €'."""
    euro = ct / 100
    return f"{euro:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ── Routen ────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    """Startseite mit CFO-Kennzahlen."""
    monatsumsatz  = _monatsumsatz_6monate()
    tageseinnahmen = _tageseinnahmen_heute()
    offene_vorgaenge = _offene_vorgaenge()
    db_ok = test_verbindung()

    # Euro-Strings für Anzeige aufbereiten
    monatsumsatz_anzeige = [
        {**m, 'umsatz_str': _cent_zu_euro_str(m['umsatz_ct'])}
        for m in monatsumsatz
    ]

    return render_template(
        'dashboard.html',
        monatsumsatz=monatsumsatz_anzeige,
        tageseinnahmen_ct=tageseinnahmen,
        tageseinnahmen_str=_cent_zu_euro_str(tageseinnahmen),
        offene_vorgaenge=offene_vorgaenge,
        db_ok=db_ok,
    )


@app.route('/coming-soon')
def coming_soon():
    """Platzhalter für noch nicht implementierte Module."""
    modul = request.args.get('modul', 'Dieses Modul')
    return render_template('coming_soon.html', modul=modul)


# ── Start ─────────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("WaWi-App startet auf %s:%s", config.HOST, config.PORT)
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
