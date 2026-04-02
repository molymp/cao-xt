"""
ZVT-Protokoll (Zahlungsverkehrsterminal) über TCP/IP – Ingenico Desk 3500.

ECR (diese App) verbindet sich als Client zum PT (Terminal) auf Port 20007.
Alle Nachrichten laufen auf einer einzigen TCP-Verbindung (kein Rückkanal nötig).

Unterstützte Befehle:
  - Autorisierung  (06 01)  – Kartenzahlung initiieren
  - Tagesabschluss (06 50)  – Kassenschnitt am Terminal
  - ping()                  – reiner TCP-Verbindungstest
"""
import socket
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── BMP-Längen (Tag → Anzahl Datenbytes) ─────────────────────────────────
# Alle Längen ohne Tag-Byte. Quelle: ZVT-Protokoll Spezifikation v04.xx
_BMP_LAENGEN: dict[int, int] = {
    0x01: 1,   # Autorisierungsmerkmal
    0x02: 1,   # Präsentationsform
    0x03: 1,   # Zahlungstyp
    0x04: 3,   # Betrag (BCD 6-stellig, Cent)
    0x0B: 3,   # Tracenummer (BCD 6-stellig)
    0x0C: 3,   # Uhrzeit (BCD HHMMSS)
    0x0D: 2,   # Datum (BCD MMDD)
    0x0E: 2,   # Ablaufdatum Karte (BCD MMYY)
    0x17: 1,   # Anzahl Versuche
    0x19: 1,   # Zahlungsart (Bit 3=PIN, Bit 4=Unterschrift …)
    0x22: 10,  # PAN teilw. maskiert (BCD)
    0x27: 4,   # Terminal-ID (BCD 8-stellig)
    0x29: 3,   # Sequenznummer / Belegnr (BCD 6-stellig)
    0x3C: 0,   # Beendigungssatz (kein Wert)
    0x49: 2,   # Währung (ISO 4217, BCD)
    0x8A: 1,   # Ergebniscode (0x00 = OK)
    0x92: 10,  # Genehmigungscode ASCII (10 Bytes)
}
# Tags mit vorangestelltem 1-Byte-Längenfeld
_BMP_VARIABEL: set[int] = {0x60, 0x9A, 0xA0, 0xA7, 0xAF}

# Acknowledge-APDU (ECR → PT)
_ACK = bytes([0x80, 0x00, 0x00])

# Standard-ZVT-Passwort für den Desk 3500 (BCD "010203").
# Wird verwendet wenn kein anderes Passwort konfiguriert ist.
_ZVT_PASSWORT_DEFAULT = bytes([0x01, 0x02, 0x03])


def passwort_von_hex(hex_str: str) -> bytes:
    """
    Wandelt einen konfigurierten Passwort-String in ZVT-Passwort-Bytes um.
    Format: 6 Dezimalstellen als BCD-kodierter Hex-String, z.B. '010203' → b'\\x01\\x02\\x03'.
    Ungültige Eingaben fallen auf das Standardpasswort zurück.
    """
    s = (hex_str or '').strip().zfill(6)[:6]
    try:
        return bytes(int(s[i:i + 2], 16) for i in range(0, 6, 2))
    except ValueError:
        log.warning('ZVT: Ungültiges Passwort-Format "%s" – Standardpasswort wird verwendet', hex_str)
        return _ZVT_PASSWORT_DEFAULT


# ── BCD-Hilfsfunktionen ───────────────────────────────────────────────────

def _bcd_zu_int(data: bytes) -> int:
    """BCD-Bytes → int.   b'\\x12\\x34' → 1234"""
    return int(''.join(f'{b:02X}' for b in data))


def _int_zu_bcd(wert: int, laenge_bytes: int) -> bytes:
    """int → BCD-Bytes fester Länge.   (1234, 3) → b'\\x00\\x12\\x34'"""
    s = str(wert).zfill(laenge_bytes * 2)
    return bytes(int(s[i:i + 2], 16) for i in range(0, laenge_bytes * 2, 2))


# ── APDU-Hilfsfunktionen ──────────────────────────────────────────────────

def _apdu(cc1: int, cc2: int, data: bytes = b'') -> bytes:
    """Erstellt eine ZVT-APDU: [CC1][CC2][LEN][DATA]."""
    n = len(data)
    if n <= 254:
        return bytes([cc1, cc2, n]) + data
    # Erweiterte Länge: 0xFF + 2-Byte Big-Endian-Länge
    return bytes([cc1, cc2, 0xFF]) + n.to_bytes(2, 'big') + data


def _parse_bmps(data: bytes) -> dict:
    """Parst ZVT-BMP-Daten. Gibt {tag: bytes} zurück."""
    result: dict[int, bytes] = {}
    i = 0
    while i < len(data):
        tag = data[i]; i += 1
        if tag in _BMP_VARIABEL:
            if i >= len(data):
                break
            laenge = data[i]; i += 1
            result[tag] = data[i:i + laenge]; i += laenge
        elif tag in _BMP_LAENGEN:
            laenge = _BMP_LAENGEN[tag]
            result[tag] = data[i:i + laenge]; i += laenge
        else:
            log.debug('ZVT: Unbekannter BMP-Tag 0x%02X (Offset %d) – Parsing beendet', tag, i - 1)
            break
    return result


# ── TCP-Verbindungsklasse ─────────────────────────────────────────────────

class _ZVTVerbindung:
    """Verwaltete TCP-Verbindung zum ZVT-Terminal. Nutzung als Context-Manager."""

    def __init__(self, ip: str, port: int, timeout: int):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def __enter__(self):
        self._sock = socket.create_connection((self.ip, self.port), timeout=5)
        self._sock.settimeout(self.timeout)
        return self

    def __exit__(self, *_):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    # ── Low-level Socket-Operationen ──────────────────────────────────────

    def _recv_exakt(self, n: int) -> bytes:
        buf = b''
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('EC-Terminal: Verbindung unterbrochen')
            buf += chunk
        return buf

    def _empfangen(self) -> bytes:
        """Liest eine vollständige ZVT-APDU vom Terminal."""
        hdr = self._recv_exakt(3)          # [CC1][CC2][LEN|0xFF]
        raw_ln = hdr[2]
        if raw_ln == 0xFF:                 # Erweiterte Länge
            ext = self._recv_exakt(2)
            actual_ln = int.from_bytes(ext, 'big')
            data = self._recv_exakt(actual_ln) if actual_ln else b''
            apdu = hdr + ext + data
        else:
            data = self._recv_exakt(raw_ln) if raw_ln else b''
            apdu = hdr + data
        log.debug('ZVT RX: %s', apdu.hex())
        return apdu

    def _senden(self, apdu: bytes):
        log.debug('ZVT TX: %s', apdu.hex())
        self._sock.sendall(apdu)

    def _ack(self):
        self._senden(_ACK)

    def _apdu_daten(self, apdu: bytes) -> bytes:
        """Gibt den Datenteil einer APDU zurück (ohne 3- oder 5-Byte-Header)."""
        return apdu[5:] if apdu[2] == 0xFF else apdu[3:]

    # ── Transaktions-Schleife ─────────────────────────────────────────────

    def _transaktion(self, befehl: bytes) -> dict:
        """
        Sendet einen Befehl und wartet auf die abschließende Fertigmeldung (06 0F / 06 1E).
        Zwischenstatus (04 FF) werden mit ACK quittiert und ignoriert.
        Gibt {'erfolg': bool, 'bmps': dict, 'cc': (cc1, cc2)} zurück.
        """
        self._senden(befehl)
        while True:
            apdu = self._empfangen()
            cc1, cc2 = apdu[0], apdu[1]

            if cc1 == 0x80 and cc2 == 0x00:
                # ACK vom Terminal – Befehl wurde angenommen, warten auf Status
                continue

            if cc1 == 0x04 and cc2 == 0xFF:
                # Zwischenstatus (Druckdaten, Display-Meldungen etc.) → ACK quittieren
                self._ack()
                continue

            if cc1 == 0x06 and cc2 == 0x0F:
                # Fertigmeldung (Completion) – Transaktion abgeschlossen
                self._ack()
                bmps   = _parse_bmps(self._apdu_daten(apdu))
                # Ergebniscode 0x8A: 0x00 = OK, alles andere = Fehler
                erfolg = bmps.get(0x8A, b'\x00') == b'\x00'
                return {'erfolg': erfolg, 'bmps': bmps, 'cc': (cc1, cc2)}

            if cc1 == 0x06 and cc2 == 0x1E:
                # Abort / Ablehnung
                self._ack()
                bmps = _parse_bmps(self._apdu_daten(apdu))
                return {'erfolg': False, 'bmps': bmps, 'cc': (cc1, cc2)}

            # Unbekannte APDU: trotzdem ACK, damit Terminal nicht hängt
            log.warning('ZVT: Unbekannte APDU %02X %02X – sende ACK', cc1, cc2)
            self._ack()


# ── Öffentliche API ───────────────────────────────────────────────────────

def ping(ip: str, port: int = 20007, timeout: int = 3) -> bool:
    """Prüft ob das EC-Terminal TCP-seitig erreichbar ist."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def authorisieren(ip: str, port: int, betrag_cent: int,
                  passwort: bytes = _ZVT_PASSWORT_DEFAULT,
                  timeout: int = 90) -> dict:
    """
    Initiiert eine Kartenzahlung über ZVT (Autorisierung 06 01).

    Rückgabe:
      {'ok': True,  'referenz': str, 'terminal_id': str}
      {'ok': False, 'fehler': str,   'offline': bool}

    Der 'referenz'-String enthält Terminal-ID, Sequenznummer und Genehmigungscode
    in kompakter Form (z.B. 'T:12345678/S:001234/A:ABCD12') und wird in
    XT_KASSE_ZAHLUNGEN.REFERENZ gespeichert.
    """
    # APDU: 06 01 [LEN] [CONFIG=0x04] [BETRAG 6 Byte BCD] [PASSWORT 3 Byte BCD]
    # CONFIG 0x04: Betrag in Eurocent, Terminal druckt eigenen Beleg
    config = bytes([0x04])
    betrag = _int_zu_bcd(betrag_cent, 6)
    befehl = _apdu(0x06, 0x01, config + betrag + passwort)

    try:
        with _ZVTVerbindung(ip, port, timeout) as zvt:
            ergebnis = zvt._transaktion(befehl)
    except OSError as e:
        log.warning('ZVT Autorisierung: Terminal nicht erreichbar (%s:%d): %s', ip, port, e)
        return {'ok': False, 'fehler': 'EC-Terminal nicht erreichbar', 'offline': True}
    except Exception as e:
        log.error('ZVT Autorisierung fehlgeschlagen: %s', e)
        return {'ok': False, 'fehler': str(e), 'offline': False}

    if not ergebnis['erfolg']:
        return {'ok': False, 'fehler': 'Zahlung abgelehnt oder abgebrochen', 'offline': False}

    # Referenz aus BMPs zusammenbauen
    bmps = ergebnis['bmps']
    terminal_id = str(_bcd_zu_int(bmps[0x27])) if 0x27 in bmps else ''
    seq_nr      = str(_bcd_zu_int(bmps[0x29])) if 0x29 in bmps else ''
    auth_code   = bmps.get(0x92, b'').decode('ascii', errors='replace').strip()

    teile = []
    if terminal_id: teile.append(f'T:{terminal_id}')
    if seq_nr:      teile.append(f'S:{seq_nr}')
    if auth_code:   teile.append(f'A:{auth_code}')
    referenz = '/'.join(teile)

    log.info('ZVT Autorisierung OK: %s (%.2f €)', referenz, betrag_cent / 100)
    return {'ok': True, 'referenz': referenz, 'terminal_id': terminal_id}


def _parse_tagesabschluss_totals(bmp60_data: bytes) -> Optional[dict]:
    """
    Parst BMP 0x60 Totaldaten aus dem Tagesabschluss.
    Format: [Anzahl-Sätze 1B] {[Kartentyp 1B][Anzahl 3B BCD][Betrag 6B BCD]}*
    Kartentyp 0x00 = Gesamtsumme aller Karten.

    Gibt {'gesamt_cent': int, 'anzahl': int, 'details': list} zurück oder None.
    """
    if not bmp60_data or len(bmp60_data) < 1:
        return None
    try:
        anzahl_saetze = bmp60_data[0]
        i = 1
        gesamt_cent = 0
        gesamt_anz  = 0
        details     = []
        for _ in range(anzahl_saetze):
            if i + 10 > len(bmp60_data):
                break
            kartentyp = bmp60_data[i]; i += 1
            anz       = _bcd_zu_int(bmp60_data[i:i + 3]); i += 3
            betrag    = _bcd_zu_int(bmp60_data[i:i + 6]); i += 6
            if kartentyp == 0x00:    # Gesamtsumme-Satz
                gesamt_cent = betrag
                gesamt_anz  = anz
            details.append({'kartentyp': kartentyp, 'anzahl': anz, 'betrag_cent': betrag})
        # Fallback: Gesamtsumme selbst berechnen wenn kein Typ-0-Satz vorhanden
        if not gesamt_cent and details:
            gesamt_cent = sum(d['betrag_cent'] for d in details)
            gesamt_anz  = sum(d['anzahl']      for d in details)
        return {'gesamt_cent': gesamt_cent, 'anzahl': gesamt_anz, 'details': details}
    except Exception as e:
        log.warning('ZVT: Tagesabschluss-BMP-0x60-Parsing fehlgeschlagen: %s', e)
        return None


def tagesabschluss_ausfuehren(ip: str, port: int,
                              passwort: bytes = _ZVT_PASSWORT_DEFAULT,
                              timeout: int = 120) -> dict:
    """
    Führt den EC-Terminal-Tagesabschluss (Kassenschnitt) durch (ZVT 06 50).

    Rückgabe:
      {'ok': True,  'totals': {'gesamt_cent': int, 'anzahl': int, 'details': list} | None}
      {'ok': False, 'fehler': str, 'offline': bool}

    'totals' enthält die vom Terminal gemeldeten Umsatzsummen für den Vergleich
    mit dem App-internen EC-Umsatz. None wenn das Terminal keine Totals meldet.
    """
    # APDU: 06 50 [LEN] [PASSWORT 3 Byte BCD]
    befehl = _apdu(0x06, 0x50, passwort)

    try:
        with _ZVTVerbindung(ip, port, timeout) as zvt:
            ergebnis = zvt._transaktion(befehl)
    except OSError as e:
        log.warning('ZVT Tagesabschluss: Terminal nicht erreichbar (%s:%d): %s', ip, port, e)
        return {'ok': False, 'totals': None, 'fehler': 'EC-Terminal nicht erreichbar',
                'offline': True}
    except Exception as e:
        log.error('ZVT Tagesabschluss fehlgeschlagen: %s', e)
        return {'ok': False, 'totals': None, 'fehler': str(e), 'offline': False}

    if not ergebnis['erfolg']:
        return {'ok': False, 'totals': None,
                'fehler': 'EC-Terminal Tagesabschluss abgelehnt', 'offline': False}

    bmps   = ergebnis['bmps']
    totals = _parse_tagesabschluss_totals(bmps.get(0x60, b''))
    log.info('ZVT Tagesabschluss OK. Totals: %s', totals)
    return {'ok': True, 'totals': totals, 'fehler': ''}
