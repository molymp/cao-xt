# ============================================================
# CAO-XT WaWi-App – Konfiguration
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
#
# Zwei Datenbanken:
#   CAO-DB  (cao_2018_001): read-only – ARTIKEL, WARENGRUPPE, LIEFERANT
#   WaWi-DB (cao_wawi):     read-write – Preisgruppen, Preishistorie
# ============================================================
import os
import configparser

_INI = os.path.join(os.path.dirname(__file__), '..', '..', 'caoxt', 'caoxt.ini')
_cfg = configparser.ConfigParser()
_cfg.read(_INI)


def _db(key, fallback=''):
    return os.environ.get(key.upper(), _cfg.get('Datenbank', key.lower(), fallback=fallback))


# ── CAO-Datenbank (Artikelstamm, read-only) ───────────────────
CAO_DB_HOST     = _db('db_loc',  'localhost')
CAO_DB_PORT     = int(_db('db_port', '3306'))
CAO_DB_NAME     = _db('db_name', '')
CAO_DB_USER     = _db('db_user', '')
CAO_DB_PASSWORD = _db('db_pass', '')

# ── WaWi-Datenbank (Preise, read-write) ───────────────────────
# Defaults: gleicher Server wie CAO, separate DB 'cao_wawi'
WAWI_DB_HOST     = os.environ.get('WAWI_DB_HOST',     CAO_DB_HOST)
WAWI_DB_PORT     = int(os.environ.get('WAWI_DB_PORT', str(CAO_DB_PORT)))
WAWI_DB_NAME     = os.environ.get('WAWI_DB_NAME',     'cao_wawi')
WAWI_DB_USER     = os.environ.get('WAWI_DB_USER',     CAO_DB_USER)
WAWI_DB_PASSWORD = os.environ.get('WAWI_DB_PASSWORD', CAO_DB_PASSWORD)

# ── App-Einstellungen ─────────────────────────────────────────
DEBUG      = os.environ.get('WAWI_DEBUG', 'false').lower() == 'true'
PORT       = int(os.environ.get('WAWI_PORT', '5003'))
HOST       = os.environ.get('WAWI_HOST', '0.0.0.0')
SECRET_KEY = os.environ.get('WAWI_SECRET_KEY', 'bitte-in-produktion-aendern')

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

# Standard-Benutzer für Preisänderungen (wenn keine Session vorhanden)
WAWI_BENUTZER_DEFAULT = os.environ.get('WAWI_BENUTZER', 'wawi')

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
