# ============================================================
# CAO-XT Kassen-App – Konfiguration
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

TERMINAL_NR = int(os.environ.get('KASSE_TERMINAL_NR', '1'))

DEBUG      = os.environ.get('KASSE_DEBUG', 'false').lower() == 'true'
PORT       = int(os.environ.get('KASSE_PORT', '5002'))
HOST       = os.environ.get('KASSE_HOST', '0.0.0.0')
SECRET_KEY = os.environ.get('KASSE_SECRET_KEY', 'bitte-in-produktion-aendern')

KIOSK_URL          = os.environ.get('KIOSK_URL',          '')
KIOSK_PORT         = int(os.environ.get('KIOSK_PORT',      '5001'))
WAWI_URL           = os.environ.get('WAWI_URL',           '')
WAWI_PORT          = int(os.environ.get('WAWI_PORT',       '5003'))

FIRMA_NAME         = os.environ.get('FIRMA_NAME',         'Habacher Dorfladen')
FIRMA_STRASSE      = os.environ.get('FIRMA_STRASSE',      '')
FIRMA_ORT          = os.environ.get('FIRMA_ORT',          '')
FIRMA_UST_ID       = os.environ.get('FIRMA_UST_ID',       '')
FIRMA_STEUERNUMMER = os.environ.get('FIRMA_STEUERNUMMER', '')

FISKALY_BASE_URL = 'https://kassensichv-middleware.fiskaly.com/api/v2'
FISKALY_MGMT_URL = 'https://kassensichv.fiskaly.com/api/v2'

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
# Datei anlegen um die obigen Werte zu überschreiben, z.B.:
#   DB_HOST     = '192.168.1.10'
#   DB_PORT     = 3306
#   DB_NAME     = 'caofaktura'
#   DB_USER     = 'kasse'
#   DB_PASSWORD = 'geheim'
#   DEBUG       = True
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
