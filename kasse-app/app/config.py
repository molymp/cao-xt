# ============================================================
# CAO-XT Kassen-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment

_cfg             = load_db_config("KASSE")
XT_ENVIRONMENT   = load_environment()
TRAININGSMODUS   = (XT_ENVIRONMENT == 'training')
DB_HOST          = _cfg['host']
DB_PORT     = _cfg['port']
DB_NAME     = _cfg['name']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']

TERMINAL_NR = int(os.environ.get('KASSE_TERMINAL_NR', '1'))

DEBUG      = os.environ.get('KASSE_DEBUG', 'false').lower() == 'true'
PORT       = int(os.environ.get('KASSE_PORT', '5002'))
HOST       = os.environ.get('KASSE_HOST', '0.0.0.0')
SECRET_KEY = os.environ.get('KASSE_SECRET_KEY', 'bitte-in-produktion-aendern')

# Legacy-Fallback: alte WAWI_*/VERWALTUNG_*-Variablen weiter beruecksichtigen.
def _env(new: str, old: str | None = None, default: str = '') -> str:
    if new in os.environ:
        return os.environ[new]
    if old and old in os.environ:
        return os.environ[old]
    return default

KIOSK_URL          = os.environ.get('KIOSK_URL',          '')
KIOSK_PORT         = int(os.environ.get('KIOSK_PORT',      '5001'))
ORGA_URL           = _env('ORGA_URL',  'WAWI_URL',  '')
ORGA_PORT          = int(_env('ORGA_PORT',  'WAWI_PORT',  '5003'))
ADMIN_URL          = _env('ADMIN_URL', 'VERWALTUNG_URL', '')
ADMIN_PORT         = int(_env('ADMIN_PORT', 'VERWALTUNG_PORT', '5004'))

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
