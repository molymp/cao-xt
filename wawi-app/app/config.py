# ============================================================
# CAO-XT WaWi-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config

_cfg        = load_db_config("WAWI")
DB_HOST     = _cfg['host']
DB_PORT     = _cfg['port']
DB_NAME     = _cfg['name']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']

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
