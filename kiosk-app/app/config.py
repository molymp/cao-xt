# ============================================================
# Bäckerei Kiosk – Konfiguration
# ============================================================

# ── Datenbank ─────────────────────────────────────────────────
DB_HOST     = "jdqsab3zx9phmhdt.myfritz.net"     # lokale LAN-IP des MariaDB-Servers eintragen
DB_PORT     = 3333
DB_USER     = "cao"
DB_PASSWORD = "faktura"
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
