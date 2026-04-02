"""
CAO-XT Kassen-App – Swissbit USB TSE (libWorm Python-Wrapper)

Unterstützt SE-050 und kompatible Swissbit USB-TSEs via libWorm C-Bibliothek.

Bibliothek wird in dieser Reihenfolge gesucht:
  1. Umgebungsvariable LIBWORM_PATH
  2. /usr/lib/libWorm.so          (Linux, Raspberry Pi)
  3. /usr/local/lib/libWorm.so
  4. /usr/lib/aarch64-linux-gnu/libWorm.so   (Pi 64-bit)
  5. /usr/lib/arm-linux-gnueabihf/libWorm.so (Pi 32-bit)

Installation auf dem Pi: siehe kasse-app/SWISSBIT_SETUP.md
"""
import ctypes
import base64
import os
import threading
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# ── WORM-Fehler-Codes ─────────────────────────────────────────
WORM_ERROR_NO_ERROR           = 0
WORM_ERROR_WRONG_STATE        = 1
WORM_ERROR_NOT_AUTHENTICATED  = 2
WORM_ERROR_INVALID_PARAMETER  = 3
WORM_ERROR_IO_ERROR           = 5
WORM_ERROR_CERT_EXPIRED       = 18   # BSI-Zertifikat abgelaufen
WORM_ERROR_DEACTIVATED        = 20

# ── User-IDs ─────────────────────────────────────────────────
WORM_USER_ADMIN      = 0
WORM_USER_TIME_ADMIN = 1

# ── Bekannte Fehlerbeschreibungen ─────────────────────────────
_FEHLER_TEXT = {
    0:  'Kein Fehler',
    1:  'Falscher Zustand (TSE nicht aktiviert?)',
    2:  'Nicht authentifiziert (Admin-PIN falsch?)',
    3:  'Ungültiger Parameter',
    4:  'Timeout',
    5:  'I/O-Fehler (Gerät nicht erreichbar?)',
    17: 'TSE nicht aktiviert',
    18: 'BSI-Zertifikat abgelaufen',
    20: 'TSE deaktiviert',
}

# ── Bibliothek-Suchpfade ──────────────────────────────────────
_LIBWORM_SUCHPFADE = [p for p in [
    os.environ.get('LIBWORM_PATH', ''),
    '/usr/lib/libWorm.so',
    '/usr/local/lib/libWorm.so',
    '/usr/lib/aarch64-linux-gnu/libWorm.so',
    '/usr/lib/arm-linux-gnueabihf/libWorm.so',
    '/usr/lib/x86_64-linux-gnu/libWorm.so',
] if p]

_lib: ctypes.CDLL | None = None
_lib_geladen: bool = False


def _lib_laden() -> ctypes.CDLL | None:
    """Lädt libWorm beim ersten Aufruf; gibt None zurück wenn nicht gefunden."""
    global _lib, _lib_geladen
    if _lib_geladen:
        return _lib
    _lib_geladen = True
    for pfad in _LIBWORM_SUCHPFADE:
        try:
            lib = ctypes.cdll.LoadLibrary(pfad)
            _api_einrichten(lib)
            _lib = lib
            log.info("libWorm geladen: %s", pfad)
            return _lib
        except (OSError, AttributeError) as e:
            log.debug("libWorm nicht in %s: %s", pfad, e)
    log.warning(
        "libWorm nicht gefunden. Swissbit-Integration nicht verfügbar. "
        "Installationsanleitung: kasse-app/SWISSBIT_SETUP.md"
    )
    return None


def _api_einrichten(lib: ctypes.CDLL):
    """Richtet Funktions-Signaturen für die WORM-API ein."""
    vp   = ctypes.c_void_p
    pvp  = ctypes.POINTER(ctypes.c_void_p)
    u8p  = ctypes.POINTER(ctypes.c_uint8)
    pu8p = ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8))
    u32  = ctypes.c_uint32
    pu32 = ctypes.POINTER(ctypes.c_uint32)
    u64  = ctypes.c_uint64
    pu64 = ctypes.POINTER(ctypes.c_uint64)
    i32  = ctypes.c_int32
    cp   = ctypes.c_char_p

    def fn(name, argtypes, restype=i32):
        f = getattr(lib, name)
        f.argtypes = argtypes
        f.restype  = restype

    fn('Worm_Init',              [pvp, cp])
    fn('Worm_Shutdown',          [vp])
    fn('Worm_Tse_Activate',      [vp, u8p, u32])
    fn('Worm_User_Authenticate', [vp, i32, u8p, u32])
    fn('Worm_User_Logout',       [vp, i32])
    fn('Worm_Tse_UpdateTime',    [vp, u64])
    fn('Worm_Tse_Info_SerialNumber',    [vp, pu8p, pu32])
    fn('Worm_Tse_Info_PublicKey',       [vp, pu8p, pu32])
    fn('Worm_Tse_Info_CertificationId', [vp, pu8p, pu32])
    fn('Worm_Tse_Info_CreatedSignatures', [vp, pu32])
    fn('Worm_Tse_Info_TotalLogEntries',   [vp, pu32])
    fn('Worm_Tse_Info_MaxSignatures',     [vp, pu32])
    fn('Worm_Tx_Start', [
        vp,
        cp, u32,   # clientId, len
        cp, u32,   # processType, len
        cp, u32,   # processData, len
        pu64,      # txNumber (out)
        pu64,      # creationTime (out)
    ])
    fn('Worm_Tx_Update_And_Finish', [
        vp,
        u64,       # txNumber
        cp, u32,   # clientId, len
        cp, u32,   # processType, len
        cp, u32,   # processData, len
        pu64,      # signatureCounter (out)
        pu64,      # finishTime (out)
        pu8p, pu32,  # signature (out), signatureLen (out)
    ])
    fn('Worm_Tx_Cancel', [vp, u64, cp, u32])
    fn('Worm_FreeBuffer', [ctypes.c_void_p], restype=None)


def verfuegbar() -> bool:
    """Gibt True zurück wenn libWorm geladen werden konnte."""
    return _lib_laden() is not None


# ── WormTse: Kontext-Manager für eine TSE-Sitzung ─────────────

class WormTse:
    """
    Öffnet eine libWorm-Verbindung zur TSE und schließt sie sicher wieder.

    Verwendung:
        with WormTse('/dev/sda') as tse:
            serial = tse.serial_b64()
            tx_nr, t_start = tse.tx_start('kasse-1', 'Kassenbeleg-V1', '')
            sig_ctr, t_end, sig = tse.tx_finish(tx_nr, 'kasse-1', ...)
    """

    def __init__(self, geraete_pfad: str):
        self._pfad = geraete_pfad.encode()
        self._ctx  = ctypes.c_void_p(None)
        self._lock = threading.Lock()

    def __enter__(self):
        lib = _lib_laden()
        if lib is None:
            raise RuntimeError(
                "libWorm nicht gefunden – Swissbit-TSE kann nicht angesprochen werden. "
                "Installationsanleitung: kasse-app/SWISSBIT_SETUP.md"
            )
        err = lib.Worm_Init(ctypes.byref(self._ctx), self._pfad)
        _pruefen(err, 'Worm_Init')
        return self

    def __exit__(self, *_):
        lib = _lib_laden()
        if lib and self._ctx:
            try:
                lib.Worm_Shutdown(self._ctx)
            except Exception as e:
                log.warning("Worm_Shutdown Fehler: %s", e)
            self._ctx = ctypes.c_void_p(None)

    # ── TSE-Informationen ──────────────────────────────────────

    def serial_b64(self) -> str:
        """Seriennummer als Base64-String (für Bondruck)."""
        return base64.b64encode(self._bytes_info('Worm_Tse_Info_SerialNumber')).decode()

    def public_key_b64(self) -> str:
        return base64.b64encode(self._bytes_info('Worm_Tse_Info_PublicKey')).decode()

    def zertifizierungs_id(self) -> str:
        try:
            return self._bytes_info('Worm_Tse_Info_CertificationId').decode('utf-8', errors='replace').rstrip('\x00')
        except Exception:
            return ''

    def signatur_zaehler(self) -> int:
        lib = _lib_laden()
        val = ctypes.c_uint32(0)
        lib.Worm_Tse_Info_CreatedSignatures(self._ctx, ctypes.byref(val))
        return val.value

    def max_signaturen(self) -> int:
        lib = _lib_laden()
        val = ctypes.c_uint32(0)
        lib.Worm_Tse_Info_MaxSignatures(self._ctx, ctypes.byref(val))
        return val.value

    def _bytes_info(self, fn_name: str) -> bytes:
        lib = _lib_laden()
        buf     = ctypes.POINTER(ctypes.c_uint8)()
        buf_len = ctypes.c_uint32(0)
        fn = getattr(lib, fn_name)
        err = fn(self._ctx, ctypes.byref(buf), ctypes.byref(buf_len))
        _pruefen(err, fn_name)
        data = bytes(buf[:buf_len.value])
        lib.Worm_FreeBuffer(buf)
        return data

    # ── TSE aktivieren (Ersteinrichtung) ──────────────────────

    def aktivieren(self, admin_pin: str):
        """
        Aktiviert die TSE (einmalig bei Ersteinrichtung).
        admin_pin: mind. 5 Zeichen, max. 16 Zeichen.
        """
        lib  = _lib_laden()
        pin  = admin_pin.encode()
        pin8 = (ctypes.c_uint8 * len(pin))(*pin)
        err  = lib.Worm_Tse_Activate(self._ctx, pin8, len(pin))
        _pruefen(err, 'Worm_Tse_Activate')
        log.info("Swissbit TSE aktiviert.")

    def zeit_setzen(self):
        """Systemzeit in die TSE schreiben (ohne Authentifizierung)."""
        lib = _lib_laden()
        ts  = int(datetime.now().timestamp())
        err = lib.Worm_Tse_UpdateTime(self._ctx, ctypes.c_uint64(ts))
        if err != WORM_ERROR_NO_ERROR:
            log.warning("Worm_Tse_UpdateTime: Code %d (%s) – wird ignoriert.",
                        err, _FEHLER_TEXT.get(err, '?'))

    # ── Transaktionen ─────────────────────────────────────────

    def tx_start(self, client_id: str, process_type: str,
                 process_data: str) -> tuple[int, int]:
        """
        Startet eine Transaktion.
        Rückgabe: (tx_number, creation_time_unix)
        """
        lib    = _lib_laden()
        cid    = client_id.encode()[:30]
        pt     = process_type.encode()
        pd     = process_data.encode()
        tx_nr  = ctypes.c_uint64(0)
        t_start = ctypes.c_uint64(0)
        with self._lock:
            err = lib.Worm_Tx_Start(
                self._ctx,
                cid, ctypes.c_uint32(len(cid)),
                pt,  ctypes.c_uint32(len(pt)),
                pd,  ctypes.c_uint32(len(pd)),
                ctypes.byref(tx_nr),
                ctypes.byref(t_start),
            )
        _pruefen(err, 'Worm_Tx_Start')
        return tx_nr.value, t_start.value

    def tx_finish(self, tx_number: int, client_id: str,
                  process_type: str, process_data: str) -> tuple[int, int, str]:
        """
        Schließt eine Transaktion ab.
        Rückgabe: (signatur_zaehler, finish_time_unix, signatur_base64)
        """
        lib     = _lib_laden()
        cid     = client_id.encode()[:30]
        pt      = process_type.encode()
        pd      = process_data.encode()
        sig_ctr = ctypes.c_uint64(0)
        t_end   = ctypes.c_uint64(0)
        sig_buf = ctypes.POINTER(ctypes.c_uint8)()
        sig_len = ctypes.c_uint32(0)
        with self._lock:
            err = lib.Worm_Tx_Update_And_Finish(
                self._ctx,
                ctypes.c_uint64(tx_number),
                cid, ctypes.c_uint32(len(cid)),
                pt,  ctypes.c_uint32(len(pt)),
                pd,  ctypes.c_uint32(len(pd)),
                ctypes.byref(sig_ctr),
                ctypes.byref(t_end),
                ctypes.byref(sig_buf),
                ctypes.byref(sig_len),
            )
        _pruefen(err, 'Worm_Tx_Update_And_Finish')
        sig_bytes = bytes(sig_buf[:sig_len.value])
        lib.Worm_FreeBuffer(sig_buf)
        return sig_ctr.value, t_end.value, base64.b64encode(sig_bytes).decode()

    def tx_cancel(self, tx_number: int, client_id: str):
        """Bricht eine offene Transaktion ab."""
        lib = _lib_laden()
        cid = client_id.encode()[:30]
        with self._lock:
            lib.Worm_Tx_Cancel(
                self._ctx,
                ctypes.c_uint64(tx_number),
                cid, ctypes.c_uint32(len(cid)),
            )


# ── Hilfsfunktionen ───────────────────────────────────────────

def _pruefen(err: int, fn: str):
    if err != WORM_ERROR_NO_ERROR:
        text = _FEHLER_TEXT.get(err, f'Code {err}')
        raise WormFehler(f"Swissbit TSE – {fn}: {text}", code=err)


class WormFehler(RuntimeError):
    def __init__(self, msg: str, code: int = -1):
        super().__init__(msg)
        self.code = code

    @property
    def zertifikat_abgelaufen(self) -> bool:
        return self.code == WORM_ERROR_CERT_EXPIRED


# ── Prozess-Daten (KassenSichV DSFinV-K Format) ───────────────

def prozess_daten_kassenbeleg(betraege_cent: dict) -> str:
    """
    Baut den Prozess-Daten-String für 'Kassenbeleg-V1' (normale Transaktion).

    betraege_cent: Cent-Beträge je Steuersatz (aus amounts_per_vat)
      {'NORMAL': 1234, 'REDUCED_1': 56, 'NULL': 0}

    Rückgabe: "Beleg^12.34_EUR^0.56_EUR^0.00_EUR^0.00_EUR^0.00_EUR"
    Format:   "Beleg^<gesamt>^<19%>^<7%>^<sonder1>^<sonder2>^<0%>"
    """
    def e(cent): return f"{cent / 100:.2f}_EUR"
    total = sum(betraege_cent.values())
    return (
        f"Beleg"
        f"^{e(total)}"
        f"^{e(betraege_cent.get('NORMAL', 0))}"
        f"^{e(betraege_cent.get('REDUCED_1', 0))}"
        f"^{e(betraege_cent.get('SPECIAL_1', 0))}"
        f"^{e(betraege_cent.get('SPECIAL_2', 0))}"
        f"^{e(betraege_cent.get('NULL', 0))}"
    )


def prozess_daten_storno(betraege_cent: dict) -> str:
    """Prozess-Daten-String für Storno-Transaktion (negative Beträge)."""
    def e(cent): return f"{cent / 100:.2f}_EUR"
    total = sum(betraege_cent.values())
    return (
        f"Storno-Beleg"
        f"^{e(total)}"
        f"^{e(betraege_cent.get('NORMAL', 0))}"
        f"^{e(betraege_cent.get('REDUCED_1', 0))}"
        f"^{e(betraege_cent.get('SPECIAL_1', 0))}"
        f"^{e(betraege_cent.get('SPECIAL_2', 0))}"
        f"^{e(betraege_cent.get('NULL', 0))}"
    )


def prozess_daten_abschluss(umsatz_brutto_cent: int) -> str:
    """Prozess-Daten-String für Tagesabschluss."""
    eur = f"{umsatz_brutto_cent / 100:.2f}_EUR"
    return f"Abschluss^{eur}^0.00_EUR^0.00_EUR^0.00_EUR^0.00_EUR^0.00_EUR"


def betraege_aus_positionen(positionen: list) -> dict:
    """
    Aggregiert Bruttobeträge je Fiskaly-Steuerschlüssel
    aus einer Positionsliste (wie in tse.py verwendet).
    """
    result: dict[str, int] = {}
    for pos in positionen:
        if pos.get('STORNIERT') or pos.get('storniert'):
            continue
        satz = float(pos.get('MWST_SATZ') or pos.get('mwst_satz') or 0)
        key  = _vat_key(satz)
        brutto = int(pos.get('GESAMTPREIS_BRUTTO') or pos.get('gesamtpreis_brutto') or 0)
        result[key] = result.get(key, 0) + brutto
    return result


def _vat_key(satz: float) -> str:
    if abs(satz - 19.0) < 0.1: return 'NORMAL'
    if abs(satz - 7.0)  < 0.1: return 'REDUCED_1'
    if abs(satz)        < 0.1: return 'NULL'
    return 'SPECIAL_1'


# ── Status-Abfrage (für Admin-Seite) ─────────────────────────

def tse_status_lesen(geraete_pfad: str) -> dict:
    """
    Liest alle verfügbaren Infos aus der TSE.
    Gibt ein Dict zurück das mit tse_tss_status() (Fiskaly) kompatibel ist.
    """
    try:
        with WormTse(geraete_pfad) as tse:
            serial    = tse.serial_b64()
            cert_id   = tse.zertifizierungs_id()
            sig_ctr   = tse.signatur_zaehler()
            max_sig   = tse.max_signaturen()
            pub_key   = tse.public_key_b64()
        return {
            'state':                        'INITIALIZED',
            'bsi_certification_id':          cert_id or 'unbekannt',
            '_id':                           serial[:36] if serial else '',
            'serial_number':                 serial,
            'signature_algorithm':          'ecdsa-plain-SHA384',
            'signature_timestamp_format':   'unixTime',
            'signature_counter':             sig_ctr,
            'transaction_counter':           sig_ctr,
            'number_registered_clients':     1,
            'max_number_registered_clients': 9,
            'max_signatures':                max_sig,
            'public_key':                    pub_key,
            '_version':                      'swissbit-worm',
            '_hinweis':                      None,
        }
    except WormFehler as e:
        hinweis = '⚠️ BSI-Zertifikat abgelaufen' if e.zertifikat_abgelaufen else str(e)
        return {
            'state':              'FEHLER',
            'bsi_certification_id': '',
            '_id':                '',
            'serial_number':      '',
            'signature_counter':  0,
            'transaction_counter': 0,
            'public_key':         '',
            '_version':           'swissbit-worm',
            '_hinweis':           hinweis,
        }
    except RuntimeError as e:
        return {
            'state':   'NICHT_VERFUEGBAR',
            '_hinweis': str(e),
            'bsi_certification_id': '', '_id': '', 'serial_number': '',
            'signature_counter': 0, 'transaction_counter': 0,
            'public_key': '', '_version': 'swissbit-worm',
        }
