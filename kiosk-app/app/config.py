# ============================================================
# Bäckerei Kiosk – Konfiguration
# ============================================================

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
