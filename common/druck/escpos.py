"""
CAO-XT – Gemeinsame ESC/POS-Konstanten und TCP-Sendehilfe

Alle ESC/POS-Byte-Sequenzen sind hier zentral definiert.
App-spezifische Bon-Aufbau-Logik verbleibt in der jeweiligen App.

Verwendung::

    from common.druck.escpos import ESC_INIT, ALIGN_CENTER, BOLD_ON, CUT, tcp_send

    buf = ESC_INIT + ALIGN_CENTER + BOLD_ON + b'Mein Laden\\n' + CUT
    tcp_send('192.168.1.100', 9100, buf)
"""
import socket

# ── Initialisierung ───────────────────────────────────────────
ESC_INIT        = b'\x1b\x40'          # ESC @ – Drucker zuruecksetzen

# ── Zeichensatz ───────────────────────────────────────────────
CODEPAGE_1252   = b'\x1b\x74\x10'      # Windows-1252: €, Umlaute nativ (Kasse)
CODEPAGE_437    = b'\x1b\x74\x00'      # CP437 US ASCII extended (Kiosk)

# ── Ausrichtung ───────────────────────────────────────────────
ALIGN_LEFT      = b'\x1b\x61\x00'      # ESC a 0
ALIGN_CENTER    = b'\x1b\x61\x01'      # ESC a 1
ALIGN_RIGHT     = b'\x1b\x61\x02'      # ESC a 2

# ── Schriftstil ───────────────────────────────────────────────
BOLD_ON         = b'\x1b\x45\x01'      # ESC E 1
BOLD_OFF        = b'\x1b\x45\x00'      # ESC E 0
DOUBLE_HW       = b'\x1b\x21\x30'      # ESC ! 0x30 – doppelte Breite + Hoehe
DOUBLE_HEIGHT   = b'\x1b\x21\x10'      # ESC ! 0x10 – nur doppelte Hoehe
NORMAL_SIZE     = b'\x1b\x21\x00'      # ESC ! 0x00 – Normalgroesse
FONT_A          = b'\x1b\x4d\x00'      # ESC m 0 – Font A (normal)
FONT_B          = b'\x1b\x4d\x01'      # ESC m 1 – Font B (kleiner)

# ── Papiervorschub / Schnitt ──────────────────────────────────
FEED_LINE       = b'\n'
CUT             = b'\x1d\x56\x01'      # GS V 1 – Teilschnitt

# ── Kassenlade ────────────────────────────────────────────────
DRAWER_PIN2     = b'\x1b\x70\x00\x19\xfa'
DRAWER_PIN5     = b'\x1b\x70\x01\x19\xfa'


def tcp_send(host: str, port: int, data: bytes, timeout: float = 3.0) -> None:
    """Sendet Bytes an einen ESC/POS-Drucker ueber TCP.

    Args:
        host:    IP-Adresse oder Hostname des Druckers.
        port:    TCP-Port (typisch 9100).
        data:    Zu sendende Byte-Sequenz.
        timeout: Verbindungs-Timeout in Sekunden (Standard 3.0).

    Raises:
        OSError: Bei Verbindungs- oder Sendefehler.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(data)
    finally:
        sock.close()
