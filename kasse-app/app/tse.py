"""
CAO-XT Kassen-App – TSE-Dispatcher
Unterstützt mehrere TSE-Typen parallel und Trainings-/Demo-Modus.

TSE-Typen:
  FISKALY  – Fiskaly Cloud TSE (Standard)
  SWISSBIT – Swissbit USB TSE via libWorm
  DEMO     – Trainings-/Demo-Modus: keine echte Signierung

Ablauf pro Kassiervorgang (alle TSE-Typen):
  1. tse_start_transaktion()   → tx_id, revision=1
  2. tse_finish_transaktion()  → Signatur, Seriennummer, Zähler
  3. tse_cancel_transaktion()  → bei Abbruch

Für Tagesabschluss (Z-Bon):
  1. tse_tagesabschluss()      → signierter Z-Bon-Eintrag

TSE-Verwaltung:
  tse_geraete_liste()          → alle TSE-Geräte aus XT_KASSE_TSE_GERAETE
  tse_geraet_speichern()       → neues TSE-Gerät anlegen / aktualisieren
  tse_geraet_aktivieren()      → TSE für Terminal aktivieren (TSE_ID setzen)
  tse_trainings_modus_setzen() → Trainings-Modus ein/aus

Alle TSE-Aktionen werden in XT_KASSE_TSE_LOG protokolliert.
"""
import uuid
import time
import threading
from datetime import datetime
import requests
import config
from db import get_db
import logging
import swissbit_worm

log = logging.getLogger(__name__)

# ── Thread-sicheres Token-Cache ───────────────────────────────
_token_lock = threading.Lock()
_token_cache: dict[int, dict] = {}   # terminal_nr → {token, expires_at}


def _terminal_config(terminal_nr: int) -> dict:
    """
    Liest TSE-Konfiguration: Terminal + aktives TSE-Gerät.

    Priorität: XT_KASSE_TSE_GERAETE (via TSE_ID) > Legacy-Spalten in TERMINALS.
    Gibt einen normalisierten Dict zurück mit einheitlichen Schlüsseln:
      TRAININGS_MODUS, TSE_TYP, FISKALY_*, SWISSBIT_*, FISKALY_CLIENT_ID
    """
    with get_db() as cur:
        cur.execute(
            """SELECT
                  t.TERMINAL_NR, t.AKTIV,
                  t.TRAININGS_MODUS,
                  t.TSE_ID,
                  t.FISKALY_CLIENT_ID,
                  -- Legacy-Spalten (Fallback falls TSE_ID noch nicht gesetzt)
                  t.FISKALY_API_KEY     AS LEG_API_KEY,
                  t.FISKALY_API_SECRET  AS LEG_API_SECRET,
                  t.FISKALY_TSS_ID      AS LEG_TSS_ID,
                  t.FISKALY_ENV         AS LEG_ENV,
                  t.FISKALY_ADMIN_PIN   AS LEG_ADMIN_PIN,
                  t.FISKALY_ADMIN_PUK   AS LEG_ADMIN_PUK,
                  -- TSE-Gerät (neue Architektur)
                  g.REC_ID              AS TSE_REC_ID,
                  g.TYP                 AS TSE_TYP,
                  g.BEZEICHNUNG         AS TSE_BEZEICHNUNG,
                  g.FISKALY_ENV,
                  g.FISKALY_API_KEY,
                  g.FISKALY_API_SECRET,
                  g.FISKALY_TSS_ID,
                  g.FISKALY_ADMIN_PIN,
                  g.FISKALY_ADMIN_PUK,
                  g.SWISSBIT_PFAD,
                  g.SWISSBIT_ADMIN_PIN,
                  g.SWISSBIT_ADMIN_PUK,
                  g.ZERTIFIKAT_GUELTIG_BIS
               FROM XT_KASSE_TERMINALS t
               LEFT JOIN XT_KASSE_TSE_GERAETE g ON t.TSE_ID = g.REC_ID
               WHERE t.TERMINAL_NR = %s AND t.AKTIV = 1""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Terminal {terminal_nr} nicht in XT_KASSE_TERMINALS gefunden.")

    cfg = dict(row)

    # ── TSE-Felder normalisieren ────────────────────────────────
    if cfg.get('TSE_REC_ID'):
        # Neue Architektur: Felder kommen aus XT_KASSE_TSE_GERAETE (schon korrekt benannt)
        cfg['TSE_TYP'] = cfg.get('TSE_TYP') or 'FISKALY'
    else:
        # Legacy: Fiskaly-Spalten direkt aus XT_KASSE_TERMINALS
        cfg['TSE_TYP']            = 'FISKALY'
        cfg['FISKALY_ENV']        = cfg.get('LEG_ENV') or 'test'
        cfg['FISKALY_API_KEY']    = cfg.get('LEG_API_KEY') or ''
        cfg['FISKALY_API_SECRET'] = cfg.get('LEG_API_SECRET') or ''
        cfg['FISKALY_TSS_ID']     = cfg.get('LEG_TSS_ID') or ''
        cfg['FISKALY_ADMIN_PIN']  = cfg.get('LEG_ADMIN_PIN') or ''
        cfg['FISKALY_ADMIN_PUK']  = cfg.get('LEG_ADMIN_PUK') or ''

    # DEMO-Typ → immer Trainings-Modus
    if cfg.get('TSE_TYP') == 'DEMO':
        cfg['TRAININGS_MODUS'] = 1

    return cfg


def _ist_training(tconf: dict) -> bool:
    """Gibt True zurück wenn Trainings-/Demo-Modus aktiv."""
    return bool(tconf.get('TRAININGS_MODUS'))


# ── Trainings-Modus Dummy-Rückgaben ───────────────────────────

def _dummy_tx_id() -> str:
    return f'DEMO-{str(uuid.uuid4())[:8].upper()}'


def _dummy_start_result() -> dict:
    return {
        'tx_id':           _dummy_tx_id(),
        'revision':        1,
        'zeitpunkt_start': datetime.now(),
    }


def _dummy_finish_result(tx_id: str, revision: int = 2) -> dict:
    return {
        'tx_id':              tx_id,
        'revision':           revision,
        'signatur':           'TRAININGSMODUS-KEINE-ECHTE-SIGNATUR',
        'signatur_zaehler':   0,
        'zeitpunkt_start':    datetime.now(),
        'zeitpunkt_ende':     datetime.now(),
        'tss_serial':         'TRAININGSMODUS',
        'log_time_format':    '',
        'process_type':       '',
        'process_data':       '',
    }


def _assert_fiskaly(tconf: dict) -> None:
    """Wirft RuntimeError wenn Fiskaly API-Key fehlt (nach TSE-Typ-Routing aufgerufen)."""
    if not tconf.get('FISKALY_API_KEY'):
        raise RuntimeError(
            f"Terminal {tconf.get('TERMINAL_NR')}: Fiskaly API-Key nicht konfiguriert. "
            "Bitte in Admin → TSE-Verwaltung eintragen."
        )


# ── Swissbit-Hilfsfunktionen ──────────────────────────────────

def _swissbit_pfad(tconf: dict) -> str:
    pfad = (tconf.get('SWISSBIT_PFAD') or '').strip()
    if not pfad:
        raise RuntimeError(
            "SWISSBIT_PFAD nicht konfiguriert. "
            "Bitte in Admin → TSE-Verwaltung den Gerätepfad eintragen (z.B. /dev/sda)."
        )
    return pfad


def _swissbit_client_id(terminal_nr: int) -> str:
    """Swissbit clientId – max 30 Zeichen."""
    return f"kasse-{terminal_nr}"[:30]


def _swissbit_start(tconf: dict, terminal_nr: int, vorgang_id: int) -> dict:
    """Startet eine Swissbit-Transaktion via libWorm."""
    pfad      = _swissbit_pfad(tconf)
    client_id = _swissbit_client_id(terminal_nr)
    with swissbit_worm.WormTse(pfad) as tse:
        tse.zeit_setzen()
        tx_nr, t_start = tse.tx_start(client_id, 'Kassenbeleg-V1', '')
    tx_id = str(tx_nr)
    _log_tse(terminal_nr, vorgang_id, 'start', tx_id, 1,
             {'client_id': client_id, 'pfad': pfad}, 0, {'tx_number': tx_nr})
    return {
        'tx_id':           tx_id,
        'revision':        1,
        'zeitpunkt_start': datetime.fromtimestamp(t_start) if t_start else datetime.now(),
    }


def _swissbit_finish(tconf: dict, terminal_nr: int, vorgang_id: int,
                     tx_id: str, positionen: list,
                     zahlarten: list, mwst_saetze: dict) -> dict:
    """Schließt eine Swissbit-Transaktion ab und gibt Signaturdaten zurück."""
    pfad      = _swissbit_pfad(tconf)
    client_id = _swissbit_client_id(terminal_nr)
    tx_number = int(tx_id)

    betraege     = swissbit_worm.betraege_aus_positionen(positionen)
    process_data = swissbit_worm.prozess_daten_kassenbeleg(betraege)

    with swissbit_worm.WormTse(pfad) as tse:
        serial_b64 = tse.serial_b64()
        sig_ctr, t_end, sig_b64 = tse.tx_finish(
            tx_number, client_id, 'Kassenbeleg-V1', process_data
        )

    _log_tse(terminal_nr, vorgang_id, 'finish', tx_id, 2,
             {'process_data': process_data}, 0,
             {'sig_ctr': sig_ctr, 'sig': sig_b64[:20] + '...'})
    return {
        'tx_id':            tx_id,
        'revision':         2,
        'signatur':         sig_b64,
        'signatur_zaehler': sig_ctr,
        'zeitpunkt_start':  None,
        'zeitpunkt_ende':   datetime.fromtimestamp(t_end) if t_end else datetime.now(),
        'tss_serial':       serial_b64,
        'log_time_format':  'unixTime',
        'process_type':     'Kassenbeleg-V1',
        'process_data':     process_data,
    }


def _swissbit_storno(tconf: dict, terminal_nr: int, vorgang_id: int,
                     original_positionen: list, mwst_saetze: dict) -> dict:
    """Erstellt eine Storno-Transaktion auf der Swissbit-TSE."""
    pfad      = _swissbit_pfad(tconf)
    client_id = _swissbit_client_id(terminal_nr)

    # Beträge negieren für Storno
    betraege_pos = swissbit_worm.betraege_aus_positionen(original_positionen)
    betraege_neg = {k: -v for k, v in betraege_pos.items()}
    process_data = swissbit_worm.prozess_daten_storno(betraege_neg)

    with swissbit_worm.WormTse(pfad) as tse:
        tse.zeit_setzen()
        tx_nr, t_start = tse.tx_start(client_id, 'Storno-Beleg', '')
        serial_b64 = tse.serial_b64()
        sig_ctr, t_end, sig_b64 = tse.tx_finish(
            tx_nr, client_id, 'Storno-Beleg', process_data
        )

    tx_id = str(tx_nr)
    _log_tse(terminal_nr, vorgang_id, 'storno_finish', tx_id, 2,
             {'process_data': process_data}, 0,
             {'sig_ctr': sig_ctr})
    return {
        'tx_id':            tx_id,
        'revision':         2,
        'signatur':         sig_b64,
        'signatur_zaehler': sig_ctr,
        'zeitpunkt_start':  datetime.fromtimestamp(t_start) if t_start else None,
        'zeitpunkt_ende':   datetime.fromtimestamp(t_end) if t_end else datetime.now(),
        'tss_serial':       serial_b64,
        'process_type':     'Storno-Beleg',
        'process_data':     process_data,
    }


def _swissbit_cancel(tconf: dict, terminal_nr: int, vorgang_id: int, tx_id: str):
    """Bricht eine offene Swissbit-Transaktion ab."""
    pfad      = _swissbit_pfad(tconf)
    client_id = _swissbit_client_id(terminal_nr)
    try:
        tx_number = int(tx_id)
        with swissbit_worm.WormTse(pfad) as tse:
            tse.tx_cancel(tx_number, client_id)
        _log_tse(terminal_nr, vorgang_id, 'cancel', tx_id, None, None, 0, None)
    except Exception as e:
        log.error("Swissbit TSE Cancel fehlgeschlagen (tx=%s): %s", tx_id, e)


def _swissbit_tagesabschluss(tconf: dict, terminal_nr: int,
                              tagesabschluss_id: int, umsatz_brutto: int) -> dict:
    """Erstellt eine Tagesabschluss-Transaktion auf der Swissbit-TSE."""
    pfad      = _swissbit_pfad(tconf)
    client_id = _swissbit_client_id(terminal_nr)
    process_data = swissbit_worm.prozess_daten_abschluss(umsatz_brutto)

    with swissbit_worm.WormTse(pfad) as tse:
        tse.zeit_setzen()
        tx_nr, t_start = tse.tx_start(client_id, 'Tagesabschluss', '')
        serial_b64 = tse.serial_b64()
        sig_ctr, t_end, sig_b64 = tse.tx_finish(
            tx_nr, client_id, 'Tagesabschluss', process_data
        )

    tx_id = str(tx_nr)
    _log_tse(terminal_nr, tagesabschluss_id, 'zbon_finish', tx_id, 2,
             {'process_data': process_data}, 0, {'sig_ctr': sig_ctr})
    return {
        'tx_id':            tx_id,
        'signatur':         sig_b64,
        'signatur_zaehler': sig_ctr,
        'tss_serial':       serial_b64,
    }


def _base_url(env: str) -> str:
    """Middleware-URL: Transaktionen, TSS-Operationen, Client-Registrierung."""
    return config.FISKALY_BASE_URL


def _mgmt_url(env: str) -> str:
    """Nur für /auth — alle anderen Operationen über _base_url()."""
    return config.FISKALY_MGMT_URL


def _get_token(terminal_nr: int, tconf: dict) -> str:
    """Gibt gültiges JWT zurück (cached, automatisch erneuert)."""
    with _token_lock:
        cached = _token_cache.get(terminal_nr)
        if cached and time.time() < cached['expires_at'] - 30:
            return cached['token']

        env = tconf.get('FISKALY_ENV', 'test')
        url = f"{_mgmt_url(env)}/auth"
        resp = requests.post(url, json={
            'api_key':    tconf['FISKALY_API_KEY'],
            'api_secret': tconf['FISKALY_API_SECRET'],
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        token = data['access_token']
        expires_in = data.get('access_token_expires_in', 600)
        _token_cache[terminal_nr] = {
            'token':      token,
            'expires_at': time.time() + expires_in,
        }
        return token


def _headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _log_tse(terminal_nr: int, vorgang_id, aktion: str, tx_id, revision,
             req_body, resp_code, resp_body, fehler=None):
    import json
    try:
        with get_db() as cur:
            cur.execute(
                """INSERT INTO XT_KASSE_TSE_LOG
                   (TERMINAL_NR, VORGANG_ID, AKTION, TX_ID, TX_REVISION,
                    REQUEST_BODY, RESPONSE_CODE, RESPONSE_BODY, FEHLER)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (terminal_nr, vorgang_id, aktion, tx_id, revision,
                 json.dumps(req_body) if req_body else None,
                 resp_code,
                 json.dumps(resp_body) if resp_body else None,
                 fehler)
            )
    except Exception as e:
        log.error("TSE-Log Fehler: %s", e)


# ── Öffentliche API ───────────────────────────────────────────

def tse_start_transaktion(terminal_nr: int, vorgang_id: int) -> dict:
    """
    Startet eine TSE-Transaktion (state=ACTIVE).
    Gibt zurück: {tx_id, revision, zeitpunkt_start}
    """
    tconf = _terminal_config(terminal_nr)
    if _ist_training(tconf):
        log.info("Terminal %s: Trainings-Modus – tse_start_transaktion übersprungen.", terminal_nr)
        return _dummy_start_result()
    if tconf.get('TSE_TYP') == 'SWISSBIT':
        return _swissbit_start(tconf, terminal_nr, vorgang_id)
    _assert_fiskaly(tconf)

    token = _get_token(terminal_nr, tconf)
    env   = tconf['FISKALY_ENV']
    tss_id    = tconf['FISKALY_TSS_ID']
    client_id = tconf['FISKALY_CLIENT_ID']

    tx_id    = str(uuid.uuid4())
    revision = 1
    body = {
        'state':     'ACTIVE',
        'client_id': client_id,
    }
    url  = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision={revision}"
    resp = requests.put(url, json=body, headers=_headers(token), timeout=15)
    resp_data = resp.json() if resp.content else {}
    _log_tse(terminal_nr, vorgang_id, 'start', tx_id, revision, body, resp.status_code, resp_data)
    resp.raise_for_status()

    return {
        'tx_id':              tx_id,
        'revision':           revision,
        'zeitpunkt_start':    _ts(resp_data.get('time_start')),
    }


def tse_finish_transaktion(terminal_nr: int, vorgang_id: int,
                           tx_id: str, revision: int,
                           positionen: list, zahlarten: list,
                           mwst_saetze: dict) -> dict:
    """
    Schließt eine TSE-Transaktion ab (state=FINISHED) und gibt die
    Signaturdaten zurück, die auf den Kassenbon gedruckt werden müssen.

    positionen: [{'mwst_satz': 19.0, 'gesamtpreis_brutto': 599, ...}, ...]
    zahlarten:  [{'zahlart': 'BAR', 'betrag': 599}, ...]
    mwst_saetze: {1: 19.0, 2: 7.0, 3: 0.0}  (STEUER_CODE → Satz)
    """
    tconf = _terminal_config(terminal_nr)
    if _ist_training(tconf):
        log.info("Terminal %s: Trainings-Modus – tse_finish_transaktion übersprungen.", terminal_nr)
        return _dummy_finish_result(tx_id)
    if tconf.get('TSE_TYP') == 'SWISSBIT':
        return _swissbit_finish(tconf, terminal_nr, vorgang_id, tx_id,
                                positionen, zahlarten, mwst_saetze)
    _assert_fiskaly(tconf)

    token = _get_token(terminal_nr, tconf)
    env   = tconf['FISKALY_ENV']
    tss_id    = tconf['FISKALY_TSS_ID']
    client_id = tconf['FISKALY_CLIENT_ID']

    next_revision = revision + 1

    # Beträge je MwSt-Satz aggregieren
    amounts_per_vat: dict[str, float] = {}
    for pos in positionen:
        if pos.get('STORNIERT'):
            continue
        satz = float(pos['MWST_SATZ'])
        vat_key = _vat_rate_key(satz)
        brutto = pos['GESAMTPREIS_BRUTTO'] / 100.0
        amounts_per_vat[vat_key] = amounts_per_vat.get(vat_key, 0.0) + brutto

    amounts_per_vat_list = [
        {'vat_rate': k, 'amount': f'{v:.2f}'}
        for k, v in amounts_per_vat.items()
    ]

    # Zahlarten
    amounts_per_payment: list[dict] = []
    payment_map = {
        'BAR':          'CASH',
        'EC':           'NON_CASH',
        'KUNDENKONTO':  'NON_CASH',
        'GUTSCHEIN':    'NON_CASH',
        'SONSTIGE':     'NON_CASH',
    }
    payment_totals: dict[str, float] = {}
    for z in zahlarten:
        key = payment_map.get(z['zahlart'], 'NON_CASH')
        payment_totals[key] = payment_totals.get(key, 0.0) + z['betrag'] / 100.0
    amounts_per_payment = [
        {'payment_type': k, 'amount': f'{v:.2f}'}
        for k, v in payment_totals.items()
    ]

    body = {
        'state':     'FINISHED',
        'client_id': client_id,
        'schema': {
            'standard_v1': {
                'receipt': {
                    'receipt_type':            'RECEIPT',
                    'amounts_per_vat_rate':    amounts_per_vat_list,
                    'amounts_per_payment_type': amounts_per_payment,
                }
            }
        }
    }
    url  = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision={next_revision}"
    resp = requests.put(url, json=body, headers=_headers(token), timeout=15)
    resp_data = resp.json() if resp.content else {}
    _log_tse(terminal_nr, vorgang_id, 'finish', tx_id, next_revision, body, resp.status_code, resp_data)
    resp.raise_for_status()

    sig = resp_data.get('signature', {})
    return {
        'tx_id':                tx_id,
        'revision':             next_revision,
        'signatur':             sig.get('value', ''),
        'signatur_zaehler':     sig.get('counter'),
        'zeitpunkt_start':      _ts(resp_data.get('time_start')),
        'zeitpunkt_ende':       _ts(resp_data.get('time_end')),
        # Fiskaly liefert tss_serial_number direkt im Response (nicht unter 'tss')
        'tss_serial':           resp_data.get('tss_serial_number', ''),
        'log_time_format':      resp_data.get('log', {}).get('time_format', ''),
        'process_type':         resp_data.get('process_type', ''),
        'process_data':         resp_data.get('process_data', ''),
    }


def tse_storno_transaktion(terminal_nr: int, vorgang_id: int,
                           original_positionen: list, mwst_saetze: dict) -> dict:
    """
    Erstellt eine neue TSE-Transaktion für einen Storno-Beleg
    (negative Beträge = RECEIPT mit negativen amounts).
    """
    tconf = _terminal_config(terminal_nr)
    if _ist_training(tconf):
        log.info("Terminal %s: Trainings-Modus – tse_storno_transaktion übersprungen.", terminal_nr)
        tx_id = _dummy_tx_id()
        return _dummy_finish_result(tx_id)
    if tconf.get('TSE_TYP') == 'SWISSBIT':
        return _swissbit_storno(tconf, terminal_nr, vorgang_id,
                                original_positionen, mwst_saetze)
    _assert_fiskaly(tconf)

    token = _get_token(terminal_nr, tconf)
    env   = tconf['FISKALY_ENV']
    tss_id    = tconf['FISKALY_TSS_ID']
    client_id = tconf['FISKALY_CLIENT_ID']

    tx_id = str(uuid.uuid4())

    # Start
    body_start = {'state': 'ACTIVE', 'client_id': client_id}
    url = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision=1"
    resp = requests.put(url, json=body_start, headers=_headers(token), timeout=15)
    resp.raise_for_status()
    _log_tse(terminal_nr, vorgang_id, 'storno_start', tx_id, 1, body_start, resp.status_code, resp.json())

    # Finish mit negativen Beträgen
    amounts_per_vat: dict[str, float] = {}
    for pos in original_positionen:
        satz = float(pos['mwst_satz'])
        vat_key = _vat_rate_key(satz)
        brutto = -(pos['gesamtpreis_brutto'] / 100.0)
        amounts_per_vat[vat_key] = amounts_per_vat.get(vat_key, 0.0) + brutto

    body_finish = {
        'state':     'FINISHED',
        'client_id': client_id,
        'schema': {
            'standard_v1': {
                'receipt': {
                    'receipt_type':         'CANCELLATION',
                    'amounts_per_vat_rate': [
                        {'vat_rate': k, 'amount': f'{v:.2f}'}
                        for k, v in amounts_per_vat.items()
                    ],
                    'amounts_per_payment_type': [
                        {'payment_type': 'CASH', 'amount': f'{sum(v for v in amounts_per_vat.values()):.2f}'}
                    ],
                }
            }
        }
    }
    url2 = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision=2"
    resp2 = requests.put(url2, json=body_finish, headers=_headers(token), timeout=15)
    resp2_data = resp2.json() if resp2.content else {}
    _log_tse(terminal_nr, vorgang_id, 'storno_finish', tx_id, 2, body_finish, resp2.status_code, resp2_data)
    resp2.raise_for_status()

    sig = resp2_data.get('signature', {})
    return {
        'tx_id':              tx_id,
        'revision':           2,
        'signatur':           sig.get('value', ''),
        'signatur_zaehler':   sig.get('counter'),
        'zeitpunkt_start':    _ts(resp2_data.get('time_start')),
        'zeitpunkt_ende':     _ts(resp2_data.get('time_end')),
        'tss_serial':         resp2_data.get('tss_serial_number', ''),
        'process_type':       resp2_data.get('process_type', ''),
        'process_data':       resp2_data.get('process_data', ''),
    }


def tse_cancel_transaktion(terminal_nr: int, vorgang_id: int,
                           tx_id: str, revision: int):
    """Bricht eine offene Transaktion ab (z.B. Abbruch des Vorgangs)."""
    try:
        tconf = _terminal_config(terminal_nr)
        if _ist_training(tconf):
            log.info("Terminal %s: Trainings-Modus – tse_cancel_transaktion übersprungen.", terminal_nr)
            return
        if tconf.get('TSE_TYP') == 'SWISSBIT':
            _swissbit_cancel(tconf, terminal_nr, vorgang_id, tx_id)
            return
        _assert_fiskaly(tconf)
        token = _get_token(terminal_nr, tconf)
        env   = tconf['FISKALY_ENV']
        tss_id    = tconf['FISKALY_TSS_ID']
        client_id = tconf['FISKALY_CLIENT_ID']

        next_rev = revision + 1
        body = {'state': 'CANCELLED', 'client_id': client_id}
        url  = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision={next_rev}"
        resp = requests.put(url, json=body, headers=_headers(token), timeout=10)
        _log_tse(terminal_nr, vorgang_id, 'cancel', tx_id, next_rev, body,
                 resp.status_code, resp.json() if resp.content else {})
    except Exception as e:
        log.error("TSE Cancel fehlgeschlagen: %s", e)


def tse_tagesabschluss(terminal_nr: int,
                       tagesabschluss_id: int,
                       umsatz_brutto: int) -> dict:
    """
    Erstellt eine TSE-Transaktion für den Tagesabschluss (Z-Bon).
    Gibt Signaturdaten zurück.
    """
    tconf = _terminal_config(terminal_nr)
    if _ist_training(tconf):
        log.info("Terminal %s: Trainings-Modus – tse_tagesabschluss übersprungen.", terminal_nr)
        return {
            'tx_id':            _dummy_tx_id(),
            'signatur':         'TRAININGSMODUS-KEINE-ECHTE-SIGNATUR',
            'signatur_zaehler': 0,
            'tss_serial':       'TRAININGSMODUS',
        }
    if tconf.get('TSE_TYP') == 'SWISSBIT':
        return _swissbit_tagesabschluss(tconf, terminal_nr, tagesabschluss_id, umsatz_brutto)
    _assert_fiskaly(tconf)
    token = _get_token(terminal_nr, tconf)
    env   = tconf['FISKALY_ENV']
    tss_id    = tconf['FISKALY_TSS_ID']
    client_id = tconf['FISKALY_CLIENT_ID']

    tx_id = str(uuid.uuid4())

    body_start = {'state': 'ACTIVE', 'client_id': client_id}
    url = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision=1"
    resp = requests.put(url, json=body_start, headers=_headers(token), timeout=15)
    resp.raise_for_status()
    _log_tse(terminal_nr, tagesabschluss_id, 'zbон_start', tx_id, 1, body_start,
             resp.status_code, resp.json())

    betrag_str = f'{umsatz_brutto / 100.0:.2f}'
    body_finish = {
        'state':     'FINISHED',
        'client_id': client_id,
        'schema': {
            'standard_v1': {
                'receipt': {
                    'receipt_type': 'DAILY_CLOSING',
                    'amounts_per_vat_rate':     [{'vat_rate': 'NULL', 'amount': betrag_str}],
                    'amounts_per_payment_type': [{'payment_type': 'CASH', 'amount': betrag_str}],
                }
            }
        }
    }
    url2 = f"{_base_url(env)}/tss/{tss_id}/tx/{tx_id}?tx_revision=2"
    resp2 = requests.put(url2, json=body_finish, headers=_headers(token), timeout=15)
    resp2_data = resp2.json() if resp2.content else {}
    _log_tse(terminal_nr, tagesabschluss_id, 'zbon_finish', tx_id, 2, body_finish,
             resp2.status_code, resp2_data)
    resp2.raise_for_status()

    sig = resp2_data.get('signature', {})
    return {
        'tx_id':            tx_id,
        'signatur':         sig.get('value', ''),
        'signatur_zaehler': sig.get('counter'),
        'tss_serial':       resp2_data.get('tss_serial_number', ''),
    }


def tse_verfuegbar(terminal_nr: int) -> bool:
    """Gibt True zurück wenn TSE erreichbar und konfiguriert (oder Trainings-Modus aktiv)."""
    try:
        tconf = _terminal_config(terminal_nr)
        if _ist_training(tconf):
            return True   # Demo/Trainings-Modus ist immer "verfügbar"
        if tconf.get('TSE_TYP') == 'SWISSBIT':
            return bool(tconf.get('SWISSBIT_PFAD')) and swissbit_worm.verfuegbar()
        # FISKALY
        if not tconf.get('FISKALY_API_KEY'):
            log.warning("TSE terminal %s: FISKALY_API_KEY nicht konfiguriert.", terminal_nr)
            return False
        if not tconf.get('FISKALY_TSS_ID'):
            log.warning("TSE terminal %s: FISKALY_TSS_ID nicht konfiguriert.", terminal_nr)
            return False
        _get_token(terminal_nr, tconf)
        return True
    except Exception as e:
        log.warning("TSE terminal %s nicht verfügbar: %s", terminal_nr, e)
        return False


def tse_tss_status(terminal_nr: int) -> dict:
    """
    Fragt den aktuellen Status der TSS ab.
    Im Trainings-Modus: gibt Demo-Status zurück.
    """
    tconf = _terminal_config(terminal_nr)
    if _ist_training(tconf):
        tse_bez = tconf.get('TSE_BEZEICHNUNG') or 'Trainings-/Demo-Modus'
        return {
            'state':                        'INITIALIZED',
            'bsi_certification_id':         'TRAININGSMODUS',
            '_id':                          'DEMO',
            'serial_number':                'TRAININGSMODUS',
            'signature_algorithm':          'N/A',
            'signature_timestamp_format':   'N/A',
            'signature_counter':            0,
            'transaction_counter':          0,
            'number_registered_clients':    1,
            'max_number_registered_clients': 9,
            'public_key':                   '',
            '_version':                     'demo',
            '_hinweis':                     f'{tse_bez} aktiv – keine echte TSE-Signierung',
        }
    if tconf.get('TSE_TYP') == 'SWISSBIT':
        pfad = _swissbit_pfad(tconf)
        return swissbit_worm.tse_status_lesen(pfad)
    token  = _get_token(terminal_nr, tconf)
    env    = tconf['FISKALY_ENV']
    tss_id = tconf['FISKALY_TSS_ID']
    url = f"{_base_url(env)}/tss/{tss_id}"
    resp = requests.get(url, headers=_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _tss_put(url: str, body: dict, token: str,
             terminal_nr: int, aktion: str) -> dict:
    """Führt einen TSS-PUT aus und wirft bei Fehler eine RuntimeError."""
    resp = requests.put(url, json=body, headers=_headers(token), timeout=15)
    resp_data = resp.json() if resp.content else {}
    _log_tse(terminal_nr, None, aktion, None, None,
             body, resp.status_code, resp_data)
    if not resp.ok:
        detail = resp_data.get('message') or resp_data.get('error') or str(resp_data)
        raise RuntimeError(
            f"TSS-PUT '{aktion}' fehlgeschlagen "
            f"({resp.status_code}): {detail}"
        )
    return resp_data


def _tss_patch(url: str, body: dict, token: str,
               terminal_nr: int, aktion: str) -> dict:
    """Führt einen TSS-PATCH aus und wirft bei Fehler eine RuntimeError."""
    resp = requests.patch(url, json=body, headers=_headers(token), timeout=15)
    resp_data = resp.json() if resp.content else {}
    _log_tse(terminal_nr, None, aktion, None, None,
             body, resp.status_code, resp_data)
    if not resp.ok:
        detail = resp_data.get('message') or resp_data.get('error') or str(resp_data)
        raise RuntimeError(
            f"TSS-PATCH '{aktion}' fehlgeschlagen "
            f"({resp.status_code}): {detail}"
        )
    return resp_data


def tse_tss_initialisieren(terminal_nr: int) -> None:
    """
    Bringt die TSS vollständig in den Zustand INITIALIZED.

    Vollständiger Fiskaly-Ablauf laut OpenAPI-Spec:
        1. PUT  /tss/{id}             {"state": "UNINITIALIZED"}   (CREATED → UNINITIALIZED)
        2. POST /tss/{id}/admin/pin   {"admin_puk": "...", "new_admin_pin": "..."}
        3. POST /tss/{id}/admin/auth  {"admin_pin": "..."}
        4. PUT  /tss/{id}             {"state": "INITIALIZED"}
        5. POST /tss/{id}/admin/logout {}

    Benötigt admin_puk (aus Fiskaly-Dashboard) und admin_pin (frei wählbar ≥6 Zeichen).
    """
    tconf     = _terminal_config(terminal_nr)
    admin_pin = (tconf.get('FISKALY_ADMIN_PIN') or '').strip()
    admin_puk = (tconf.get('FISKALY_ADMIN_PUK') or '').strip()

    if not admin_pin:
        raise RuntimeError(
            "TSE Admin-PIN nicht konfiguriert. "
            "Bitte in Admin → Terminal einen PIN eintragen (mind. 6 Zeichen)."
        )
    if not admin_puk:
        raise RuntimeError(
            "TSE Admin-PUK nicht konfiguriert. "
            "Den PUK findest du im Fiskaly-Dashboard unter TSS → Details."
        )

    token  = _get_token(terminal_nr, tconf)
    env    = tconf['FISKALY_ENV']
    tss_id = tconf['FISKALY_TSS_ID']
    base   = f"{_base_url(env)}/tss/{tss_id}"

    # ── Aktuellen Zustand ermitteln ───────────────────────────
    status_resp = requests.get(base, headers=_headers(token), timeout=15)
    status_resp.raise_for_status()
    current_state = status_resp.json().get('state', '')
    log.info("TSS %s aktueller Zustand: %s", tss_id, current_state)

    if current_state == 'INITIALIZED':
        log.info("TSS %s bereits INITIALIZED.", tss_id)
        return

    # ── Schritt 1: CREATED → UNINITIALIZED ───────────────────
    # PATCH für State-Wechsel, PUT würde eine neue TSS anlegen (→ 409)
    if current_state == 'CREATED':
        _tss_patch(base, {'state': 'UNINITIALIZED'}, token,
                   terminal_nr, 'tss_created_to_uninitialized')
        log.info("TSS %s: CREATED → UNINITIALIZED.", tss_id)

    # ── Schritt 2: Admin-PIN mit PUK setzen ──────────────────
    # Endpunkt laut Live-Sonde: PATCH /tss/{id}/admin  (nicht /admin/pin)
    pin_resp = requests.patch(
        f"{base}/admin",
        json={'admin_puk': admin_puk, 'new_admin_pin': admin_pin},
        headers=_headers(token), timeout=15
    )
    pin_data = pin_resp.json() if pin_resp.content else {}
    _log_tse(terminal_nr, None, 'tss_admin_pin_setzen', None, None,
             {'admin_puk': '***', 'new_admin_pin': '***'},
             pin_resp.status_code, pin_data)
    if not pin_resp.ok:
        detail = pin_data.get('message') or pin_data.get('error') or str(pin_data)
        raise RuntimeError(f"Admin-PIN setzen fehlgeschlagen ({pin_resp.status_code}): {detail}")
    log.info("TSS %s: Admin-PIN gesetzt.", tss_id)

    # ── Schritt 3: Als Admin einloggen ────────────────────────
    auth_resp = requests.post(
        f"{base}/admin/auth",
        json={'admin_pin': admin_pin},
        headers=_headers(token), timeout=15
    )
    auth_data = auth_resp.json() if auth_resp.content else {}
    _log_tse(terminal_nr, None, 'tss_admin_auth', None, None,
             {'admin_pin': '***'}, auth_resp.status_code, auth_data)
    if not auth_resp.ok:
        detail = auth_data.get('message') or auth_data.get('error') or str(auth_data)
        raise RuntimeError(f"Admin-Auth fehlgeschlagen ({auth_resp.status_code}): {detail}")
    # Falls die API einen neuen Token zurückgibt, diesen verwenden
    admin_token = auth_data.get('access_token') or token
    log.info("TSS %s: Admin authentifiziert.", tss_id)

    # ── Schritt 4: UNINITIALIZED → INITIALIZED ───────────────
    _tss_patch(base, {'state': 'INITIALIZED'}, admin_token,
               terminal_nr, 'tss_uninitialized_to_initialized')
    log.info("TSS %s: INITIALIZED.", tss_id)

    # ── Schritt 5: Admin-Logout ───────────────────────────────
    requests.post(f"{base}/admin/logout", json={},
                  headers=_headers(admin_token), timeout=15)
    log.info("TSS %s erfolgreich initialisiert (Terminal %s).", tss_id, terminal_nr)


def tse_client_registrieren(terminal_nr: int) -> str:
    """
    Legt einen neuen Fiskaly-Client für dieses Terminal an und speichert
    die generierte Client-ID in XT_KASSE_TERMINALS.

    Prüft vorher den TSS-Status — ist die TSS noch UNINITIALIZED, wird sie
    automatisch initialisiert (sofern ein Admin-PIN konfiguriert ist).

    Wird automatisch beim ersten Speichern der Konfiguration aufgerufen,
    wenn keine Client-ID hinterlegt ist.

    Gibt die neue Client-ID (UUID) zurück.
    """
    from db import get_db
    tconf = _terminal_config(terminal_nr)
    token = _get_token(terminal_nr, tconf)
    env   = tconf['FISKALY_ENV']
    tss_id = tconf['FISKALY_TSS_ID']

    # TSS-Status prüfen und ggf. initialisieren
    try:
        status = tse_tss_status(terminal_nr)
        tss_state = status.get('state', '')
        if tss_state not in ('INITIALIZED',):
            log.info("TSS-Status ist '%s' – versuche Initialisierung …", tss_state)
            tse_tss_initialisieren(terminal_nr)
            # Token nach Zustandsänderung neu holen
            _token_cache.pop(terminal_nr, None)
            tconf = _terminal_config(terminal_nr)
            token = _get_token(terminal_nr, tconf)
    except RuntimeError:
        raise
    except Exception as e:
        log.warning("TSS-Status-Abfrage fehlgeschlagen, fahre trotzdem fort: %s", e)

    client_id     = str(uuid.uuid4())
    serial_number = f"kasse-terminal-{terminal_nr}"

    body = {'serial_number': serial_number}
    url  = f"{_base_url(env)}/tss/{tss_id}/client/{client_id}"
    resp = requests.put(url, json=body, headers=_headers(token), timeout=15)
    resp_data = resp.json() if resp.content else {}

    _log_tse(terminal_nr, None, 'client_registrieren', None, None,
             body, resp.status_code, resp_data)

    resp.raise_for_status()

    # Client-ID dauerhaft in der DB speichern
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_TERMINALS SET FISKALY_CLIENT_ID = %s WHERE TERMINAL_NR = %s",
            (client_id, terminal_nr)
        )

    log.info("Fiskaly-Client %s für Terminal %s angelegt.", client_id, terminal_nr)
    return client_id


# ── Interne Hilfsfunktionen ───────────────────────────────────

def _ts(unix_ts) -> datetime | None:
    """Konvertiert Fiskaly Unix-Timestamp (int) in Python datetime für MySQL."""
    if unix_ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(unix_ts))
    except Exception:
        return None


def _vat_rate_key(satz: float) -> str:
    """Wandelt einen MwSt-Satz in den Fiskaly-Enum-Wert um."""
    if abs(satz - 19.0) < 0.1:
        return 'NORMAL'
    if abs(satz - 7.0) < 0.1:
        return 'REDUCED_1'
    if abs(satz) < 0.1:
        return 'NULL'
    # unbekannter Satz → Fiskaly erlaubt numerische Angabe
    return f'{satz:.1f}'


# ── TSE-Verwaltungsfunktionen ─────────────────────────────────

def tse_geraete_liste() -> list:
    """
    Gibt alle TSE-Geräte aus XT_KASSE_TSE_GERAETE zurück
    (neueste zuerst, mit Info welche Terminals sie nutzen).
    """
    with get_db() as cur:
        cur.execute(
            """SELECT g.*,
                      GROUP_CONCAT(t.TERMINAL_NR ORDER BY t.TERMINAL_NR) AS TERMINAL_NRS
                 FROM XT_KASSE_TSE_GERAETE g
                 LEFT JOIN XT_KASSE_TERMINALS t ON t.TSE_ID = g.REC_ID
                GROUP BY g.REC_ID
                ORDER BY g.REC_ID DESC"""
        )
        return cur.fetchall()


def tse_geraet_laden(tse_id: int) -> dict | None:
    """Lädt ein einzelnes TSE-Gerät."""
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KASSE_TSE_GERAETE WHERE REC_ID = %s", (tse_id,))
        return cur.fetchone()


def tse_geraet_speichern(data: dict) -> int:
    """
    Legt ein neues TSE-Gerät an oder aktualisiert ein vorhandenes.
    data: dict mit Feldern passend zu XT_KASSE_TSE_GERAETE.
    Gibt REC_ID zurück.
    """
    rec_id = data.get('rec_id') or data.get('REC_ID')
    with get_db() as cur:
        if rec_id:
            cur.execute(
                """UPDATE XT_KASSE_TSE_GERAETE
                      SET TYP=%s, BEZEICHNUNG=%s, BSI_ZERTIFIZIERUNG=%s,
                          ZERTIFIKAT_GUELTIG_BIS=%s,
                          FISKALY_ENV=%s, FISKALY_API_KEY=%s, FISKALY_API_SECRET=%s,
                          FISKALY_TSS_ID=%s, FISKALY_ADMIN_PIN=%s, FISKALY_ADMIN_PUK=%s,
                          SWISSBIT_PFAD=%s, SWISSBIT_ADMIN_PIN=%s, SWISSBIT_ADMIN_PUK=%s,
                          IN_BETRIEB_SEIT=%s, AUSSER_BETRIEB=%s, BEMERKUNG=%s
                    WHERE REC_ID=%s""",
                (_f(data, 'TYP', 'FISKALY'), _f(data, 'BEZEICHNUNG'),
                 _f(data, 'BSI_ZERTIFIZIERUNG'),
                 _f(data, 'ZERTIFIKAT_GUELTIG_BIS') or None,
                 _f(data, 'FISKALY_ENV', 'test'), _f(data, 'FISKALY_API_KEY'),
                 _f(data, 'FISKALY_API_SECRET'), _f(data, 'FISKALY_TSS_ID'),
                 _f(data, 'FISKALY_ADMIN_PIN'), _f(data, 'FISKALY_ADMIN_PUK'),
                 _f(data, 'SWISSBIT_PFAD'), _f(data, 'SWISSBIT_ADMIN_PIN'),
                 _f(data, 'SWISSBIT_ADMIN_PUK'),
                 _f(data, 'IN_BETRIEB_SEIT') or None,
                 _f(data, 'AUSSER_BETRIEB') or None, _f(data, 'BEMERKUNG'),
                 rec_id)
            )
            return rec_id
        else:
            cur.execute(
                """INSERT INTO XT_KASSE_TSE_GERAETE
                   (TYP, BEZEICHNUNG, BSI_ZERTIFIZIERUNG, ZERTIFIKAT_GUELTIG_BIS,
                    FISKALY_ENV, FISKALY_API_KEY, FISKALY_API_SECRET, FISKALY_TSS_ID,
                    FISKALY_ADMIN_PIN, FISKALY_ADMIN_PUK,
                    SWISSBIT_PFAD, SWISSBIT_ADMIN_PIN, SWISSBIT_ADMIN_PUK,
                    IN_BETRIEB_SEIT, BEMERKUNG)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (_f(data, 'TYP', 'FISKALY'), _f(data, 'BEZEICHNUNG'),
                 _f(data, 'BSI_ZERTIFIZIERUNG'),
                 _f(data, 'ZERTIFIKAT_GUELTIG_BIS') or None,
                 _f(data, 'FISKALY_ENV', 'test'), _f(data, 'FISKALY_API_KEY'),
                 _f(data, 'FISKALY_API_SECRET'), _f(data, 'FISKALY_TSS_ID'),
                 _f(data, 'FISKALY_ADMIN_PIN'), _f(data, 'FISKALY_ADMIN_PUK'),
                 _f(data, 'SWISSBIT_PFAD'), _f(data, 'SWISSBIT_ADMIN_PIN'),
                 _f(data, 'SWISSBIT_ADMIN_PUK'),
                 _f(data, 'IN_BETRIEB_SEIT') or None, _f(data, 'BEMERKUNG'))
            )
            cur.execute("SELECT LAST_INSERT_ID() AS id")
            return cur.fetchone()['id']


def tse_geraet_aktivieren(terminal_nr: int, tse_id: int | None) -> None:
    """
    Setzt die aktive TSE für ein Terminal.
    tse_id=None → TSE-Zuweisung entfernen (nur Legacy-Spalten).
    Invalidiert den Token-Cache.
    """
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_TERMINALS SET TSE_ID=%s WHERE TERMINAL_NR=%s",
            (tse_id, terminal_nr)
        )
    _token_cache.pop(terminal_nr, None)
    log.info("Terminal %s: aktive TSE geändert → TSE_ID=%s", terminal_nr, tse_id)


def tse_trainings_modus_setzen(terminal_nr: int, aktiv: bool) -> None:
    """Schaltet den Trainings-Modus für ein Terminal ein oder aus."""
    with get_db() as cur:
        cur.execute(
            "UPDATE XT_KASSE_TERMINALS SET TRAININGS_MODUS=%s WHERE TERMINAL_NR=%s",
            (1 if aktiv else 0, terminal_nr)
        )
    _token_cache.pop(terminal_nr, None)
    log.info("Terminal %s: Trainings-Modus → %s", terminal_nr, 'EIN' if aktiv else 'AUS')


def _f(data: dict, key: str, default: str = '') -> str:
    """Hilfsfunktion: Wert aus dict, als String leer-bereinigt."""
    val = data.get(key) or data.get(key.lower()) or default or ''
    return str(val).strip() if val is not None else default
