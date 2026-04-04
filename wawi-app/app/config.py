# ============================================================
# CAO-XT WaWi-App – Konfiguration
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import configparser

_INI = os.path.join(os.path.dirname(__file__), '..', '..', 'caoxt', 'caoxt.ini')
_cfg = configparser.ConfigParser()
_cfg.read(_INI)


def _db(key, fallback=''):
    return os.environ.get(key.upper(), _cfg.get('Datenbank', key.lower(), fallback=fallback))


# ── Defaults aus caoxt.ini / Umgebungsvariablen ───────────────
DB_HOST     = _db('db_loc',  'localhost')
DB_PORT     = int(_db('db_port', '3306'))
DB_NAME     = _db('db_name', '')
DB_USER     = _db('db_user', '')
DB_PASSWORD = _db('db_pass', '')

PORT       = int(os.environ.get('WAWI_PORT', '5003'))
HOST       = os.environ.get('WAWI_HOST', '0.0.0.0')
SECRET_KEY = os.environ.get('WAWI_SECRET_KEY', 'bitte-in-produktion-aendern')
DEBUG      = os.environ.get('WAWI_DEBUG', 'false').lower() == 'true'

KASSE_URL  = os.environ.get('KASSE_URL', '')
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))
KIOSK_URL  = os.environ.get('KIOSK_URL', '')
KIOSK_PORT = int(os.environ.get('KIOSK_PORT', '5001'))

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
