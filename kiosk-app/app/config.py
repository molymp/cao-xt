# ============================================================
# Bäckerei Kiosk – Konfiguration (thin wrapper um common.config)
# Priorität: config_local.py > Umgebungsvariablen > caoxt.ini
# Lokale Overrides in config_local.py (nicht in git) eintragen.
# ============================================================
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config, load_environment

# ── Datenbank ─────────────────────────────────────────────────
# Host/Port/User/Password aus caoxt.ini (gleicher MySQL-Server wie CAO Faktura).
# DB_NAME NICHT aus caoxt.ini: Kiosk nutzt eigene Datenbank 'Backwaren',
# die von der CAO-Faktura-DB (db_name in caoxt.ini) abweicht.
# Überschreiben via Env-Var KIOSK_DB_NAME oder config_local.py.
_cfg        = load_db_config("KIOSK")
XT_ENVIRONMENT = load_environment()
DB_HOST     = _cfg['host']
DB_PORT     = _cfg['port']
DB_USER     = _cfg['user']
DB_PASSWORD = _cfg['password']
DB_NAME     = os.environ.get('KIOSK_DB_NAME') or 'Backwaren'

# ── Terminal ──────────────────────────────────────────────────
# Einstellige Zahl 1–9, pro Gerät einmalig vergeben.
TERMINAL_NR = 1

# ── Flask ─────────────────────────────────────────────────────
DEBUG      = True
PORT       = 5001            # 5000 ist belegt
HOST       = "0.0.0.0"      # ganzes LAN erreichbar
SECRET_KEY = os.environ.get('KIOSK_SECRET_KEY', 'bitte-in-produktion-aendern')

# ── Barcode ───────────────────────────────────────────────────
EAN_BEREICH       = "21"
EAN_SAMMELARTIKEL = "7408"   # CAO-Sammelartikel Backwaren

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

# ── Verknüpfte Apps ───────────────────────────────────────────
KASSE_URL  = os.environ.get('KASSE_URL',  '')   # oder z.B. http://192.168.1.x:5002
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))  # Fallback: gleicher Host, Port 5002
WAWI_URL        = os.environ.get('WAWI_URL',  '')
WAWI_PORT       = int(os.environ.get('WAWI_PORT',  '5003'))
VERWALTUNG_URL  = os.environ.get('VERWALTUNG_URL', '')
VERWALTUNG_PORT = int(os.environ.get('VERWALTUNG_PORT', '5004'))

# ── Lokale Overrides (config_local.py, nicht in git) ──────────
# Datei anlegen um die obigen Werte zu überschreiben, z.B.:
#   DB_HOST     = '192.168.1.10'
#   DB_USER     = 'kiosk'
#   DB_PASSWORD = 'geheim'
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
