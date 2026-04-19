# ============================================================
# CAO-XT WaWi-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment

_cfg        = load_db_config("WAWI")
XT_ENVIRONMENT = load_environment()
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
KIOSK_URL       = os.environ.get('KIOSK_URL', '')
KIOSK_PORT      = int(os.environ.get('KIOSK_PORT', '5001'))
VERWALTUNG_URL  = os.environ.get('VERWALTUNG_URL', '')
VERWALTUNG_PORT = int(os.environ.get('VERWALTUNG_PORT', '5004'))

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

# ── HACCP / TFA Cloud-API (Temperatursensoren) ────────────────
# API-Key im config_local.py oder als Env-Var setzen. NICHT committen.
TFA_API_KEY  = os.environ.get('TFA_API_KEY', '')
TFA_BASE_URL = os.environ.get('TFA_BASE_URL', 'https://go.tfa.me')
# Poll-Intervall des Background-Workers in Sekunden.
HACCP_POLL_INTERVALL_S = int(os.environ.get('HACCP_POLL_INTERVALL_S', '120'))

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
