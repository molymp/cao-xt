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
            "SELECT FIRMA_NAME, FIRMA_STRASSE, FIRMA_ORT, "
            "FIRMA_UST_ID, FIRMA_STEUERNUMMER "
            "FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s",
            (terminal_nr,)
        )
        t = cur.fetchone() or {}
        cur.execute("SELECT * FROM FIRMA LIMIT 1")
        f = cur.fetchone() or {}

    name = (
        ' '.join(filter(None, [f.get('NAME1'), f.get('NAME2'), f.get('NAME3')]))
        or t.get('FIRMA_NAME') or config.FIRMA_NAME
    )
    strasse = ' '.join(filter(None, [f.get('STRASSE'), f.get('HAUSNR')])) \
              or t.get('FIRMA_STRASSE') or config.FIRMA_STRASSE
    ort = ' '.join(filter(None, [f.get('PLZ'), f.get('ORT')])) \
          or t.get('FIRMA_ORT') or config.FIRMA_ORT

    return {
        'name':         name,
        'strasse':      strasse,
        'ort':          ort,
        'ust_id':       f.get('UST_ID') or t.get('FIRMA_UST_ID') or config.FIRMA_UST_ID,
        'steuernummer': f.get('STEUERNUMMER') or t.get('FIRMA_STEUERNUMMER') or config.FIRMA_STEUERNUMMER,
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


# ── Bon-Kopf (Name + Adresse + Slogan) ───────────────────────

def _drucke_kopf(b: _Bon, firma: dict):
    """Druckt den zentrierten Firmenkopf auf den Bon (Name, Adresse, Infos)."""
    b.raw(_ALIGN_CENTER)
    b.raw(_BOLD_ON).raw(_DOUBLE_HW)
    b.text(firma['name'] + '\n')
    b.raw(_NORMAL_SIZE).raw(_BOLD_OFF)
    b.text('Der Laden von Bürgern für Bürger\n')
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
               trainings_modus: bool = False) -> bytes:
    """
    Baut den kompletten Kassenbon als Byte-Buffer.
    vorgang: Row aus XT_KASSE_VORGAENGE
    mwst_saetze: {1: 19.0, 2: 7.0, 3: 0.0}
    """
    firma = _firma_info(terminal_nr)
    b = _Bon()
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)

    # ── Kopf ─────────────────────────────────────────────────
    _drucke_kopf(b, firma)
    b.nl()
    if firma['ust_id']:
        b.text(f"USt-IdNr.: {firma['ust_id']}\n")
    if firma['steuernummer']:
        b.text(f"St.-Nr.: {firma['steuernummer']}\n")
    b.trenn()

    if trainings_modus:
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
        b.raw(_BOLD_ON).text('Kein steuerrelevanter Beleg!\n').raw(_BOLD_OFF)
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
    b.text(f"Bon-Nr: {vorgang['TERMINAL_NR']}-{vorgang['BON_NR']}  {datum_str}\n")
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
    if vorgang.get('VORGANGSNUMMER'):
        b.raw(_NORMAL_SIZE)
        b.text(f"Beleg-Nr: {vorgang['VORGANGSNUMMER']}\n")

    # ── QR-Code (optional, BSI TR-03153) ─────────────────────
    if qr_code and not trainings_modus:
        b.raw(_ALIGN_CENTER)
        b.raw(_qr_bytes(_tse_qr_text(vorgang)))
        b.raw(_ALIGN_LEFT)

    # ── TSE-Pflichtangaben (§6 AEAO zu §146a) / Trainings-Hinweis ────────
    b.raw(_ALIGN_LEFT).trenn()
    if trainings_modus:
        b.raw(_FONT_B)
        b.text('TRAININGSMODUS – KEIN STEUERRELEVANTER BELEG\n')
        b.text('Keine TSE-Signatur vorhanden.\n')
        b.raw(_FONT_A)
        b.trenn()
        b.raw(_ALIGN_CENTER).raw(_DOUBLE_HW)
        b.text('TRAININGSBON\n')
        b.raw(_NORMAL_SIZE).raw(_ALIGN_LEFT)
    else:
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
               qr_code: bool = False, trainings_modus: bool = False):
    """Druckt den Kassenbon auf dem konfigurierten Netzwerkdrucker."""
    daten = _bon_bytes(vorgang, positionen, zahlungen, mwst_saetze,
                       terminal_nr, ist_kopie, ist_storno, qr_code, trainings_modus)
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


def drucke_zbon(terminal_nr: int, tagesabschluss: dict, mwst_saetze: dict):
    """Druckt den Z-Bon (Tagesabschluss mit TSE-Signatur)."""
    b = _Bon()
    b.raw(_ESC_INIT).raw(_CODEPAGE_1252)
    firma = _firma_info(terminal_nr)
    _drucke_kopf(b, firma)
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
    b.text(f"Umsatz brutto:  {_e(d['umsatz_brutto'])}\n")
    b.text(f"Umsatz netto:   {_e(d['umsatz_netto'])}\n")
    b.trenn('-', 30)
    for code, satz in sorted(mwst_saetze.items()):
        key_mwst  = f'mwst_{code}'
        key_netto = f'netto_{code}'
        mwst_b  = d.get(key_mwst, 0)
        netto_b = d.get(key_netto, 0)
        if mwst_b or netto_b:
            b.text(f"MwSt {satz:.0f}%: Netto {_e(netto_b)}"
                   f"  MwSt {_e(mwst_b)}\n")
    b.trenn('-', 30)
    b.text(f"Bar:            {_e(d['umsatz_bar'])}\n")
    b.text(f"Unbar/Karte:    {_e(d['umsatz_ec'])}\n")
    b.text(f"Kundenkonto:    {_e(d['umsatz_kundenkonto'])}\n")
    if d['anzahl_stornos']:
        b.text(f"Stornos:  {d['anzahl_stornos']}x  {_e(d['betrag_stornos'])}\n")
    b.trenn('-', 30)
    b.text(f"Kassenstand Anfang: {_e(d['kassenbestand_anfang'])}\n")
    b.text(f"Einlagen:           {_e(d['einlagen'])}\n")
    b.text(f"Entnahmen:          {_e(d['entnahmen'])}\n")
    b.raw(_BOLD_ON)
    b.text(f"Kassenstand Ende:   {_e(d['kassenbestand_ende'])}\n")
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
