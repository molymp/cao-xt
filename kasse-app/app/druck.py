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
from db import get_db
from datetime import datetime
import logging

log = logging.getLogger(__name__)

# ESC/POS-Kommandos
_ESC_INIT      = b'\x1b\x40'
_CODEPAGE_1252 = b'\x1b\x74\x10'   # WPC1252 (Windows-1252): €, Umlaute nativ
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

# Zeichensatz – WPC1252 druckt Umlaute und € nativ; nur typografische Sonderzeichen ersetzen
_UMLAUT_MAP = str.maketrans({
    '–': '-', '—': '-', '„': '"', '\u201c': '"', '\u201d': '"', '…': '...',
})


def _e(cent: int) -> str:
    """Cent → '1,23 €' (WPC1252-sicher)."""
    return f"{cent / 100:.2f} €".replace(".", ",")


def _a(text: str) -> str:
    return text.translate(_UMLAUT_MAP)


def _z(label: str, wert: str, breite: int = 48) -> str:
    """Label linksbündig, Wert rechtsbündig – zusammen genau 'breite' Zeichen."""
    label = _a(str(label))
    wert  = _a(str(wert))
    pad   = breite - len(label) - len(wert)
    return label + (' ' * max(pad, 1)) + wert + '\n'


class _Bon:
    """Builder-Klasse für den Byte-Buffer."""
    def __init__(self):
        self._buf = bytearray()

    def raw(self, data: bytes):
        self._buf.extend(data)
        return self

    def text(self, s: str):
        self._buf.extend(_a(s).encode('cp1252', errors='replace'))
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
            "SELECT FIRMA_NAME, FIRMA_ZUSATZ "
            "FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
            (terminal_nr,)
        )
        t = cur.fetchone() or {}
        cur.execute("SELECT * FROM FIRMA ORDER BY REC_ID DESC LIMIT 1")
        f = cur.fetchone() or {}

    # Firmenname: Terminal-Eintrag hat Vorrang (wenn gesetzt)
    name = t.get('FIRMA_NAME') or \
           ' '.join(filter(None, [f.get('NAME1'), f.get('NAME2'), f.get('NAME3')])) or \
           config.FIRMA_NAME

    strasse = ' '.join(filter(None, [f.get('STRASSE'), f.get('HAUSNR')])) \
              or config.FIRMA_STRASSE
    ort = ' '.join(filter(None, [f.get('PLZ'), f.get('ORT')])) \
          or config.FIRMA_ORT

    return {
        'name':    name,
        'zusatz':  t.get('FIRMA_ZUSATZ') or '',
        'strasse': strasse,
        'ort':     ort,
    }


def _sende(ip: str, port: int, daten: bytes):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((ip, port))
        sock.sendall(daten)
    finally:
        sock.close()


def _qr_bytes(text: str, groesse: int = 3) -> bytes:
    """
    Erstellt ESC/POS QR-Code Bytes (Modell 2).
    groesse: Modulgröße 1 (kleinst) … 8 (größt), Standard 3.
    """
    data = text.encode('utf-8')
    length = len(data) + 3
    buf = bytearray()
    buf += b'\x1d\x28\x6b\x04\x00\x31\x41\x32\x00'        # Modell 2
    buf += bytes([0x1d, 0x28, 0x6b, 0x03, 0x00, 0x31, 0x43, groesse])  # Größe
    buf += b'\x1d\x28\x6b\x03\x00\x31\x45\x31'             # Fehlerkorrektur M
    pL = length & 0xFF
    pH = (length >> 8) & 0xFF
    buf += bytes([0x1d, 0x28, 0x6b, pL, pH, 0x31, 0x50, 0x30]) + data
    buf += b'\x1d\x28\x6b\x03\x00\x31\x51\x30'             # Drucken
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


# ── Bon-Kopf (Name + Adresse + Slogan) ───────────────────────

def _drucke_kopf(b: _Bon, firma: dict):
    """Druckt den zentrierten Firmenkopf auf den Bon (Name, Adresse, Infos)."""
    b.raw(_ALIGN_CENTER)
    b.raw(_BOLD_ON).raw(_DOUBLE_HW)
    b.text(firma['name'] + '\n')
    b.raw(_NORMAL_SIZE).raw(_BOLD_OFF)
    if firma.get('zusatz'):
        b.text(firma['zusatz'] + '\n')
    adresse = ' '.join(filter(None, [firma['strasse'], firma['ort']]))
    if adresse:
        b.text(adresse + '\n')
    b.text('Mo.-Fr. 6:30h-18:00h     Sa. 7:00-12:00h\n')
    b.text('Tel. 08847/6956156    habacher-dorfladen.de\n')


# ── Bon-Bytes bauen ───────────────────────────────────────────

def _bon_bytes(vorgang: dict, positionen: list, zahlungen: list,
               mwst_saetze: dict, terminal_nr: int,
               ist_kopie: bool, ist_storno: bool,
               qr_code: bool = False,
               trainings_modus: bool = False,
               nicht_produktiv: bool = False) -> bytes:
    """
    Baut den kompletten Kassenbon als Byte-Buffer.
    vorgang: Row aus XT_KASSE_VORGAENGE
    mwst_saetze: {1: 19.0, 2: 7.0, 3: 0.0}
    """
    firma = _firma_info(terminal_nr)
    b = _Bon()
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)

    # Klassifizierung: training = kein TSE / Trainings-Modus
    #                  sandbox  = Fiskaly-Testumgebung (echte Sig, aber nicht produktiv)
    tse_serial  = (vorgang.get('TSE_SERIAL') or '').strip()
    ist_training = trainings_modus or tse_serial in ('', 'TRAININGSMODUS')
    ist_sandbox  = nicht_produktiv and not ist_training
    nicht_live   = ist_training or ist_sandbox

    # ── Kopf ─────────────────────────────────────────────────
    _drucke_kopf(b, firma)
    b.trenn()

    if ist_training:
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
        b.raw(_BOLD_ON).text('Kein steuerrelevanter Beleg!\n').raw(_BOLD_OFF)
        b.trenn()
    elif ist_sandbox:
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TEST-BON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
        b.raw(_BOLD_ON).text('Fiskaly Sandbox – kein steuerrelevanter Beleg!\n').raw(_BOLD_OFF)
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
    beleg_nr = vorgang.get('VORGANGSNUMMER') or f"{vorgang['TERMINAL_NR']}-{vorgang['BON_NR']}"
    b.text(f"Beleg: {beleg_nr}  {datum_str}\n")
    b.raw(_BOLD_OFF)
    if vorgang.get('KUNDEN_NAME'):
        b.trenn()
        nr   = vorgang.get('KUNDEN_NR')
        ort  = vorgang.get('KUNDEN_ORT')
        b.raw(_BOLD_ON)
        b.text(f"Kunde:  {_a(vorgang['KUNDEN_NAME'])}\n")
        b.raw(_BOLD_OFF)
        if nr:
            b.text(f"Kunden-Nr: {_a(nr)}\n")
        if ort:
            b.text(f"Ort:    {_a(ort)}\n")
    if vorgang.get('NOTIZ'):
        b.trenn()
        b.raw(_BOLD_ON)
        b.text(f"Betreff: {_a(vorgang['NOTIZ'])}\n")
        b.raw(_BOLD_OFF)
    b.trenn()

    # ── Positionen ───────────────────────────────────────────
    for pos in positionen:
        if pos.get('STORNIERT'):
            continue
        name  = _a(pos['BEZEICHNUNG'])
        menge = float(pos['MENGE'])
        ep    = _e(pos['EINZELPREIS_BRUTTO'])
        gp    = _e(pos['GESAMTPREIS_BRUTTO'])
        satz  = pos['MWST_SATZ']

        ep_orig = pos.get('EP_ORIGINAL')
        ep_hinweis = f" (statt {_e(ep_orig)})" if ep_orig else ""

        if menge != 1.0:
            menge_str = f"{menge:.3f}".rstrip('0').rstrip('.') if menge % 1 else str(int(menge))
            b.raw(b'\x1b\x21\x00')
            b.text(f"{name[:48]}\n")
            zeile2 = f"  {menge_str} x EP {ep}{ep_hinweis}  {satz:.0f}%"
            b.text(f"{zeile2:<36} {gp:>11}\n")
        else:
            b.text(f"{name[:36]:<36} {gp:>11}\n")
            b.text(f"  EP {ep}{ep_hinweis}  {satz:.0f}%\n")

    b.trenn('=')

    # ── Gesamtbetrag ─────────────────────────────────────────
    b.raw(_ALIGN_RIGHT).raw(_BOLD_ON)
    b.text(f"GESAMT: {_e(vorgang['BETRAG_BRUTTO'])}\n")
    b.raw(_BOLD_OFF).raw(_ALIGN_LEFT)
    b.trenn()

    # ── Zahlarten ─────────────────────────────────────────────
    for z in zahlungen:
        zahlart_text = {
            'BAR': 'Bar', 'EC': 'Unbar / Karte', 'KUNDENKONTO': 'Kundenkonto',
            'GUTSCHEIN': 'Gutschein', 'SONSTIGE': 'Sonstige',
        }.get(z['ZAHLART'], z['ZAHLART'])
        if z['ZAHLART'] == 'BAR' and z.get('BETRAG_GEGEBEN'):
            # Zahlart in "Gegeben"-Zeile, kein separater Betrag-Posten
            wechsel = z.get('WECHSELGELD') or 0
            label_geg = f"{zahlart_text} Gegeben:"
            b.text(f"{label_geg:<36} {_e(z['BETRAG_GEGEBEN']):>11}\n")
            b.raw(_BOLD_ON)
            b.text(f"{'Rückgeld:':<36} {_e(wechsel):>11}\n")
            b.raw(_BOLD_OFF)
        else:
            b.text(f"{zahlart_text:<36} {_e(z['BETRAG']):>11}\n")

    b.trenn()

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
            b.text(f"MwSt {satz:.0f}%: Netto {_e(netto_b)}"
                   f"  MwSt {_e(mwst_b)}\n")

    b.trenn()

    # ── Footer ────────────────────────────────────────────────
    b.raw(_ALIGN_CENTER)
    b.text('Vielen Dank fuer Ihren Einkauf!\n')

    # ── TSE-Pflichtangaben + QR-Code ─────────────────────────
    # QR-Code links, TSE-Text direkt darunter – eine kompakte Einheit
    b.raw(_ALIGN_LEFT).trenn()
    if ist_training:
        b.raw(_FONT_B)
        b.text('KEIN STEUERRELEVANTER BELEG – KEINE LIVE-TSE\n')
        b.raw(_FONT_A)
        b.trenn()
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
    elif ist_sandbox:
        # Echte TSE-Signatur vorhanden, aber Testumgebung
        if qr_code:
            b.raw(_ALIGN_LEFT)
            b.raw(_qr_bytes(_tse_qr_text(vorgang)))
        b.raw(_FONT_B)
        _W = 64
        tx_str   = str(vorgang.get('TSE_TX_ID') or 'n/a')
        sigz_str = str(vorgang.get('TSE_SIGNATUR_ZAEHLER') or 'n/a')
        serial   = vorgang.get('TSE_SERIAL') or 'n/a'
        sig      = vorgang.get('TSE_SIGNATUR') or 'n/a'
        stream   = f"TX:{tx_str} Sig-Z.:{sigz_str} SN:" + serial + " SIG:" + sig[:_W * 3]
        for i in range(0, len(stream), _W):
            b.text(stream[i:i + _W] + '\n')
        b.raw(_FONT_A)
        b.trenn()
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TEST-BON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
    else:
        if qr_code:
            b.raw(_ALIGN_LEFT)
            b.raw(_qr_bytes(_tse_qr_text(vorgang)))
        b.raw(_FONT_B)
        # Font-B-Zeilenbreite: 80mm-Drucker = 576 Punkte / 9 Punkte je Zeichen = 64
        _W = 64
        tx_str   = str(vorgang.get('TSE_TX_ID') or 'n/a')
        sigz_str = str(vorgang.get('TSE_SIGNATUR_ZAEHLER') or 'n/a')
        serial   = vorgang.get('TSE_SERIAL') or 'n/a'
        sig      = vorgang.get('TSE_SIGNATUR') or 'n/a'
        sig_max  = _W * 3
        stream   = (f"TX:{tx_str} Sig-Z.:{sigz_str} SN:"
                    + serial + " SIG:" + sig[:sig_max])
        for i in range(0, len(stream), _W):
            b.text(stream[i:i + _W] + '\n')
        b.raw(_FONT_A)

    b.nl(6)
    b.raw(_CUT)

    return b.bytes()


# ── Öffentliche Funktionen ────────────────────────────────────

def drucke_bon(vorgang: dict, positionen: list, zahlungen: list,
               mwst_saetze: dict, terminal_nr: int,
               ist_kopie: bool = False, ist_storno: bool = False,
               qr_code: bool = False, trainings_modus: bool = False,
               nicht_produktiv: bool = False):
    """Druckt den Kassenbon auf dem konfigurierten Netzwerkdrucker."""
    daten = _bon_bytes(vorgang, positionen, zahlungen, mwst_saetze,
                       terminal_nr, ist_kopie, ist_storno, qr_code,
                       trainings_modus, nicht_produktiv)
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
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)
    firma = _firma_info(terminal_nr)
    _drucke_kopf(b, firma)
    b.trenn()
    b.raw(_BOLD_ON).text('X-BON (Zwischenabschluss)\n').raw(_BOLD_OFF)
    b.text(f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
    b.text(f"Terminal: {terminal_nr}\n")
    b.trenn()
    _print_abschluss_zeilen(b, daten, mwst_saetze)
    b.nl(6).raw(_CUT)
    ip, port = _drucker_addr(terminal_nr)
    _sende(ip, port, b.bytes())


def drucke_zbon(terminal_nr: int, tagesabschluss: dict, mwst_saetze: dict,
                trainings_modus: bool = False, nicht_produktiv: bool = False):
    """Druckt den Z-Bon (Tagesabschluss mit TSE-Signatur)."""
    ist_training = trainings_modus
    ist_sandbox  = nicht_produktiv and not ist_training

    b = _Bon()
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)
    firma = _firma_info(terminal_nr)
    _drucke_kopf(b, firma)
    b.trenn()

    if ist_training:
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
        b.raw(_BOLD_ON).text('Kein steuerrelevanter Beleg!\n').raw(_BOLD_OFF)
        b.trenn()
    elif ist_sandbox:
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TEST-BON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
        b.raw(_BOLD_ON).text('Fiskaly Sandbox – kein steuerrelevanter Beleg!\n').raw(_BOLD_OFF)
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
        'umsatz_bar':                tagesabschluss['UMSATZ_BAR'],
        'umsatz_ec':                 tagesabschluss['UMSATZ_EC'],
        'umsatz_kundenkonto':        tagesabschluss.get('UMSATZ_KUNDENKONTO') or 0,
        'anzahl_belege_kundenkonto': tagesabschluss.get('ANZAHL_BELEGE_KUNDENKONTO') or 0,
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

    if ist_training:
        b.trenn()
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
    elif ist_sandbox:
        b.trenn()
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TEST-BON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)

    b.nl(6).raw(_CUT)
    ip, port = _drucker_addr(terminal_nr)
    _sende(ip, port, b.bytes())


def _print_abschluss_zeilen(b: _Bon, d: dict, mwst_saetze: dict):
    b.raw(_BOLD_ON).text(_z('Belege:', str(d['anzahl_belege']))).raw(_BOLD_OFF)
    b.text(_z('Umsatz brutto:', _e(d['umsatz_brutto'])))
    b.text(_z('Umsatz netto:',  _e(d['umsatz_netto'])))
    b.trenn()
    for code, satz in sorted(mwst_saetze.items()):
        key_mwst  = f'mwst_{code}'
        key_netto = f'netto_{code}'
        mwst_b  = d.get(key_mwst, 0)
        netto_b = d.get(key_netto, 0)
        if mwst_b or netto_b:
            b.text(_z(f'  Netto {satz:.0f}%:', _e(netto_b)))
            b.text(_z(f'  Steuer {satz:.0f}%:', _e(mwst_b)))
    b.trenn()
    b.text(_z('Bar:',          _e(d['umsatz_bar'])))
    b.text(_z('Unbar/Karte:',  _e(d['umsatz_ec'])))
    if d['anzahl_stornos']:
        b.text(_z(f"Stornos ({d['anzahl_stornos']}x):", _e(d['betrag_stornos'])))
    b.trenn()
    b.text(_z('Kassenstand Anfang:', _e(d['kassenbestand_anfang'])))
    b.text(_z('Einlagen:',           _e(d['einlagen'])))
    b.text(_z('Entnahmen:',          _e(d['entnahmen'])))
    b.raw(_BOLD_ON)
    b.text(_z('Kassenstand Ende:', _e(d['kassenbestand_ende'])))
    b.raw(_BOLD_OFF)
    if d.get('umsatz_kundenkonto'):
        b.trenn()
        n = d.get('anzahl_belege_kundenkonto', 0)
        b.text(_z(f'Kundenkonto ({n}x):', _e(d['umsatz_kundenkonto'])))
        b.text('(kein Kassenumsatz)\n')


def _lieferschein_bytes(ls: dict, positionen: list, firma: dict,
                        kopie: bool = False) -> bytes:
    """Baut den Lieferschein-Bon als ESC/POS-Byte-Buffer (ohne Preise)."""
    b = _Bon()
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)

    _drucke_kopf(b, firma)
    b.trenn()

    if kopie:
        b.raw(_ALIGN_CENTER).raw(_BOLD_ON)
        b.text('* KUNDENKOPIE *\n')
        b.raw(_BOLD_OFF).raw(_ALIGN_LEFT)
        b.trenn()

    b.raw(_ALIGN_CENTER).raw(_BOLD_ON)
    b.text('L I E F E R S C H E I N\n')
    b.raw(_BOLD_OFF).raw(_ALIGN_LEFT)
    b.trenn()

    # Kopfzeile: Nummer + Datum
    ldatum = ls.get('LDATUM') or ls.get('ERSTELLT') or datetime.now()
    if hasattr(ldatum, 'strftime'):
        datum_str = ldatum.strftime('%d.%m.%Y')
    else:
        datum_str = str(ldatum)[:10]

    b.text(f"Nr.:   {_a(ls.get('VLSNUM') or '')}\n")
    b.text(f"Datum: {datum_str}\n")

    # Lieferart (aus DB gelesen, JOIN in drucke_lieferschein)
    liefart_name = _a(ls.get('LIEFART_NAME') or '')
    if liefart_name:
        b.text(f"Versandart: {liefart_name}\n")

    # Projekttext (aus Betreff-Feld)
    projekt = _a(ls.get('PROJEKT') or '')
    if projekt:
        b.text(f"Betreff: {projekt}\n")

    # Kunde
    name1 = _a(ls.get('KUN_NAME1') or '')
    name2 = _a(ls.get('KUN_NAME2') or '')
    strasse = _a(ls.get('KUN_STRASSE') or '')
    plz_ort = ' '.join(filter(None, [ls.get('KUN_PLZ'), ls.get('KUN_ORT')]))
    if name1:
        b.trenn()
        b.raw(_BOLD_ON)
        b.text(f"Kunde: {name1}\n")
        b.raw(_BOLD_OFF)
        if name2:
            b.text(f"       {name2}\n")
        if strasse:
            b.text(f"       {strasse}\n")
        if plz_ort:
            b.text(f"       {_a(plz_ort)}\n")

    b.trenn()

    # Positionen – alles in Font A (48 Zeichen), keine Preise
    b.text(_z('Pos  Bezeichnung', 'Menge'))
    b.trenn()

    for pos in positionen:
        nr     = int(pos.get('POSITION') or 0)
        name   = _a(str(pos.get('BEZEICHNUNG') or ''))
        artnum = _a(str(pos.get('ARTNUM') or '').strip())
        menge  = float(pos.get('MENGE') or 0)
        me     = _a(str(pos.get('ME_EINHEIT') or 'Stk'))

        menge_str = f"{menge:.3f}".rstrip('0').rstrip('.') if menge % 1 else str(int(menge))
        menge_disp = f"{menge_str} {me}"

        # Zeile 1: Pos + Bezeichnung (bis 43 Zeichen)
        b.text(f"{nr:>3}. {name[:43]}\n")
        # Zeile 2: Artikelnummer links (wenn vorhanden), Menge rechtsbündig
        artnr_str = f"     Art-Nr: {artnum}" if artnum else ''
        b.text(_z(artnr_str, menge_disp))

    b.trenn()

    # Unterschriftszeile – Leerzeilen als Schreibfläche
    b.nl(3)
    b.text('Empfangen von: _________________________________\n')
    b.nl(3)
    b.text('Datum: _________________________________________\n')
    b.nl(3)
    b.text('Unterschrift: __________________________________\n')

    b.nl(6)
    b.raw(_CUT)
    return b.bytes()


def drucke_lieferschein(terminal_nr: int, lieferschein_id: int,
                        mit_kopie: bool = False) -> None:
    """Druckt einen Lieferschein-Bon mit Unterschriftszeile (ohne Preise).
    Bei mit_kopie=True wird ein zweiter Bon als Kundenkopie gedruckt."""
    firma = _firma_info(terminal_nr)
    ip, port = _drucker_addr(terminal_nr)

    with get_db() as cur:
        cur.execute("SELECT * FROM LIEFERSCHEIN WHERE REC_ID = %s", (lieferschein_id,))
        ls = cur.fetchone()
        if not ls:
            raise RuntimeError(f"Lieferschein {lieferschein_id} nicht gefunden.")

        # Lieferart-Name separat laden – robust gegen fehlende Tabelle / abweichenden Typ
        liefart_name = ''
        try:
            liefart_val = ls.get('LIEFART')
            if liefart_val:
                cur.execute(
                    "SELECT NAME FROM LIEFERARTEN WHERE REC_ID = %s LIMIT 1",
                    (liefart_val,)
                )
                row = cur.fetchone()
                if row:
                    liefart_name = row['NAME'] or ''
        except Exception as _le:
            log.warning("LIEFERARTEN-Lookup beim Druck fehlgeschlagen: %s", _le)
        ls = dict(ls)
        ls['LIEFART_NAME'] = liefart_name

        cur.execute(
            "SELECT * FROM LIEFERSCHEIN_POS "
            "WHERE LIEFERSCHEIN_ID = %s ORDER BY POSITION",
            (ls['REC_ID'],)
        )
        positionen = cur.fetchall()

    daten = _lieferschein_bytes(ls, positionen, firma)
    _sende(ip, port, daten)

    if mit_kopie:
        daten_kopie = _lieferschein_bytes(ls, positionen, firma, kopie=True)
        _sende(ip, port, daten_kopie)


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
