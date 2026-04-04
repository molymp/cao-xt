# ============================================================
# Bäckerei Kiosk – Konfiguration
# Priorität: config_local.py > Umgebungsvariablen > diese Defaults
# Lokale Overrides in config_local.py (nicht in git) eintragen.
# ============================================================
import os

# ── Datenbank ─────────────────────────────────────────────────
DB_HOST     = "<DB_HOST>"       # z.B. 192.168.x.x (lokale LAN-IP des MariaDB-Servers)
DB_PORT     = 3306              # Standard MariaDB-Port anpassen falls nötig
DB_USER     = "<DB_USER>"
DB_PASSWORD = "<DB_PASSWORD>"
DB_NAME     = "Backwaren"

# ── Terminal ──────────────────────────────────────────────────
# Einstellige Zahl 1–9, pro Gerät einmalig vergeben.
TERMINAL_NR = 1

# ── Flask ─────────────────────────────────────────────────────
DEBUG = True
PORT  = 5001            # 5000 ist belegt
HOST  = "0.0.0.0"      # ganzes LAN erreichbar

# ── Barcode ───────────────────────────────────────────────────
EAN_BEREICH       = "21"
EAN_SAMMELARTIKEL = "7408"   # CAO-Sammelartikel Backwaren

FIRMA_NAME = os.environ.get('FIRMA_NAME', 'Habacher Dorfladen')

# ── Verknüpfte Apps ───────────────────────────────────────────
KASSE_URL  = os.environ.get('KASSE_URL',  '')   # oder z.B. http://192.168.1.x:5002
KASSE_PORT = int(os.environ.get('KASSE_PORT', '5002'))  # Fallback: gleicher Host, Port 5002
WAWI_URL   = os.environ.get('WAWI_URL',  '')
WAWI_PORT  = int(os.environ.get('WAWI_PORT',  '5003'))

# ── Lokale Overrides (config_local.py, nicht in git) ──────────
# Datei anlegen um die obigen Werte zu überschreiben, z.B.:
#   DB_HOST     = '192.168.1.10'
#   DB_USER     = 'kiosk'
#   DB_PASSWORD = 'geheim'
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
