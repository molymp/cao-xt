"""
CAO-XT – Einkauf: Lieferanten-Registry + IMAP-Zugang

Phase 1 des Einkaufsprozesses (siehe DECISIONS / Auto-Memory):
  * Lieferanten-Stammdaten in ``XT_EINKAUF_LIEFERANT``
    (Erkennungsmuster fuer eingehende Bestellbestaetigungs-Mails,
    optionale Web-Login-Daten fuer Stammdaten-Anreicherung)
  * IMAP-Konfiguration zentral in ``DORFKERN_KONFIG`` (Kategorie EINKAUF)
  * Verbindungstest fuer IMAP (Login, INBOX zaehlen)

Spaetere Phasen (Email-Polling, CAO-Sync, Bestell-Erstellung) bauen auf
diesem Modul auf. Web-Passwort und IMAP-Passwort werden als
``TYP='SECRET'`` in ``DORFKERN_KONFIG`` bzw. einem separaten
Schluessel pro Lieferant abgelegt – Klartext bis Verschluesselungs-Roll-out
(siehe konfig.py-Hinweis).

CAO-Tabellen werden hier NICHT angefasst – die Einbindung des Lieferanten
in ``ADRESSEN`` erfolgt erst, wenn der Anwender im Admin-UI explizit
einen Adressdatensatz zuordnet (Feld ``CAO_LIEF_ID``).
"""
from __future__ import annotations

import imaplib
import logging
import socket
from typing import Any, Optional

from common.db import get_db, get_db_transaction
from common import konfig as _konfig

log = logging.getLogger(__name__)


# ── Konfig-Schluessel (DORFKERN_KONFIG, Kategorie EINKAUF) ───────────────────

KEY_IMAP_HOST       = 'einkauf.imap.host'
KEY_IMAP_PORT       = 'einkauf.imap.port'
KEY_IMAP_USER       = 'einkauf.imap.user'
KEY_IMAP_PASSWORD   = 'einkauf.imap.password'   # SECRET
KEY_IMAP_USE_SSL    = 'einkauf.imap.use_ssl'
KEY_IMAP_FOLDER     = 'einkauf.imap.folder'
KEY_IMAP_POLL_MIN   = 'einkauf.imap.poll_min'

DEFAULT_IMAP_PORT     = 993
DEFAULT_IMAP_USE_SSL  = True
DEFAULT_IMAP_FOLDER   = 'INBOX'
DEFAULT_IMAP_POLL_MIN = 5

# Schluessel-Schema fuer Web-Passwort pro Lieferant:
#   einkauf.lieferant.<KUERZEL>.web_password
def web_password_key(kuerzel: str) -> str:
    return f'einkauf.lieferant.{kuerzel.lower()}.web_password'


# ── Schema ───────────────────────────────────────────────────────────────────

def run_migration() -> None:
    """Legt die Lieferanten-Tabelle an. Idempotent.

    Phase-1-Felder. Email-Erkennungs-Patterns werden bei Bedarf
    spaeter (Phase 3) um regex/glob/Substring-Tags erweitert; aktuell
    interpretieren wir sie als Substring-Match (case-insensitive).
    """
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINKAUF_LIEFERANT (
                  REC_ID                 INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  KUERZEL                VARCHAR(20)  NOT NULL,
                  BEZEICHNUNG            VARCHAR(120) NOT NULL,
                  CAO_LIEF_ID            INT          NULL,
                  EMAIL_VON_PATTERN      VARCHAR(255) NULL,
                  EMAIL_SUBJECT_PATTERN  VARCHAR(255) NULL,
                  WEB_LOGIN_URL          VARCHAR(255) NULL,
                  WEB_USERNAME           VARCHAR(120) NULL,
                  PARSER_KEY             VARCHAR(40)  NULL,
                  AKTIV                  TINYINT(1)   NOT NULL DEFAULT 1,
                  ERSTELLT_AM            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  GEAENDERT_AM           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
                  GEAENDERT_VON          INT          NULL,
                  UNIQUE KEY uq_kuerzel (KUERZEL)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Einkauf: Lieferanten-Registry (Phase 1)'
            """)
        log.info("Migration: XT_EINKAUF_LIEFERANT geprueft/erstellt.")
    except Exception as exc:
        log.warning("XT_EINKAUF_LIEFERANT-Migration fehlgeschlagen: %s", exc)


def seed_defaults() -> int:
    """Legt einen UTZ-Default-Lieferanten an, falls keiner existiert.

    Werte stammen aus der Beispiel-Bestellbestaetigung
    (siehe Auto-Memory-Notiz Einkaufsprozess). ``INSERT IGNORE``
    (UNIQUE auf KUERZEL) – nachtraegliche Aenderungen im Admin-UI
    bleiben erhalten.
    """
    anzahl = 0
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                INSERT IGNORE INTO XT_EINKAUF_LIEFERANT
                  (KUERZEL, BEZEICHNUNG, EMAIL_VON_PATTERN,
                   EMAIL_SUBJECT_PATTERN, WEB_LOGIN_URL, PARSER_KEY, AKTIV)
                VALUES
                  ('UTZ', 'UTZ Lebensmittel', 'webportal@utz24.online',
                   'Ihre Bestellung (UTZ Lebensmittel)',
                   'https://utz24.online/', 'utz_v1', 1)
            """)
            anzahl = cur.rowcount
    except Exception as exc:
        log.warning("seed_defaults Einkauf: %s", exc)
    if anzahl:
        log.info("XT_EINKAUF_LIEFERANT: %d Default-Eintraege angelegt.", anzahl)
    return anzahl


# ── Lieferanten-CRUD ─────────────────────────────────────────────────────────

def _zeile_zu_dict(row: dict) -> dict:
    """Reicht die DB-Zeile durch – ohne Web-Passwort (das liegt in
    DORFKERN_KONFIG und wird nur ueber dedizierte API geholt/gesetzt)."""
    if not row:
        return {}
    out = dict(row)
    # Bool-Cast fuer AKTIV
    out['AKTIV'] = bool(int(out.get('AKTIV') or 0))
    return out


def liste(nur_aktive: bool = False) -> list[dict]:
    """Liefert alle Lieferanten (sortiert nach KUERZEL)."""
    sql = ("SELECT REC_ID, KUERZEL, BEZEICHNUNG, CAO_LIEF_ID, "
           "EMAIL_VON_PATTERN, EMAIL_SUBJECT_PATTERN, WEB_LOGIN_URL, "
           "WEB_USERNAME, PARSER_KEY, AKTIV, ERSTELLT_AM, GEAENDERT_AM "
           "FROM XT_EINKAUF_LIEFERANT")
    params: tuple = ()
    if nur_aktive:
        sql += " WHERE AKTIV = 1"
    sql += " ORDER BY KUERZEL"
    try:
        with get_db() as cur:
            cur.execute(sql, params)
            return [_zeile_zu_dict(r) for r in (cur.fetchall() or [])]
    except Exception as exc:
        log.warning("einkauf.liste(): DB-Fehler: %s", exc)
        return []


def holen(rec_id: int) -> Optional[dict]:
    """Liefert einen Lieferanten oder None."""
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT REC_ID, KUERZEL, BEZEICHNUNG, CAO_LIEF_ID, "
                "EMAIL_VON_PATTERN, EMAIL_SUBJECT_PATTERN, WEB_LOGIN_URL, "
                "WEB_USERNAME, PARSER_KEY, AKTIV, ERSTELLT_AM, GEAENDERT_AM "
                "FROM XT_EINKAUF_LIEFERANT WHERE REC_ID = %s",
                (rec_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning("einkauf.holen(%s): %s", rec_id, exc)
        return None
    return _zeile_zu_dict(row) if row else None


def anlegen(daten: dict, ma_id: Optional[int] = None) -> int:
    """Legt einen neuen Lieferanten an. Liefert die neue REC_ID.

    Pflichtfelder: ``KUERZEL`` (max 20), ``BEZEICHNUNG``.
    """
    kuerzel = (daten.get('KUERZEL') or '').strip().upper()
    bez     = (daten.get('BEZEICHNUNG') or '').strip()
    if not kuerzel or not bez:
        raise ValueError('KUERZEL und BEZEICHNUNG sind Pflicht.')
    if len(kuerzel) > 20:
        raise ValueError('KUERZEL maximal 20 Zeichen.')

    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO XT_EINKAUF_LIEFERANT
              (KUERZEL, BEZEICHNUNG, CAO_LIEF_ID, EMAIL_VON_PATTERN,
               EMAIL_SUBJECT_PATTERN, WEB_LOGIN_URL, WEB_USERNAME,
               PARSER_KEY, AKTIV, GEAENDERT_VON)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            kuerzel, bez,
            daten.get('CAO_LIEF_ID') or None,
            (daten.get('EMAIL_VON_PATTERN') or '').strip() or None,
            (daten.get('EMAIL_SUBJECT_PATTERN') or '').strip() or None,
            (daten.get('WEB_LOGIN_URL') or '').strip() or None,
            (daten.get('WEB_USERNAME') or '').strip() or None,
            (daten.get('PARSER_KEY') or '').strip() or None,
            1 if daten.get('AKTIV', True) else 0,
            ma_id,
        ))
        return int(cur.lastrowid)


def aktualisieren(rec_id: int, daten: dict,
                  ma_id: Optional[int] = None) -> bool:
    """UPDATE auf der Zeile. Web-Passwort wird hier NICHT angefasst –
    dafuer separater Endpoint."""
    felder: list[str] = []
    werte: list[Any] = []
    erlaubt = {
        'BEZEICHNUNG', 'CAO_LIEF_ID', 'EMAIL_VON_PATTERN',
        'EMAIL_SUBJECT_PATTERN', 'WEB_LOGIN_URL', 'WEB_USERNAME',
        'PARSER_KEY', 'AKTIV',
    }
    for k, v in daten.items():
        if k not in erlaubt:
            continue
        if k == 'AKTIV':
            felder.append('AKTIV = %s')
            werte.append(1 if v else 0)
        elif k == 'CAO_LIEF_ID':
            felder.append('CAO_LIEF_ID = %s')
            werte.append(int(v) if v not in (None, '', 0) else None)
        else:
            felder.append(f'{k} = %s')
            werte.append((str(v).strip() if v is not None else '') or None)
    if not felder:
        return False
    felder.append('GEAENDERT_VON = %s')
    werte.append(ma_id)
    werte.append(rec_id)
    sql = ("UPDATE XT_EINKAUF_LIEFERANT SET " + ', '.join(felder)
           + " WHERE REC_ID = %s")
    with get_db_transaction() as cur:
        cur.execute(sql, tuple(werte))
        return cur.rowcount > 0


def loeschen(rec_id: int) -> bool:
    """Hard-Delete. Lieferanten OHNE eingegangene Bestellungen sollten
    sich entfernen lassen; ist eine ``XT_EINKAUF_BESTELLUNG`` mit
    ``LIEF_REC_ID = rec_id`` vorhanden, FK schlaegt zu (Phase 2 fuegt
    den FK ein).
    """
    with get_db_transaction() as cur:
        cur.execute("DELETE FROM XT_EINKAUF_LIEFERANT WHERE REC_ID = %s",
                    (rec_id,))
        return cur.rowcount > 0


# ── Web-Passwort (pro Lieferant in DORFKERN_KONFIG) ──────────────────────────

def web_password_setzen(kuerzel: str, password: str,
                        ma_id: Optional[int] = None) -> None:
    """Speichert das Web-Passwort eines Lieferanten als SECRET.
    Leerer String entfernt den Eintrag (loescht den Konfig-Schluessel).
    """
    schluessel = web_password_key(kuerzel)
    if password is None or password == '':
        # Loeschen via UPDATE auf leeren String – beim naechsten Lesen
        # liefert konfig.get None zurueck. Wir entfernen den Eintrag
        # ganz, damit "leer" und "ungesetzt" deckungsgleich sind.
        try:
            from common.db import get_db_transaction as _txn
            with _txn() as cur:
                cur.execute(
                    "DELETE FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                    (schluessel,))
            _konfig.invalidate(schluessel)
        except Exception as exc:
            log.warning("web_password_setzen(loeschen) %s: %s", kuerzel, exc)
        return
    _konfig.set(schluessel, password, typ='SECRET',
                kategorie='EINKAUF',
                beschreibung=f'Web-Passwort fuer Lieferant {kuerzel}',
                ma_id=ma_id)


def web_password_gesetzt(kuerzel: str) -> bool:
    """True wenn fuer den Lieferanten ein Web-Passwort hinterlegt ist."""
    return bool(_konfig.get(web_password_key(kuerzel)))


def web_password_holen(kuerzel: str) -> Optional[str]:
    """Liefert das Klartext-Passwort (nur fuer den Daemon/Scraper)."""
    wert = _konfig.get(web_password_key(kuerzel))
    return str(wert) if wert else None


# ── IMAP-Konfiguration ───────────────────────────────────────────────────────

def imap_konfig() -> dict[str, Any]:
    """Liefert die effektive IMAP-Konfiguration (Werte aus DORFKERN_KONFIG
    plus Defaults fuer ungesetzte Felder).
    """
    return {
        'host':      _konfig.get(KEY_IMAP_HOST, '') or '',
        'port':      int(_konfig.get(KEY_IMAP_PORT, DEFAULT_IMAP_PORT)
                         or DEFAULT_IMAP_PORT),
        'user':      _konfig.get(KEY_IMAP_USER, '') or '',
        'use_ssl':   bool(_konfig.get(KEY_IMAP_USE_SSL,
                                      DEFAULT_IMAP_USE_SSL)),
        'folder':    _konfig.get(KEY_IMAP_FOLDER, DEFAULT_IMAP_FOLDER)
                     or DEFAULT_IMAP_FOLDER,
        'poll_min':  int(_konfig.get(KEY_IMAP_POLL_MIN,
                                     DEFAULT_IMAP_POLL_MIN)
                         or DEFAULT_IMAP_POLL_MIN),
        'password_gesetzt': bool(_konfig.get(KEY_IMAP_PASSWORD)),
    }


def imap_konfig_speichern(host: Optional[str] = None,
                          port: Optional[int] = None,
                          user: Optional[str] = None,
                          password: Optional[str] = None,
                          use_ssl: Optional[bool] = None,
                          folder: Optional[str] = None,
                          poll_min: Optional[int] = None,
                          ma_id: Optional[int] = None) -> dict:
    """Schreibt die uebergebenen Felder in DORFKERN_KONFIG.
    ``None`` = nicht aendern. ``''`` (leerer String) bei password
    bedeutet: Passwort entfernen.
    """
    if host is not None:
        _konfig.set(KEY_IMAP_HOST, host.strip(), typ='STRING',
                    kategorie='EINKAUF',
                    beschreibung='IMAP-Host fuer Bestellbestaetigungen',
                    ma_id=ma_id)
    if port is not None:
        _konfig.set(KEY_IMAP_PORT, int(port), typ='INT',
                    kategorie='EINKAUF',
                    beschreibung='IMAP-Port', ma_id=ma_id)
    if user is not None:
        _konfig.set(KEY_IMAP_USER, user.strip(), typ='STRING',
                    kategorie='EINKAUF',
                    beschreibung='IMAP-Benutzer (Postfach)', ma_id=ma_id)
    if password is not None:
        if password == '':
            try:
                with get_db_transaction() as cur:
                    cur.execute(
                        "DELETE FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                        (KEY_IMAP_PASSWORD,))
                _konfig.invalidate(KEY_IMAP_PASSWORD)
            except Exception as exc:
                log.warning("imap_konfig_speichern: pw-DELETE: %s", exc)
        else:
            _konfig.set(KEY_IMAP_PASSWORD, password, typ='SECRET',
                        kategorie='EINKAUF',
                        beschreibung='IMAP-App-Passwort', ma_id=ma_id)
    if use_ssl is not None:
        _konfig.set(KEY_IMAP_USE_SSL, bool(use_ssl), typ='BOOL',
                    kategorie='EINKAUF',
                    beschreibung='SSL/TLS verwenden', ma_id=ma_id)
    if folder is not None:
        _konfig.set(KEY_IMAP_FOLDER, folder.strip() or DEFAULT_IMAP_FOLDER,
                    typ='STRING', kategorie='EINKAUF',
                    beschreibung='IMAP-Ordner', ma_id=ma_id)
    if poll_min is not None:
        _konfig.set(KEY_IMAP_POLL_MIN, int(poll_min), typ='INT',
                    kategorie='EINKAUF',
                    beschreibung='Poll-Intervall (Minuten)', ma_id=ma_id)
    return imap_konfig()


def imap_verbindungstest() -> dict:
    """Versucht ein IMAP-Login mit der gespeicherten Konfiguration und
    liest die Anzahl Nachrichten im Inbox-Ordner.

    Returns: ``{'ok': bool, 'msg': str, 'anzahl': int|None}``.
    Verwendet kurze Timeouts; rotiert bei Erfolg sofort wieder aus.
    """
    cfg = imap_konfig()
    host = cfg['host']
    user = cfg['user']
    password = _konfig.get(KEY_IMAP_PASSWORD)
    if not (host and user and password):
        return {'ok': False, 'anzahl': None,
                'msg': 'IMAP-Host, Benutzer oder Passwort nicht gesetzt.'}
    # Default-Socket-Timeout schmal halten (sonst blockiert ein toter
    # Server den Webrequest minutenlang).
    alt_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(10)
    try:
        if cfg['use_ssl']:
            client = imaplib.IMAP4_SSL(host, cfg['port'])
        else:
            client = imaplib.IMAP4(host, cfg['port'])
        try:
            client.login(user, password)
            typ, daten = client.select(cfg['folder'], readonly=True)
            if typ != 'OK':
                return {'ok': False, 'anzahl': None,
                        'msg': f'Ordner {cfg["folder"]!r} nicht zugaenglich.'}
            anzahl = int(daten[0]) if daten and daten[0] else 0
            return {'ok': True, 'anzahl': anzahl,
                    'msg': f'Login OK · {anzahl} Mails in '
                           f'{cfg["folder"]!r}.'}
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except imaplib.IMAP4.error as exc:
        return {'ok': False, 'anzahl': None,
                'msg': f'IMAP-Fehler: {exc}'}
    except (socket.timeout, OSError) as exc:
        return {'ok': False, 'anzahl': None,
                'msg': f'Verbindung fehlgeschlagen: {exc}'}
    finally:
        socket.setdefaulttimeout(alt_timeout)
