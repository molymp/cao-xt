# ============================================================
# CAO-XT Admin-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment


def _env(new: str, old: str | None = None, default: str = '') -> str:
    """ADMIN_*-Variable lesen; faellt auf den alten VERWALTUNG_*-Namen zurueck,
    damit bestehende Deployments bei einem Release-Upgrade nicht brechen.
    Der alte Name sollte in Dorfkern v2.1 entfernt werden.
    """
    if new in os.environ:
        return os.environ[new]
    if old and old in os.environ:
        return os.environ[old]
    return default


_cfg        = load_db_config("ADMIN")
XT_ENVIRONMENT = load_environment()
DB_HOST     = _cfg['host']
DB_PORT     = _cfg['port']
DB_NAME     = _cfg['name']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']


def reload_db_config():
    """Liest DB-Werte erneut aus caoxt.ini / Env-Vars und aktualisiert Modul-Globals."""
    _this = sys.modules[__name__]
    fresh = load_db_config("ADMIN")
    _this.DB_HOST     = fresh['host']
    _this.DB_PORT     = fresh['port']
    _this.DB_NAME     = fresh['name']
    _this.DB_USER     = fresh['user']
    _this.DB_PASSWORD = fresh['password']

PORT       = int(_env('ADMIN_PORT',       'VERWALTUNG_PORT',       '5004'))
HOST       = _env('ADMIN_HOST',       'VERWALTUNG_HOST',       '0.0.0.0')
SECRET_KEY = _env('ADMIN_SECRET_KEY', 'VERWALTUNG_SECRET_KEY', 'bitte-in-produktion-aendern')
DEBUG      = _env('ADMIN_DEBUG',      'VERWALTUNG_DEBUG',      'false').lower() == 'true'

KASSE_URL  = os.environ.get('KASSE_URL', '')
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))
KIOSK_URL  = os.environ.get('KIOSK_URL', '')
KIOSK_PORT = int(os.environ.get('KIOSK_PORT', '5001'))
ORGA_URL   = _env('ORGA_URL',  'WAWI_URL',  '')
ORGA_PORT  = int(_env('ORGA_PORT', 'WAWI_PORT', '5003'))

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

INI_PATH = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

# ── Lokale Overrides (config_local.py, nicht in git) ─────────
try:
    from config_local import *   # noqa: F401, F403
except ImportError:
    pass
