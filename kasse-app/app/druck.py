"""
CAO-XT Kassen-App – Bondruck (ESC/POS TCP)
Erfüllt §6 AEAO zu §146a AO (Pflichtangaben auf Kassenbon):
  • Name und Anschrift des Unternehmers
  • Datum, Uhrzeit (Beginn und Ende des Vorgangs)
  • Menge und Art der Leistung
  • Entgelt und Steuerbetrag je Steuersatz
  • TSE-Seriennummer, Transaktionsnummer, Signaturzähler, Prüfwert
  • QR-Code (optional, empfohlen)
"""
import socket
import io
import config
from db import get_db, cent_zu_euro_str
from datetime import datetime
import logging

log = logging.getLogger(__name__)

# ESC/POS-Kommandos
_ESC_INIT      = b'\x1b\x40'
_ALIGN_LEFT    = b'\x1b\x61\x00'
_ALIGN_CENTER  = b'\x1b\x61\x01'
_ALIGN_RIGHT   = b'\x1b\x61\x02'
_BOLD_ON       = b'\x1b\x45\x01'
_BOLD_OFF      = b'\x1b\x45\x00'
_DOUBLE_HW     = b'\x1b\x21\x30'   # doppelte Breite + Höhe
_NORMAL_SIZE   = b'\x1b\x21\x00'
_DOUBLE_HEIGHT = b'\x1b\x21\x10'
_FONT_B        = b'\x1b\x4d\x01'   # Font B (kleiner)
_FONT_A        = b'\x1b\x4d\x00'   # Font A (normal)
_CUT           = b'\x1d\x56\x01'   # Teilschnitt

# Kassenlade öffnen
_DRAWER_PIN2   = b'\x1b\x70\x00\x19\xfa'
_DRAWER_PIN5   = b'\x1b\x70\x01\x19\xfa'

# Zeichensatz
_UMLAUT_MAP = str.maketrans({
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
    'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
    'ß': 'ss', '€': 'EUR',
    '–': '-', '—': '-', '„': '"', '"': '"', '"': '"', '…': '...',
})


def _a(text: str) -> str:
    return text.translate(_UMLAUT_MAP)


class _Bon:
    """Builder-Klasse für den Byte-Buffer."""
    def __init__(self):
        self._buf = bytearray()

    def raw(self, data: bytes):
        self._buf.extend(data)
        return self

    def text(self, s: str):
        self._buf.extend(_a(s).encode('cp437', errors='replace'))
        return self

    def nl(self, n: int = 1):
        self._buf.extend(b'\n' * n)
        return self

    def trenn(self, zeichen='-', breite=48):
        self.text(zeichen * breite + '\n')
        return self

    def bytes(self) -> bytes:
        return bytes(self._buf)


def _drucker_addr(terminal_nr: int) -> tuple[str, int]:
    with get_db() as cur:
        cur.execute(
            "SELECT DRUCKER_IP, DRUCKER_PORT FROM XT_KASSE_TERMINALS "
            "WHERE TERMINAL_NR = %s AND AKTIV = 1",
            (terminal_nr,)
        )
        row = cur.fetchone()
    if not row or not row['DRUCKER_IP']:
        raise RuntimeError(f"Kein Drucker für Terminal {terminal_nr} konfiguriert.")
    return row['DRUCKER_IP'], row['DRUCKER_PORT']


def _kassenlade_pin(terminal_nr: int) -> int:
    with get_db() as cur:
        cur.execute(
            "SELECT KASSENLADE FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return row['KASSENLADE'] if row else 0


def _firma_info(terminal_nr: int) -> dict:
    with get_db() as cur:
        cur.execute(
            """SELECT FIRMA_NAME, FIRMA_STRASSE, FIRMA_ORT,
                      FIRMA_UST_ID, FIRMA_STEUERNUMMER
               FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    return {
        'name':          (row and row['FIRMA_NAME'])   or config.FIRMA_NAME,
        'strasse':       (row and row['FIRMA_STRASSE']) or config.FIRMA_STRASSE,
        'ort':           (row and row['FIRMA_ORT'])     or config.FIRMA_ORT,
        'ust_id':        (row and row['FIRMA_UST_ID'])  or config.FIRMA_UST_ID,
        'steuernummer':  (row and row['FIRMA_STEUERNUMMER']) or config.FIRMA_STEUERNUMMER,
    }


def _sende(ip: str, port: int, daten: bytes):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((ip, port))
        sock.sendall(daten)
    finally:
        sock.close()


def _qr_bytes(text: str) -> bytes:
    """Erstellt ESC/POS QR-Code Bytes (Modell 2)."""
    data = text.encode('utf-8')
    length = len(data) + 3
    buf = bytearray()
    # QR-Code Modell 2
    buf += b'\x1d\x28\x6b\x04\x00\x31\x41\x32\x00'   # Modell 2
    buf += b'\x1d\x28\x6b\x03\x00\x31\x43\x06'        # Größe 6
    buf += b'\x1d\x28\x6b\x03\x00\x31\x45\x31'        # Fehlerkorrektur M
    # Daten
    pL = length & 0xFF
    pH = (length >> 8) & 0xFF
    buf += bytes([0x1d, 0x28, 0x6b, pL, pH, 0x31, 0x50, 0x30]) + data
    buf += b'\x1d\x28\x6b\x03\x00\x31\x51\x30'        # Drucken
    return bytes(buf)


def _tse_qr_text(vorgang: dict) -> str:
    """
    Erstellt den QR-Code-Text gemäß BSI TR-03153 / DSFinV-K.
    Format: V0;BON_NR;TSS_SERIAL;SIGNATUR_ZAEHLER;ZEITPUNKT_START;ZEITPUNKT_ENDE;SIGNATUR
    """
    start = vorgang.get('TSE_ZEITPUNKT_START') or ''
    ende  = vorgang.get('TSE_ZEITPUNKT_ENDE') or ''
    if hasattr(start, 'strftime'):
        start = start.strftime('%Y-%m-%dT%H:%M:%S')
    if hasattr(ende, 'strftime'):
        ende = ende.strftime('%Y-%m-%dT%H:%M:%S')
    return (
        f"V0;{vorgang.get('BON_NR','')};{vorgang.get('TSE_SERIAL','?')};"
        f"{vorgang.get('TSE_SIGNATUR_ZAEHLER','?')};{start};{ende};"
        f"{(vorgang.get('TSE_SIGNATUR') or '')[:40]}"
    )


# ── Bon-Bytes bauen ───────────────────────────────────────────

def _bon_bytes(vorgang: dict, positionen: list, zahlungen: list,
               mwst_saetze: dict, terminal_nr: int,
               ist_kopie: bool, ist_storno: bool) -> bytes:
    """
    Baut den kompletten Kassenbon als Byte-Buffer.
    vorgang: Row aus XT_KASSE_VORGAENGE
    mwst_saetze: {1: 19.0, 2: 7.0, 3: 0.0}
    """
    firma = _firma_info(terminal_nr)
    b = _Bon()
    b.raw(_ESC_INIT)

    # ── Kopf ─────────────────────────────────────────────────
    b.raw(_ALIGN_CENTER)
    b.raw(_BOLD_ON).raw(_DOUBLE_HW)
    b.text(firma['name'] + '\n')
    b.raw(_NORMAL_SIZE).raw(_BOLD_OFF)
    if firma['strasse']:
        b.text(firma['strasse'] + '\n')
    if firma['ort']:
        b.text(firma['ort'] + '\n')
    b.nl()
    if firma['ust_id']:
        b.text(f"USt-IdNr.: {firma['ust_id']}\n")
    if firma['steuernummer']:
        b.text(f"St.-Nr.: {firma['steuernummer']}\n")
    b.trenn()

    if ist_storno:
        b.raw(_BOLD_ON).text('*** STORNIERUNG ***\n').raw(_BOLD_OFF)
        b.trenn()
    if ist_kopie:
        b.raw(_BOLD_ON).text('*** KOPIE ***\n').raw(_BOLD_OFF)
        b.trenn()

    b.raw(_ALIGN_LEFT)
    bon_datum = vorgang.get('BON_DATUM') or datetime.now()
    if hasattr(bon_datum, 'strftime'):
        datum_str = bon_datum.strftime('%d.%m.%Y  %H:%M:%S')
    else:
        datum_str = str(bon_datum)

    b.raw(_BOLD_ON)
    b.text(f"Bon-Nr:    {vorgang['TERMINAL_NR']}-{vorgang['BON_NR']}\n")
    b.raw(_BOLD_OFF)
    b.text(f"Datum:    {datum_str}\n")
    b.text(f"Terminal: {terminal_nr}\n")
    b.trenn()

    # ── Positionen ───────────────────────────────────────────
    for pos in positionen:
        if pos.get('STORNIERT'):
            continue
        name  = _a(pos['BEZEICHNUNG'])
        menge = float(pos['MENGE'])
        ep    = cent_zu_euro_str(pos['EINZELPREIS_BRUTTO'])
        gp    = cent_zu_euro_str(pos['GESAMTPREIS_BRUTTO'])
        satz  = pos['MWST_SATZ']
        rab   = float(pos.get('RABATT_PROZENT') or 0)

        if menge != 1.0:
            menge_str = f"{menge:.3f}".rstrip('0').rstrip('.') if menge % 1 else str(int(menge))
            b.raw(b'\x1b\x21\x00')
            b._buf.extend(f"{name[:48]}\n".encode('cp437', errors='replace'))
            zeile2 = f"  {menge_str} x EP {ep}  {satz:.0f}%"
            b._buf.extend(f"{zeile2:<38} {gp:>9}\n".encode('cp437', errors='replace'))
        else:
            b._buf.extend(f"{name[:38]:<38} {gp:>9}\n".encode('cp437', errors='replace'))
            b._buf.extend(f"  EP {ep}  {satz:.0f}%\n".encode('cp437', errors='replace'))

        if rab > 0:
            b.text(f"  Rabatt {rab:.0f}%\n")

    b.trenn('=')

    # ── MwSt-Aufschlüsselung ─────────────────────────────────
    b.raw(_ALIGN_LEFT)
    for code, satz in sorted(mwst_saetze.items()):
        mwst_b = sum(
            p['MWST_BETRAG'] for p in positionen
            if p['STEUER_CODE'] == code and not p.get('STORNIERT')
        )
        netto_b = sum(
            p['NETTO_BETRAG'] for p in positionen
            if p['STEUER_CODE'] == code and not p.get('STORNIERT')
        )
        if mwst_b or netto_b:
            b.text(f"MwSt {satz:.0f}%: Netto {cent_zu_euro_str(netto_b)}"
                   f"  MwSt {cent_zu_euro_str(mwst_b)}\n")

    b.trenn()

    # ── Gesamtbetrag ─────────────────────────────────────────
    b.raw(_ALIGN_RIGHT).raw(_BOLD_ON)
    b.text(f"GESAMT: {cent_zu_euro_str(vorgang['BETRAG_BRUTTO'])}\n")
    b.raw(_BOLD_OFF).raw(_ALIGN_LEFT)

    # ── Zahlarten ─────────────────────────────────────────────
    for z in zahlungen:
        zahlart_text = {
            'BAR': 'Bar', 'EC': 'EC-Karte', 'KUNDENKONTO': 'Kundenkonto',
            'GUTSCHEIN': 'Gutschein', 'SONSTIGE': 'Sonstige',
        }.get(z['ZAHLART'], z['ZAHLART'])
        b.text(f"{zahlart_text:<20} {cent_zu_euro_str(z['BETRAG']):>9}\n")
        if z['ZAHLART'] == 'BAR' and z.get('BETRAG_GEGEBEN'):
            b.text(f"  Gegeben:  {cent_zu_euro_str(z['BETRAG_GEGEBEN'])}\n")
            wechsel = (z.get('WECHSELGELD') or 0)
            b.raw(_BOLD_ON)
            b.text(f"  Rueckgeld: {cent_zu_euro_str(wechsel)}\n")
            b.raw(_BOLD_OFF)

    b.trenn()

    # ── TSE-Pflichtangaben (§6 AEAO zu §146a) ────────────────
    b.raw(_FONT_B)
    b.text(f"TX:{vorgang.get('TSE_TX_ID') or 'n/a'} Sig-Z.:{vorgang.get('TSE_SIGNATUR_ZAEHLER') or 'n/a'}\n")
    serial = vorgang.get('TSE_SERIAL') or 'n/a'
    for i, chunk in enumerate([serial[j:j+54] for j in range(0, len(serial), 54)]):
        b.text(('SN:' if i == 0 else '   ') + chunk + '\n')
    sig = vorgang.get('TSE_SIGNATUR') or 'n/a'
    for i, chunk in enumerate([sig[j:j+54] for j in range(0, min(len(sig), 162), 54)]):
        b.text(('SIG:' if i == 0 else '    ') + chunk + '\n')
    b.raw(_FONT_A)

    # ── Footer ────────────────────────────────────────────────
    b.raw(_ALIGN_CENTER)
    b.text('Vielen Dank fuer Ihren Einkauf!\n')
    if vorgang.get('VORGANGSNUMMER'):
        b.raw(_NORMAL_SIZE)
        b.text(f"Beleg-Nr: {vorgang['VORGANGSNUMMER']}\n")
    b.nl(6)
    b.raw(_CUT)

    return b.bytes()


# ── Öffentliche Funktionen ────────────────────────────────────

def drucke_bon(vorgang: dict, positionen: list, zahlungen: list,
               mwst_saetze: dict, terminal_nr: int,
               ist_kopie: bool = False, ist_storno: bool = False):
    """Druckt den Kassenbon auf dem konfigurierten Netzwerkdrucker."""
    daten = _bon_bytes(vorgang, positionen, zahlungen, mwst_saetze,
                       terminal_nr, ist_kopie, ist_storno)
    ip, port = _drucker_addr(terminal_nr)
    _sende(ip, port, daten)


def oeffne_kassenlade(terminal_nr: int):
    """Öffnet die Kassenlade (falls konfiguriert)."""
    pin = _kassenlade_pin(terminal_nr)
    if pin == 0:
        return   # keine Lade konfiguriert
    cmd = _DRAWER_PIN2 if pin == 1 else _DRAWER_PIN5
    try:
        ip, port = _drucker_addr(terminal_nr)
        _sende(ip, port, _ESC_INIT + cmd)
    except Exception as e:
        log.warning("Kassenlade öffnen fehlgeschlagen: %s", e)


def drucke_xbon(terminal_nr: int, daten: dict, mwst_saetze: dict):
    """Druckt den X-Bon (Zwischenabschluss ohne Nullstellung)."""
    b = _Bon()
    b.raw(_ESC_INIT)
    firma = _firma_info(terminal_nr)
    b.raw(_ALIGN_CENTER).raw(_BOLD_ON).raw(_DOUBLE_HW)
    b.text(firma['name'] + '\n')
    b.raw(_NORMAL_SIZE).raw(_BOLD_OFF)
    b.trenn()
    b.raw(_BOLD_ON).text('X-BON (Zwischenabschluss)\n').raw(_BOLD_OFF)
    b.text(f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
    b.text(f"Terminal: {terminal_nr}\n")
    b.trenn()
    _print_abschluss_zeilen(b, daten, mwst_saetze)
    b.nl(6).raw(_CUT)
    ip, port = _drucker_addr(terminal_nr)
    _sende(ip, port, b.bytes())


def drucke_zbon(terminal_nr: int, tagesabschluss: dict, mwst_saetze: dict):
    """Druckt den Z-Bon (Tagesabschluss mit TSE-Signatur)."""
    b = _Bon()
    b.raw(_ESC_INIT)
    firma = _firma_info(terminal_nr)
    b.raw(_ALIGN_CENTER).raw(_BOLD_ON).raw(_DOUBLE_HW)
    b.text(firma['name'] + '\n')
    b.raw(_NORMAL_SIZE).raw(_BOLD_OFF)
    b.trenn()
    b.raw(_BOLD_ON).text('Z-BON (Tagesabschluss)\n').raw(_BOLD_OFF)
    b.raw(_ALIGN_LEFT)
    zeitpunkt = tagesabschluss.get('ZEITPUNKT') or datetime.now()
    if hasattr(zeitpunkt, 'strftime'):
        b.text(f"Datum:    {zeitpunkt.strftime('%d.%m.%Y %H:%M:%S')}\n")
    b.text(f"Z-Bon-Nr: {tagesabschluss['Z_NR']}\n")
    b.text(f"Terminal: {terminal_nr}\n")
    b.trenn()

    daten = {
        'anzahl_belege':        tagesabschluss['ANZAHL_BELEGE'],
        'umsatz_brutto':        tagesabschluss['UMSATZ_BRUTTO'],
        'umsatz_netto':         tagesabschluss['UMSATZ_NETTO'],
        'mwst_1':               tagesabschluss['MWST_1'],
        'mwst_2':               tagesabschluss['MWST_2'],
        'mwst_3':               tagesabschluss.get('MWST_3', 0),
        'netto_1':              tagesabschluss['NETTO_1'],
        'netto_2':              tagesabschluss['NETTO_2'],
        'netto_3':              tagesabschluss.get('NETTO_3', 0),
        'umsatz_bar':           tagesabschluss['UMSATZ_BAR'],
        'umsatz_ec':            tagesabschluss['UMSATZ_EC'],
        'umsatz_kundenkonto':   tagesabschluss['UMSATZ_KUNDENKONTO'],
        'anzahl_stornos':       tagesabschluss['ANZAHL_STORNOS'],
        'betrag_stornos':       tagesabschluss['BETRAG_STORNOS'],
        'kassenbestand_anfang': tagesabschluss['KASSENBESTAND_ANFANG'],
        'einlagen':             tagesabschluss['EINLAGEN'],
        'entnahmen':            tagesabschluss['ENTNAHMEN'],
        'kassenbestand_ende':   tagesabschluss['KASSENBESTAND_ENDE'],
    }
    _print_abschluss_zeilen(b, daten, mwst_saetze)

    # TSE
    b.trenn()
    b.raw(_BOLD_ON).text('TSE-Signatur:\n').raw(_BOLD_OFF)
    b.text(f"TX-ID:  {tagesabschluss.get('TSE_TX_ID') or 'n/a'}\n")
    b.text(f"Zaehler: {tagesabschluss.get('TSE_SIGNATUR_ZAEHLER') or 'n/a'}\n")
    sig = tagesabschluss.get('TSE_SIGNATUR') or 'n/a'
    for i in range(0, min(len(sig), 96), 48):
        b.text(sig[i:i+48] + '\n')

    b.nl(6).raw(_CUT)
    ip, port = _drucker_addr(terminal_nr)
    _sende(ip, port, b.bytes())


def _print_abschluss_zeilen(b: _Bon, d: dict, mwst_saetze: dict):
    b.raw(_BOLD_ON).text(f"Belege:       {d['anzahl_belege']}\n").raw(_BOLD_OFF)
    b.text(f"Umsatz brutto:  {cent_zu_euro_str(d['umsatz_brutto'])}\n")
    b.text(f"Umsatz netto:   {cent_zu_euro_str(d['umsatz_netto'])}\n")
    b.trenn('-', 30)
    for code, satz in sorted(mwst_saetze.items()):
        key_mwst  = f'mwst_{code}'
        key_netto = f'netto_{code}'
        mwst_b  = d.get(key_mwst, 0)
        netto_b = d.get(key_netto, 0)
        if mwst_b or netto_b:
            b.text(f"MwSt {satz:.0f}%: Netto {cent_zu_euro_str(netto_b)}"
                   f"  MwSt {cent_zu_euro_str(mwst_b)}\n")
    b.trenn('-', 30)
    b.text(f"Bar:            {cent_zu_euro_str(d['umsatz_bar'])}\n")
    b.text(f"EC-Karte:       {cent_zu_euro_str(d['umsatz_ec'])}\n")
    b.text(f"Kundenkonto:    {cent_zu_euro_str(d['umsatz_kundenkonto'])}\n")
    if d['anzahl_stornos']:
        b.text(f"Stornos:  {d['anzahl_stornos']}x  {cent_zu_euro_str(d['betrag_stornos'])}\n")
    b.trenn('-', 30)
    b.text(f"Kassenstand Anfang: {cent_zu_euro_str(d['kassenbestand_anfang'])}\n")
    b.text(f"Einlagen:           {cent_zu_euro_str(d['einlagen'])}\n")
    b.text(f"Entnahmen:          {cent_zu_euro_str(d['entnahmen'])}\n")
    b.raw(_BOLD_ON)
    b.text(f"Kassenstand Ende:   {cent_zu_euro_str(d['kassenbestand_ende'])}\n")
    b.raw(_BOLD_OFF)


def test_drucker(terminal_nr: int) -> bool:
    try:
        ip, port = _drucker_addr(terminal_nr)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((ip, port))
        sock.close()
        return True
    except Exception:
        return False
