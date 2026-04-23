# ============================================================
# CAO-XT Orga-App – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment


def _env(new: str, old: str | None = None, default: str = '') -> str:
    """ORGA_*-Variable lesen; faellt auf den alten WAWI_*-Namen zurueck,
    damit bestehende Deployments bei einem Release-Upgrade nicht brechen.
    Der alte Name sollte in Dorfkern v2.1 entfernt werden.
    """
    if new in os.environ:
        return os.environ[new]
    if old and old in os.environ:
        return os.environ[old]
    return default


_cfg        = load_db_config("ORGA")
XT_ENVIRONMENT = load_environment()
DB_HOST     = _cfg['host']
DB_PORT     = _cfg['port']
DB_NAME     = _cfg['name']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']

PORT       = int(_env('ORGA_PORT',       'WAWI_PORT',       '5003'))
HOST       = _env('ORGA_HOST',       'WAWI_HOST',       '0.0.0.0')
SECRET_KEY = _env('ORGA_SECRET_KEY', 'WAWI_SECRET_KEY', 'bitte-in-produktion-aendern')
DEBUG      = _env('ORGA_DEBUG',      'WAWI_DEBUG',      'false').lower() == 'true'

KASSE_URL  = os.environ.get('KASSE_URL', '')
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))
KIOSK_URL       = os.environ.get('KIOSK_URL', '')
KIOSK_PORT      = int(os.environ.get('KIOSK_PORT', '5001'))
ADMIN_URL  = _env('ADMIN_URL',  'VERWALTUNG_URL',  '')
ADMIN_PORT = int(_env('ADMIN_PORT', 'VERWALTUNG_PORT', '5004'))

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
