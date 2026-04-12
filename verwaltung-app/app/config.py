# ============================================================
# CAO-XT Verwaltungs-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment

_cfg        = load_db_config("VERWALTUNG")
XT_ENVIRONMENT = load_environment()
DB_HOST     = _cfg['host']
DB_PORT     = _cfg['port']
DB_NAME     = _cfg['name']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']


def reload_db_config():
    """Liest DB-Werte erneut aus caoxt.ini / Env-Vars und aktualisiert Modul-Globals."""
    _this = sys.modules[__name__]
    fresh = load_db_config("VERWALTUNG")
    _this.DB_HOST     = fresh['host']
    _this.DB_PORT     = fresh['port']
    _this.DB_NAME     = fresh['name']
    _this.DB_USER     = fresh['user']
    _this.DB_PASSWORD = fresh['password']

PORT       = int(os.environ.get('VERWALTUNG_PORT', '5004'))
HOST       = os.environ.get('VERWALTUNG_HOST', '0.0.0.0')
SECRET_KEY = os.environ.get('VERWALTUNG_SECRET_KEY', 'bitte-in-produktion-aendern')
DEBUG      = os.environ.get('VERWALTUNG_DEBUG', 'false').lower() == 'true'

KASSE_URL  = os.environ.get('KASSE_URL', '')
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))
KIOSK_URL  = os.environ.get('KIOSK_URL', '')
KIOSK_PORT = int(os.environ.get('KIOSK_PORT', '5001'))
WAWI_URL   = os.environ.get('WAWI_URL', '')
WAWI_PORT  = int(os.environ.get('WAWI_PORT', '5003'))

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

INI_PATH = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
