"""
CAO-XT – Einkauf: Lieferanten-Registry + Postfach-Zugang

Phase 1 des Einkaufsprozesses (siehe DECISIONS / Auto-Memory):
  * Lieferanten-Stammdaten in ``XT_EINKAUF_LIEFERANT``
    (Erkennungsmuster fuer eingehende Bestellbestaetigungs-Mails,
    optionale Web-Login-Daten fuer Stammdaten-Anreicherung)
  * Postfach-Zugang zentral in ``DORFKERN_KONFIG`` (Kategorie EINKAUF):
      - Gmail-API ueber OAuth 2.0 (Refresh-Token), aktueller Default
        fuer das Habacher Workspace-Postfach
        ``bestellung@habacher-dorfladen.de``.
      - IMAP+App-Passwort (Legacy) bleibt im Code fuer Nicht-Gmail-
        Provider und alte Setups; im UI aktuell ausgeblendet.
  * Verbindungstest fuer beide Pfade (Gmail-API: messages.list,
    IMAP: Login + Folder-Select).

Spaetere Phasen (Email-Polling, CAO-Sync, Bestell-Erstellung) bauen auf
diesem Modul auf. Web-Passwort, IMAP-Passwort, OAuth-Refresh-Token und
OAuth-Client-Secret werden als ``TYP='SECRET'`` in ``DORFKERN_KONFIG``
abgelegt – Klartext bis Verschluesselungs-Roll-out (siehe konfig.py).

CAO-Tabellen werden hier NICHT angefasst – die Einbindung des Lieferanten
in ``ADRESSEN`` erfolgt erst, wenn der Anwender im Admin-UI explizit
einen Adressdatensatz zuordnet (Feld ``CAO_LIEF_ID``).
"""
from __future__ import annotations

import imaplib
import logging
import os
import re
import socket
from typing import Any, Optional

from common.db import get_db, get_db_transaction
from common import konfig as _konfig

log = logging.getLogger(__name__)

# Gmail-API + OAuth-Imports werden lazy gemacht – das Modul soll auch
# auf einem System hochkommen, auf dem die google-* Bibliotheken (noch)
# fehlen. Funktionen, die diese brauchen, faellen mit klarer Meldung.
GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


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
    """Legt die Einkauf-Tabellen an. Idempotent.

    * XT_EINKAUF_LIEFERANT (Phase 1): Lieferanten-Registry
    * XT_EINKAUF_BESTELLUNG (Phase 2): eingegangene
      Bestellbestaetigungs-Mails als Roh-Container
    * XT_EINKAUF_BESTELLPOS (Phase 2): Positionen aus dem Parser

    Email-Erkennungs-Patterns werden aktuell als Substring-Match
    (case-insensitive) interpretiert.
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
                  WEB_KUNDEN_NR          VARCHAR(40)  NULL,
                  WEB_KEY                VARCHAR(40)  NULL,
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
            # Idempotente Spalten-Erweiterung fuer bestehende Installationen
            for col, ddl in [
                ('WEB_KUNDEN_NR', 'VARCHAR(40)  NULL AFTER WEB_USERNAME'),
                ('WEB_KEY',       'VARCHAR(40)  NULL AFTER WEB_KUNDEN_NR'),
            ]:
                cur.execute("""
                    SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME   = 'XT_EINKAUF_LIEFERANT'
                      AND COLUMN_NAME  = %s
                """, (col,))
                if int((cur.fetchone() or {}).get('n', 0)) == 0:
                    cur.execute(f"ALTER TABLE XT_EINKAUF_LIEFERANT "
                                f"ADD COLUMN {col} {ddl}")

            # Cache-Tabelle Erweiterung: BILD_LOKAL fuer offline-faehige
            # Anzeige von Lieferanten-Bildern (Phase 4).
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'XT_EINKAUF_LIEF_ARTIKEL'
                  AND COLUMN_NAME  = 'BILD_LOKAL'
            """)
            if int((cur.fetchone() or {}).get('n', 0)) == 0:
                cur.execute("ALTER TABLE XT_EINKAUF_LIEF_ARTIKEL "
                            "ADD COLUMN BILD_LOKAL VARCHAR(255) NULL "
                            "AFTER BILD_URL")

            # XT_EINKAUF_BESTELLPOS.STATUS: 'neu_anlegen' fuer manuell
            # bestaetigte „echt neu"-Positionen ergaenzen.
            cur.execute("""
                SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'XT_EINKAUF_BESTELLPOS'
                  AND COLUMN_NAME  = 'STATUS'
            """)
            row = cur.fetchone()
            ctype = (row or {}).get('COLUMN_TYPE') or ''
            if row and 'neu_anlegen' not in ctype:
                cur.execute("""
                    ALTER TABLE XT_EINKAUF_BESTELLPOS
                    MODIFY COLUMN STATUS
                      ENUM('neu','matched','in_cao','fehler','neu_anlegen')
                      NOT NULL DEFAULT 'neu'
                """)
                ctype = "enum('neu','matched','in_cao','fehler','neu_anlegen')"
            if 'manuell_klaeren' not in ctype:
                # Positionen ohne Lieferanten-Stammdaten (Cache leer)
                # bleiben fuer manuelle Nacharbeit liegen.
                cur.execute("""
                    ALTER TABLE XT_EINKAUF_BESTELLPOS
                    MODIFY COLUMN STATUS
                      ENUM('neu','matched','in_cao','fehler',
                           'neu_anlegen','manuell_klaeren')
                      NOT NULL DEFAULT 'neu'
                """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINKAUF_BESTELLUNG (
                  REC_ID            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  LIEF_REC_ID       INT UNSIGNED NOT NULL,
                  GMAIL_MSG_ID      VARCHAR(64)  NOT NULL,
                  GMAIL_THREAD_ID   VARCHAR(64)  NULL,
                  ABSENDER          VARCHAR(255) NULL,
                  BETREFF           VARCHAR(255) NULL,
                  EMAIL_DATUM       DATETIME     NULL,
                  ROHTEXT           MEDIUMTEXT   NULL,
                  ROHHTML           MEDIUMTEXT   NULL,
                  STATUS            ENUM('neu','geparst','in_cao','fehler','verworfen')
                                     NOT NULL DEFAULT 'neu',
                  BESTELL_NR        VARCHAR(40)  NULL,
                  KUNDEN_NR         VARCHAR(40)  NULL,
                  GESAMTSUMME_NETTO DECIMAL(12,4) NULL,
                  ANZ_POSITIONEN    INT          NULL,
                  PARSE_FEHLER      TEXT         NULL,
                  EINGANG_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  GEAENDERT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
                  BEARBEITET_VON    INT          NULL,
                  UNIQUE KEY uq_gmail_msg (GMAIL_MSG_ID),
                  INDEX idx_status (STATUS),
                  INDEX idx_lief (LIEF_REC_ID),
                  CONSTRAINT fk_einkauf_best_lief
                    FOREIGN KEY (LIEF_REC_ID) REFERENCES XT_EINKAUF_LIEFERANT(REC_ID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Einkauf: eingegangene Bestellbestaetigungs-Mails (Phase 2)'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINKAUF_LIEF_ARTIKEL (
                  REC_ID            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  LIEF_REC_ID       INT UNSIGNED NOT NULL,
                  ARTIKEL_NR_LIEF   VARCHAR(40)  NOT NULL,
                  INTERNAL_ID       VARCHAR(40)  NULL,
                  SLUG              VARCHAR(160) NULL,
                  BEZEICHNUNG       VARCHAR(255) NULL,
                  BARCODE_STUECK    VARCHAR(40)  NULL,
                  BARCODE_KT        VARCHAR(40)  NULL,
                  EK_NETTO          DECIMAL(12,4) NULL,
                  UVP_BRUTTO        DECIMAL(12,4) NULL,
                  MWST_PCT          TINYINT      NULL,
                  VPE_EK            INT          NULL,
                  INHALT            VARCHAR(60)  NULL,
                  EINHEIT           VARCHAR(40)  NULL,
                  BILD_URL          VARCHAR(500) NULL,
                  BILD_LOKAL        VARCHAR(255) NULL,
                  VERFUEGBARKEIT    VARCHAR(80)  NULL,
                  ABFRAGE_FEHLER    VARCHAR(500) NULL,
                  ABGEFRAGT_AT      DATETIME     NULL,
                  ERSTELLT_AT       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  GEAENDERT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_lief_artnr (LIEF_REC_ID, ARTIKEL_NR_LIEF),
                  INDEX idx_barcode_stueck (BARCODE_STUECK),
                  INDEX idx_barcode_kt (BARCODE_KT),
                  CONSTRAINT fk_einkauf_liefart_lief
                    FOREIGN KEY (LIEF_REC_ID) REFERENCES XT_EINKAUF_LIEFERANT(REC_ID)
                    ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Einkauf: Stammdaten-Cache pro Lieferanten-Artikel (Phase 4)'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINKAUF_POLLER_STATUS (
                  REC_ID          TINYINT UNSIGNED NOT NULL DEFAULT 1 PRIMARY KEY,
                  LAST_RUN_AT     DATETIME NULL,
                  LAST_SUCCESS_AT DATETIME NULL,
                  GMAIL_OK        TINYINT(1) NOT NULL DEFAULT 0,
                  LAST_ERROR      VARCHAR(500) NULL,
                  ZYKLUS_COUNT    INT UNSIGNED NOT NULL DEFAULT 0,
                  NEU_GEFUNDEN    INT UNSIGNED NOT NULL DEFAULT 0,
                  HOSTNAME        VARCHAR(120) NULL,
                  CHECK (REC_ID = 1)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Einkauf-Poller Single-Row Heartbeat'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINKAUF_BESTELLPOS (
                  REC_ID            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  BEST_REC_ID       INT UNSIGNED NOT NULL,
                  POS_NR            INT UNSIGNED NOT NULL,
                  ARTIKEL_NR_LIEF   VARCHAR(40)  NULL,
                  BESCHREIBUNG_LIEF VARCHAR(255) NULL,
                  MENGE             DECIMAL(12,3) NULL,
                  PREIS_NETTO       DECIMAL(12,4) NULL,
                  ZEILEN_BETRAG     DECIMAL(12,4) NULL,
                  ARTIKEL_REC_ID    INT          NULL,
                  STATUS            ENUM('neu','matched','in_cao','fehler')
                                     NOT NULL DEFAULT 'neu',
                  ANMERKUNG         TEXT         NULL,
                  ERSTELLT_AT       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  INDEX idx_best (BEST_REC_ID),
                  INDEX idx_artnr_lief (ARTIKEL_NR_LIEF),
                  CONSTRAINT fk_einkauf_pos_best
                    FOREIGN KEY (BEST_REC_ID) REFERENCES XT_EINKAUF_BESTELLUNG(REC_ID)
                    ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Einkauf: Bestellpositionen aus dem Parser (Phase 2)'
            """)

            # Phase 5b: Spalte WARENGRUPPE_ID fuer User-Auswahl pro
            # neu-anzulegender Position (CAO-Pflichtfeld). NULL bis
            # User explizit eine Warengruppe waehlt; Sync-Trigger
            # blockiert bei pos_status='neu_anlegen' + WG_ID=NULL.
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'XT_EINKAUF_BESTELLPOS'
                  AND COLUMN_NAME  = 'WARENGRUPPE_ID'
            """)
            if int((cur.fetchone() or {}).get('n', 0)) == 0:
                cur.execute("""
                    ALTER TABLE XT_EINKAUF_BESTELLPOS
                    ADD COLUMN WARENGRUPPE_ID INT NULL
                    AFTER ARTIKEL_REC_ID
                """)

            # Phase 5b: XT_ARTIKEL_VK_KONTROLLE — Audit-Liste der
            # Artikel die nach einem CAO-Sync (Anlage oder EK-Aenderung)
            # eine VK-Pruefung brauchen. UI in Orga/Artikel/Preispflege
            # zeigt offene Eintraege als „⚠ VK-Kontrolle ausstehend".
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_ARTIKEL_VK_KONTROLLE (
                  REC_ID         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  ARTIKEL_REC_ID INT          NOT NULL,
                  GRUND          ENUM('neu','ek_geaendert')
                                  NOT NULL DEFAULT 'neu',
                  ALT_EK         DECIMAL(12,4) NULL,
                  NEU_EK         DECIMAL(12,4) NULL,
                  QUELLE_BEST    INT UNSIGNED  NULL,
                  ANGELEGT_AT    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  ANGELEGT_VON   INT           NULL,
                  ERLEDIGT_AT    DATETIME      NULL,
                  ERLEDIGT_VON   INT           NULL,
                  ANMERKUNG      TEXT          NULL,
                  INDEX idx_artikel (ARTIKEL_REC_ID),
                  INDEX idx_offen (ERLEDIGT_AT, GRUND),
                  INDEX idx_quelle_best (QUELLE_BEST)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Phase 5b: VK-Kontrolle bei neu angelegtem Artikel oder EK-Aenderung'
            """)
        log.info("Migration: XT_EINKAUF_LIEFERANT/BESTELLUNG/BESTELLPOS geprueft.")
    except Exception as exc:
        log.warning("XT_EINKAUF_*-Migration fehlgeschlagen: %s", exc)


def seed_defaults() -> int:
    """Legt einen UTZ-Default-Lieferanten an, falls keiner existiert.

    Werte stammen aus der Beispiel-Bestellbestaetigung
    (siehe Auto-Memory-Notiz Einkaufsprozess). ``INSERT IGNORE``
    (UNIQUE auf KUERZEL) – nachtraegliche Aenderungen im Admin-UI
    bleiben erhalten.

    Zusaetzlich: zarter Backfill fuer den UTZ-Bestandseintrag, der
    aus aelteren Migrationen (Phase 1) noch ohne ``WEB_KEY`` und mit
    der vorlaeufigen Login-URL existieren kann. ``WEB_USERNAME`` /
    ``WEB_KUNDEN_NR`` / Passwort werden NIE ueberschrieben (sind
    User-Daten).
    """
    anzahl = 0
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                INSERT IGNORE INTO XT_EINKAUF_LIEFERANT
                  (KUERZEL, BEZEICHNUNG, EMAIL_VON_PATTERN,
                   EMAIL_SUBJECT_PATTERN, WEB_LOGIN_URL, WEB_KEY,
                   PARSER_KEY, AKTIV)
                VALUES
                  ('UTZ', 'UTZ Lebensmittel', 'webportal@utz24.online',
                   'Ihre Bestellung (UTZ Lebensmittel)',
                   'https://www.utz24.online/grosshandlung/de/?action=shop_login',
                   'utz24', 'utz_v1', 1)
            """)
            anzahl = cur.rowcount
            # Backfill nur, wenn WEB_KEY noch nicht gesetzt ist
            cur.execute("""
                UPDATE XT_EINKAUF_LIEFERANT
                   SET WEB_KEY = 'utz24',
                       WEB_LOGIN_URL = COALESCE(NULLIF(WEB_LOGIN_URL, ''),
                           'https://www.utz24.online/grosshandlung/de/?action=shop_login')
                 WHERE KUERZEL = 'UTZ'
                   AND (WEB_KEY IS NULL OR WEB_KEY = '')
            """)
            # Zweiter Backfill: alten Default 'https://utz24.online/' auf
            # den korrekten Login-Endpoint hochziehen.
            cur.execute("""
                UPDATE XT_EINKAUF_LIEFERANT
                   SET WEB_LOGIN_URL =
                       'https://www.utz24.online/grosshandlung/de/?action=shop_login'
                 WHERE KUERZEL = 'UTZ'
                   AND WEB_LOGIN_URL = 'https://utz24.online/'
            """)
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
           "WEB_USERNAME, WEB_KUNDEN_NR, WEB_KEY, PARSER_KEY, AKTIV, "
           "ERSTELLT_AM, GEAENDERT_AM "
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
                "WEB_USERNAME, WEB_KUNDEN_NR, WEB_KEY, PARSER_KEY, "
                "AKTIV, ERSTELLT_AM, GEAENDERT_AM "
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
               WEB_KUNDEN_NR, WEB_KEY, PARSER_KEY, AKTIV, GEAENDERT_VON)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            kuerzel, bez,
            daten.get('CAO_LIEF_ID') or None,
            (daten.get('EMAIL_VON_PATTERN') or '').strip() or None,
            (daten.get('EMAIL_SUBJECT_PATTERN') or '').strip() or None,
            (daten.get('WEB_LOGIN_URL') or '').strip() or None,
            (daten.get('WEB_USERNAME') or '').strip() or None,
            (daten.get('WEB_KUNDEN_NR') or '').strip() or None,
            (daten.get('WEB_KEY') or '').strip() or None,
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
        'WEB_KUNDEN_NR', 'WEB_KEY',
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


# ── Gmail-API / OAuth 2.0 ────────────────────────────────────────────────────
#
# Workspace-Konten unterstuetzen seit 2025 keinen reinen
# Username/Passwort-IMAP-Login mehr; App-Passwoerter sind ggf. vom
# Workspace-Admin ueberhaupt nicht zugelassen. Stattdessen sprechen wir
# direkt die Gmail-API ueber OAuth 2.0 an.
#
# Setup einmalig (User-Aufgabe):
#   1. Google Cloud Console: Projekt anlegen
#   2. APIs & Services → Library → "Gmail API" aktivieren
#   3. APIs & Services → OAuth consent screen → Internal (Workspace) →
#      App-Name + Support-Mail eintragen, Scope ``gmail.readonly`` adden
#   4. APIs & Services → Credentials → "Create Credentials" →
#      "OAuth client ID" → Application type "Web application" →
#      Authorized redirect URI eintragen (wird im UI angezeigt)
#   5. Client-ID + Client-Secret im Admin-UI eintragen
#   6. "Mit Google verbinden" klicken → Consent → Refresh-Token wird
#      in DORFKERN_KONFIG abgelegt.

KEY_GMAIL_CLIENT_ID     = 'einkauf.gmail.client_id'
KEY_GMAIL_CLIENT_SECRET = 'einkauf.gmail.client_secret'   # SECRET
KEY_GMAIL_REFRESH_TOKEN = 'einkauf.gmail.refresh_token'   # SECRET
KEY_GMAIL_USER_EMAIL    = 'einkauf.gmail.user_email'
KEY_GMAIL_POLL_MIN      = 'einkauf.gmail.poll_min'

DEFAULT_GMAIL_POLL_MIN = 5

GMAIL_TOKEN_URI = 'https://oauth2.googleapis.com/token'
GMAIL_AUTH_URI  = 'https://accounts.google.com/o/oauth2/v2/auth'


def gmail_konfig() -> dict[str, Any]:
    """Liefert die Gmail-Konfiguration. Geheimnisse werden NICHT
    zurueckgegeben – nur Boolean-Flags ``client_secret_gesetzt`` /
    ``refresh_token_gesetzt`` / ``verbunden``."""
    return {
        'client_id':                _konfig.get(KEY_GMAIL_CLIENT_ID, '') or '',
        'user_email':               _konfig.get(KEY_GMAIL_USER_EMAIL, '') or '',
        'poll_min':                 int(_konfig.get(KEY_GMAIL_POLL_MIN,
                                                    DEFAULT_GMAIL_POLL_MIN)
                                         or DEFAULT_GMAIL_POLL_MIN),
        'client_secret_gesetzt':    bool(_konfig.get(KEY_GMAIL_CLIENT_SECRET)),
        'refresh_token_gesetzt':    bool(_konfig.get(KEY_GMAIL_REFRESH_TOKEN)),
        'verbunden':                bool(_konfig.get(KEY_GMAIL_REFRESH_TOKEN)
                                          and _konfig.get(KEY_GMAIL_CLIENT_ID)
                                          and _konfig.get(KEY_GMAIL_CLIENT_SECRET)),
        'scopes':                   GMAIL_SCOPES,
    }


def gmail_konfig_speichern(client_id: Optional[str] = None,
                           client_secret: Optional[str] = None,
                           user_email: Optional[str] = None,
                           poll_min: Optional[int] = None,
                           ma_id: Optional[int] = None) -> dict:
    """Speichert die uebergebenen Felder. ``None`` = nicht aendern.
    ``client_secret=''`` (leerer String) entfernt das Secret."""
    if client_id is not None:
        _konfig.set(KEY_GMAIL_CLIENT_ID, client_id.strip(), typ='STRING',
                    kategorie='EINKAUF',
                    beschreibung='Gmail-API OAuth-Client-ID', ma_id=ma_id)
    if client_secret is not None:
        if client_secret == '':
            try:
                with get_db_transaction() as cur:
                    cur.execute(
                        "DELETE FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                        (KEY_GMAIL_CLIENT_SECRET,))
                _konfig.invalidate(KEY_GMAIL_CLIENT_SECRET)
            except Exception as exc:
                log.warning("gmail_konfig_speichern: secret-DELETE: %s", exc)
        else:
            _konfig.set(KEY_GMAIL_CLIENT_SECRET, client_secret,
                        typ='SECRET', kategorie='EINKAUF',
                        beschreibung='Gmail-API OAuth-Client-Secret',
                        ma_id=ma_id)
    if user_email is not None:
        _konfig.set(KEY_GMAIL_USER_EMAIL, user_email.strip(), typ='STRING',
                    kategorie='EINKAUF',
                    beschreibung='Gmail-Postfach (zu lesendes Konto)',
                    ma_id=ma_id)
    if poll_min is not None:
        _konfig.set(KEY_GMAIL_POLL_MIN, int(poll_min), typ='INT',
                    kategorie='EINKAUF',
                    beschreibung='Gmail-Poll-Intervall (Minuten)',
                    ma_id=ma_id)
    return gmail_konfig()


def gmail_oauth_url(redirect_uri: str,
                    state: str = '') -> tuple[str, str, str]:
    """Baut die Google-Auth-URL. Der Browser wird auf diese URL
    geleitet; Google leitet nach Consent zurueck zu ``redirect_uri``
    mit einem ``code``-Query-Parameter, den ``gmail_oauth_token_speichern``
    in ein Refresh-Token tauscht.

    Wichtig: ``Flow.authorization_url`` erzeugt seit Library-Version
    1.0+ automatisch ein PKCE-Code-Challenge-Paar. Der passende
    ``code_verifier`` liegt nur im konkreten Flow-Objekt. Wir geben ihn
    mit zurueck, damit der Aufrufer ihn in der Session zwischenspeichern
    und beim Callback ans Token-Tausch-Flow uebergeben kann.

    Returns:
        ``(auth_url, state, code_verifier)``.
    """
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as exc:
        raise RuntimeError(
            'google-auth-oauthlib nicht installiert: '
            'pip install -r admin-app/app/requirements.txt'
        ) from exc

    cfg = gmail_konfig()
    client_id     = cfg.get('client_id') or ''
    client_secret = _konfig.get(KEY_GMAIL_CLIENT_SECRET) or ''
    if not (client_id and client_secret):
        raise ValueError('Client-ID / Client-Secret fehlen.')

    flow = Flow.from_client_config(
        {
            'web': {
                'client_id':     client_id,
                'client_secret': client_secret,
                'auth_uri':      GMAIL_AUTH_URI,
                'token_uri':     GMAIL_TOKEN_URI,
                'redirect_uris': [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, returned_state = flow.authorization_url(
        # ``offline`` plus ``prompt=consent`` erzwingt einen
        # Refresh-Token, auch wenn der User vorher schon zugestimmt hatte
        # (Google liefert sonst nur Access-Tokens).
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=state or None,
    )
    return auth_url, returned_state, flow.code_verifier or ''


def gmail_oauth_token_speichern(code: str, redirect_uri: str,
                                code_verifier: str = '',
                                ma_id: Optional[int] = None) -> dict:
    """Tauscht den Authorization-Code in einen Refresh-Token und legt
    ihn in DORFKERN_KONFIG ab.

    Args:
        code:          Authorization-Code aus dem OAuth-Callback.
        redirect_uri:  Muss exakt mit der bei ``gmail_oauth_url``
                       verwendeten URI uebereinstimmen.
        code_verifier: PKCE-Verifier aus dem Auth-Start-Flow
                       (siehe Tuple-Rueckgabe von ``gmail_oauth_url``).
                       Pflicht wenn der erste Flow PKCE genutzt hat
                       (Default seit google-auth-oauthlib 1.0).
        ma_id:         Optional fuer Audit.

    Returns: ``{'ok': bool, 'msg': str, 'email': str|None}``.
    """
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as exc:
        return {'ok': False, 'msg': f'google-auth-oauthlib fehlt: {exc}'}

    cfg = gmail_konfig()
    client_id     = cfg.get('client_id') or ''
    client_secret = _konfig.get(KEY_GMAIL_CLIENT_SECRET) or ''
    if not (client_id and client_secret):
        return {'ok': False, 'msg': 'Client-ID/Secret nicht gesetzt.'}

    try:
        flow = Flow.from_client_config(
            {
                'web': {
                    'client_id':     client_id,
                    'client_secret': client_secret,
                    'auth_uri':      GMAIL_AUTH_URI,
                    'token_uri':     GMAIL_TOKEN_URI,
                    'redirect_uris': [redirect_uri],
                }
            },
            scopes=GMAIL_SCOPES,
            redirect_uri=redirect_uri,
        )
        # PKCE-Code-Verifier wieder einsetzen, damit der Token-Tausch
        # zum Code-Challenge im Auth-Request passt.
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
    except Exception as exc:
        log.warning("gmail_oauth_token_speichern: fetch_token: %s", exc)
        return {'ok': False, 'msg': f'Token-Tausch fehlgeschlagen: {exc}'}

    creds = flow.credentials
    if not creds.refresh_token:
        return {'ok': False,
                'msg': 'Kein Refresh-Token zurueckgekommen. '
                       'Tipp: in Google den Zugriff zuerst entziehen, '
                       'dann erneut verbinden.'}

    _konfig.set(KEY_GMAIL_REFRESH_TOKEN, creds.refresh_token,
                typ='SECRET', kategorie='EINKAUF',
                beschreibung='Gmail-API OAuth Refresh-Token',
                ma_id=ma_id)

    # Profil-Mail abfragen, damit das UI bestaetigt, welches Postfach
    # verbunden wurde.
    email = None
    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds,
                        cache_discovery=False)
        prof = service.users().getProfile(userId='me').execute()
        email = prof.get('emailAddress')
        if email and not _konfig.get(KEY_GMAIL_USER_EMAIL):
            _konfig.set(KEY_GMAIL_USER_EMAIL, email, typ='STRING',
                        kategorie='EINKAUF',
                        beschreibung='Gmail-Postfach (zu lesendes Konto)',
                        ma_id=ma_id)
    except Exception as exc:
        log.warning("Gmail-Profil-Abfrage nach Verbindung: %s", exc)

    return {'ok': True, 'msg': 'Verbindung gespeichert.', 'email': email}


def gmail_oauth_disconnect(ma_id: Optional[int] = None) -> dict:
    """Loescht den Refresh-Token. Versucht ausserdem, den Token bei
    Google zu widerrufen (best-effort)."""
    refresh = _konfig.get(KEY_GMAIL_REFRESH_TOKEN)
    if refresh:
        try:
            import urllib.request
            import urllib.parse
            urllib.request.urlopen(
                'https://oauth2.googleapis.com/revoke',
                data=urllib.parse.urlencode({'token': refresh}).encode(),
                timeout=5,
            )
        except Exception as exc:
            log.warning("Gmail-Token-Revoke best-effort fehlgeschlagen: %s",
                        exc)
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                (KEY_GMAIL_REFRESH_TOKEN,))
        _konfig.invalidate(KEY_GMAIL_REFRESH_TOKEN)
    except Exception as exc:
        return {'ok': False, 'msg': f'DB-Fehler: {exc}'}
    return {'ok': True, 'msg': 'Verbindung getrennt.'}


def gmail_credentials():
    """Baut frische ``google.oauth2.credentials.Credentials`` aus dem
    gespeicherten Refresh-Token (fuer den Daemon und Verbindungstests).
    Wirft ``RuntimeError`` wenn etwas fehlt.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise RuntimeError('google-auth nicht installiert.') from exc

    cfg = gmail_konfig()
    client_id     = cfg.get('client_id') or ''
    client_secret = _konfig.get(KEY_GMAIL_CLIENT_SECRET) or ''
    refresh       = _konfig.get(KEY_GMAIL_REFRESH_TOKEN) or ''
    if not (client_id and client_secret and refresh):
        raise RuntimeError('Gmail-OAuth nicht vollstaendig konfiguriert.')

    return Credentials(
        token=None,
        refresh_token=refresh,
        token_uri=GMAIL_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )


def gmail_verbindungstest() -> dict:
    """Macht einen ``users.getProfile``-Call und liefert
    Profil-Mail + Anzahl ungelesener Mails im INBOX."""
    try:
        creds = gmail_credentials()
    except Exception as exc:
        return {'ok': False, 'anzahl': None,
                'msg': f'Konfiguration unvollstaendig: {exc}'}
    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds,
                        cache_discovery=False)
        prof = service.users().getProfile(userId='me').execute()
        # Ungelesene Mails im INBOX zaehlen (cheaper als full list)
        labels = service.users().labels().get(
            userId='me', id='INBOX').execute()
        return {
            'ok':     True,
            'anzahl': labels.get('messagesUnread'),
            'msg':    f'Verbunden mit {prof.get("emailAddress")} · '
                      f'{labels.get("messagesTotal", "?")} Mails gesamt, '
                      f'{labels.get("messagesUnread", 0)} ungelesen.',
            'email':  prof.get('emailAddress'),
        }
    except Exception as exc:
        return {'ok': False, 'anzahl': None,
                'msg': f'Gmail-API-Fehler: {exc}'}


# ── Gmail-Fetch: Bestellbestaetigungen abholen + persistieren ───────────────

def _gmail_query_fuer_lieferant(lief: dict, neuer_als_tage: int = 30) -> str:
    """Baut die Gmail-Search-Query aus den Erkennungs-Patterns eines
    Lieferanten. Beispiel:
        from:webportal@utz24.online
        subject:"Ihre Bestellung (UTZ Lebensmittel)"
        newer_than:30d
    """
    teile: list[str] = []
    von = (lief.get('EMAIL_VON_PATTERN') or '').strip()
    if von:
        teile.append(f'from:{von}')
    subj = (lief.get('EMAIL_SUBJECT_PATTERN') or '').strip()
    if subj:
        # Subject mit Anfuehrungszeichen, falls Leerzeichen darin
        teile.append(f'subject:"{subj}"')
    teile.append(f'newer_than:{int(neuer_als_tage)}d')
    return ' '.join(teile)


def _gmail_extract_plain(payload: dict) -> str:
    """Sucht rekursiv im Gmail-Message-Payload nach text/plain und
    liefert den dekodierten String. Faellt zurueck auf den ersten
    text/* Teil falls kein plain.
    """
    import base64
    def _walk(part: dict) -> Optional[str]:
        mime = (part.get('mimeType') or '').lower()
        body = part.get('body') or {}
        data = body.get('data')
        if mime == 'text/plain' and data:
            return base64.urlsafe_b64decode(data + '===').decode(
                'utf-8', errors='replace')
        for kind in part.get('parts') or []:
            r = _walk(kind)
            if r is not None:
                return r
        return None

    plain = _walk(payload)
    if plain is not None:
        return plain
    # Fallback: erstes text/html (HTML-Tags grob strippen)
    def _walk_html(part: dict) -> Optional[str]:
        mime = (part.get('mimeType') or '').lower()
        body = part.get('body') or {}
        data = body.get('data')
        if mime == 'text/html' and data:
            raw = base64.urlsafe_b64decode(data + '===').decode(
                'utf-8', errors='replace')
            # Sehr roh: alle Tags durch Whitespace ersetzen
            import re as _re
            return _re.sub(r'<[^>]+>', ' ', raw)
        for kind in part.get('parts') or []:
            r = _walk_html(kind)
            if r is not None:
                return r
        return None
    return _walk_html(payload) or ''


def _gmail_extract_html(payload: dict) -> str:
    """Liefert den text/html-Teil dekodiert (oder leeren String)."""
    import base64
    def _walk(part: dict) -> Optional[str]:
        mime = (part.get('mimeType') or '').lower()
        body = part.get('body') or {}
        data = body.get('data')
        if mime == 'text/html' and data:
            return base64.urlsafe_b64decode(data + '===').decode(
                'utf-8', errors='replace')
        for kind in part.get('parts') or []:
            r = _walk(kind)
            if r is not None:
                return r
        return None
    return _walk(payload) or ''


def _gmail_header(payload: dict, name: str) -> str:
    """Liefert einen Header-Wert (case-insensitiv)."""
    name_low = name.lower()
    for h in payload.get('headers') or []:
        if (h.get('name') or '').lower() == name_low:
            return h.get('value') or ''
    return ''


def _email_datum_parsen(s: str):
    """Wandelt einen RFC2822-Datum-String in datetime (oder None)."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        return None


def gmail_fetch_neue_bestellungen(neuer_als_tage: int = 30,
                                  max_pro_lieferant: int = 30,
                                  ma_id: Optional[int] = None) -> dict:
    """Holt fuer jeden aktiven Lieferanten neue Bestellbestaetigungen
    aus dem verbundenen Gmail-Postfach, parst sie und persistiert sie
    in ``XT_EINKAUF_BESTELLUNG`` (mit Positionen in
    ``XT_EINKAUF_BESTELLPOS``).

    Bereits eingelagerte Mails (UNIQUE-Constraint auf
    ``GMAIL_MSG_ID``) werden uebersprungen.

    Returns: ``{'ok': bool, 'gefunden': N, 'neu': N, 'lieferanten':
        [{'kuerzel', 'gefunden', 'neu', 'fehler'}], 'fehler': str|None}``.
    """
    try:
        creds = gmail_credentials()
    except Exception as exc:
        return {'ok': False, 'fehler': str(exc),
                'gefunden': 0, 'neu': 0, 'lieferanten': []}

    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds,
                        cache_discovery=False)
    except Exception as exc:
        return {'ok': False, 'fehler': f'Gmail-Client-Build: {exc}',
                'gefunden': 0, 'neu': 0, 'lieferanten': []}

    from common.einkauf_parser import parse_email

    lieferanten = liste(nur_aktive=True)
    summe_gefunden = 0
    summe_neu     = 0
    pro_lief_log: list[dict] = []

    for lief in lieferanten:
        kuerzel = lief['KUERZEL']
        if not lief.get('EMAIL_VON_PATTERN'):
            continue
        lief_log = {
            'kuerzel': kuerzel, 'gefunden': 0, 'neu': 0, 'fehler': None,
        }
        try:
            query = _gmail_query_fuer_lieferant(lief, neuer_als_tage)
            res = service.users().messages().list(
                userId='me', q=query,
                maxResults=max_pro_lieferant).execute()
            ids = [m['id'] for m in res.get('messages', [])]
            lief_log['gefunden'] = len(ids)
            summe_gefunden += len(ids)

            for msg_id in ids:
                # Schon eingelagert?
                with get_db() as cur:
                    cur.execute(
                        "SELECT REC_ID FROM XT_EINKAUF_BESTELLUNG "
                        "WHERE GMAIL_MSG_ID = %s",
                        (msg_id,))
                    if cur.fetchone():
                        continue

                msg = service.users().messages().get(
                    userId='me', id=msg_id, format='full').execute()
                payload = msg.get('payload', {}) or {}
                plain = _gmail_extract_plain(payload)
                htmlb = _gmail_extract_html(payload)
                betreff = _gmail_header(payload, 'Subject')
                absender = _gmail_header(payload, 'From')
                datum = _email_datum_parsen(_gmail_header(payload, 'Date'))

                geparst = parse_email(lief.get('PARSER_KEY') or '', plain)
                if not geparst.get('fehler') and geparst.get('positionen'):
                    status = 'geparst'
                else:
                    status = 'fehler' if geparst.get('fehler') else 'neu'

                with get_db_transaction() as cur:
                    cur.execute("""
                        INSERT INTO XT_EINKAUF_BESTELLUNG
                          (LIEF_REC_ID, GMAIL_MSG_ID, GMAIL_THREAD_ID,
                           ABSENDER, BETREFF, EMAIL_DATUM,
                           ROHTEXT, ROHHTML, STATUS,
                           BESTELL_NR, KUNDEN_NR,
                           GESAMTSUMME_NETTO, ANZ_POSITIONEN,
                           PARSE_FEHLER, BEARBEITET_VON)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        lief['REC_ID'], msg_id, msg.get('threadId'),
                        absender[:255], betreff[:255], datum,
                        plain, htmlb, status,
                        (geparst.get('best_nr') or '')[:40] or None,
                        (geparst.get('kunden_nr') or '')[:40] if geparst.get('kunden_nr') else None,
                        geparst.get('gesamtsumme_netto'),
                        len(geparst.get('positionen') or []),
                        geparst.get('fehler'),
                        ma_id,
                    ))
                    best_id = int(cur.lastrowid)
                    for p in geparst.get('positionen') or []:
                        cur.execute("""
                            INSERT INTO XT_EINKAUF_BESTELLPOS
                              (BEST_REC_ID, POS_NR, ARTIKEL_NR_LIEF,
                               BESCHREIBUNG_LIEF, MENGE, PREIS_NETTO,
                               ZEILEN_BETRAG)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            best_id, p['pos_nr'],
                            (p.get('artikel_nr_lief') or '')[:40],
                            (p.get('bezeichnung_lief') or '')[:255],
                            p.get('menge'),
                            p.get('preis_netto'),
                            p.get('zeilen_betrag'),
                        ))
                lief_log['neu'] += 1
                summe_neu += 1
        except Exception as exc:
            log.exception("Gmail-Fetch fuer %s fehlgeschlagen", kuerzel)
            lief_log['fehler'] = str(exc)
        pro_lief_log.append(lief_log)

    return {'ok': True, 'fehler': None,
            'gefunden': summe_gefunden, 'neu': summe_neu,
            'lieferanten': pro_lief_log}


# ── Bestellungen-CRUD (Listen-Ansicht im UI) ─────────────────────────────────

def bestellungen_liste(status: Optional[str] = None,
                       limit: int = 100) -> list[dict]:
    """Liefert eingegangene Bestellungen sortiert nach EMAIL_DATUM desc."""
    sql = ("SELECT b.REC_ID, b.LIEF_REC_ID, l.KUERZEL AS LIEF_KUERZEL, "
           "l.BEZEICHNUNG AS LIEF_BEZ, b.GMAIL_MSG_ID, b.ABSENDER, "
           "b.BETREFF, b.EMAIL_DATUM, b.STATUS, b.BESTELL_NR, "
           "b.KUNDEN_NR, b.GESAMTSUMME_NETTO, b.ANZ_POSITIONEN, "
           "b.PARSE_FEHLER, b.EINGANG_AT "
           "FROM XT_EINKAUF_BESTELLUNG b "
           "JOIN XT_EINKAUF_LIEFERANT l ON l.REC_ID = b.LIEF_REC_ID")
    params: tuple = ()
    if status:
        sql += " WHERE b.STATUS = %s"
        params = (status,)
    sql += " ORDER BY b.EMAIL_DATUM DESC, b.REC_ID DESC LIMIT %s"
    params = params + (int(limit),)
    try:
        with get_db() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("bestellungen_liste: %s", exc)
        return []


# ── Fuzzy-Vorschlag fuer noch nicht zugeordnete Positionen ──────────────────
#
# Wenn die BESTNUM-Match nichts findet, kann der CAO-Stammartikel trotzdem
# bereits da sein – nur unter einer anderen Lieferanten-ArtNr (z.B. weil
# frueher bei einem anderen Lieferanten gepflegt wurde, oder die
# Lieferanten-Nr-Verknuepfung in ARTIKEL_PREIS noch fehlt). Dafuer eine
# heuristische Bezeichnungs-Suche.

# Stoppwoerter, die in der Suche keinen Mehrwert bringen
_BEZ_STOP = {
    'bio', 'fettarm', 'ungeschnitten', 'natur', 'frisch', 'klassisch',
    'classic', 'vegan', 'ohne', 'mit', 'der', 'die', 'das', 'und',
    'fuer', 'fett', 'lagig', 'pack', 'fuer', 'jeden', 'tag', 'eckig',
    'rund', 'eis', 'tk', 'gross', 'klein', 'hoch', 'pro',
    'kg', 'g', 'ml', 'l', 'cl', 'st', 'stk', 'stueck',
}
_BEZ_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß0-9]{4,}")


def _bezeichnungs_tokens(bez: str) -> list[str]:
    """Extrahiert Such-relevante Tokens aus einer Lieferanten-Bezeichnung.

    Strategie: alphanum-Sequenzen >= 4 Zeichen, ohne Stoppwoerter,
    sortiert nach Laenge absteigend (laengere = spezifischer). Fragezeichen
    (Encoding-Artefakte aus Plain-Text-Mails) werden ignoriert.
    """
    if not bez:
        return []
    # Encoding-? aus PHP-Plain-Texten als Wildcard behandeln
    bez = bez.replace('?', ' ')
    tokens = _BEZ_TOKEN.findall(bez)
    nuetzlich = [t for t in tokens if t.lower() not in _BEZ_STOP]
    # Nach Laenge absteigend, damit wir die spezifischsten zuerst nutzen
    nuetzlich.sort(key=lambda t: -len(t))
    return nuetzlich


def _barcode_konflikt(lief_barcode: str, cao_artikel_rec_id: int) -> bool:
    """True wenn der Lieferanten-Barcode bekannt ist UND der
    CAO-Artikel andere(n) Barcode(s) hat, die nicht uebereinstimmen.

    Ein Konflikt heisst: definitiv NICHT der gleiche Artikel,
    auch wenn die Bezeichnung passt.

    False, wenn:
      * lief_barcode leer (wir wissen es nicht)
      * CAO-Artikel hat keinen Barcode (Stammdaten unvollstaendig
        – Match noch moeglich)
      * CAO-Artikel.BARCODE/BARCODE2/BARCODE3 enthaelt den Lief-Barcode
    """
    if not lief_barcode or not cao_artikel_rec_id:
        return False
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT BARCODE, BARCODE2, BARCODE3 FROM ARTIKEL
                WHERE REC_ID = %s
            """, (int(cao_artikel_rec_id),))
            row = cur.fetchone() or {}
    except Exception:
        return False
    cao_barcodes = [str(row.get(k) or '').strip()
                    for k in ('BARCODE', 'BARCODE2', 'BARCODE3')]
    cao_barcodes = [b for b in cao_barcodes if b]
    if not cao_barcodes:
        # CAO hat keinen Barcode → kein Konflikt feststellbar
        return False
    return lief_barcode.strip() not in cao_barcodes


def cao_artikel_vorschlag(bezeichnung_lief: str,
                          cao_lief_id: Optional[int] = None,
                          limit: int = 3,
                          ausschluss_barcode: str = '') -> list[dict]:
    """Sucht in ARTIKEL nach Bezeichnungs-aehnlichen Stammartikeln.

    Kein Fuzzy im Sinne von Levenshtein – wir nehmen die zwei
    spezifischsten Tokens (>=4 Zeichen, keine Stoppwoerter) und
    verlangen, dass beide im MATCHCODE auftauchen. Das ist robust und
    laesst sich von der DB indizieren.

    Args:
        bezeichnung_lief: BESCHREIBUNG_LIEF aus der Bestellposition.
        cao_lief_id:      wenn gesetzt: bevorzugt Treffer, deren
                          DEFAULT_LIEF_ID auf diesen Lieferanten zeigt.
        limit:            max Treffer.

    Returns: Liste von dicts {rec_id, artnum, matchcode, kas_name,
        warengruppe, ek_preis, vk5b, lager, default_lief_id}.
    """
    tokens = _bezeichnungs_tokens(bezeichnung_lief)[:2]
    if not tokens:
        return []

    # Wir filtern nur aktive (NO_VK_FLAG != 'Y' und USERFELD_02 leer)
    where = ["a.NO_VK_FLAG <> 'Y'",
             "(a.USERFELD_02 IS NULL OR a.USERFELD_02 = '')"]
    params: list = []
    for tok in tokens:
        where.append("(a.MATCHCODE LIKE %s OR a.KAS_NAME LIKE %s "
                     "OR a.KURZNAME LIKE %s)")
        like = f'%{tok}%'
        params.extend([like, like, like])

    # Wenn der Lieferant bekannt ist: nach DEFAULT_LIEF_ID-Treffern zuerst.
    order = ('CASE WHEN a.DEFAULT_LIEF_ID = %s THEN 0 ELSE 1 END, '
             'CHAR_LENGTH(a.MATCHCODE)')
    if cao_lief_id:
        params.append(int(cao_lief_id))
    else:
        order = 'CHAR_LENGTH(a.MATCHCODE)'

    sql = f"""
        SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME, a.KURZNAME,
               a.WARENGRUPPE, a.STEUER_CODE,
               a.EK_PREIS, a.VK5B, a.MENGE_AKT,
               a.DEFAULT_LIEF_ID, a.NO_VK_FLAG, a.USERFELD_02,
               TRIM(a.BARCODE)  AS BARCODE,
               TRIM(a.BARCODE2) AS BARCODE2,
               TRIM(a.BARCODE3) AS BARCODE3
        FROM ARTIKEL a
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT %s
    """
    # Wir holen mehr Kandidaten als limit, damit der Barcode-Filter
    # nicht zu wenige uebrig laesst
    params.append(int(limit) * 3)
    try:
        with get_db() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
    except Exception as exc:
        log.warning("cao_artikel_vorschlag: %s", exc)
        return []

    # Barcode-Filter: bei bekannter Lieferanten-EAN nur Treffer behalten,
    # die entweder selbst keinen Barcode haben (kann derselbe Artikel
    # sein, nur unvollstaendig gepflegt) oder einen passenden enthalten.
    if ausschluss_barcode:
        cleaned = []
        for r in rows:
            cao_barcodes = [str(r.get(k) or '').strip()
                            for k in ('BARCODE', 'BARCODE2', 'BARCODE3')]
            cao_barcodes = [b for b in cao_barcodes if b]
            if cao_barcodes and ausschluss_barcode not in cao_barcodes:
                # Definitiv anderer Artikel – ueberspringen
                continue
            cleaned.append(r)
        rows = cleaned[:limit]
    else:
        rows = rows[:limit]

    return [{
        'rec_id':           r.get('REC_ID'),
        'artnum':           r.get('ARTNUM'),
        'matchcode':        r.get('MATCHCODE'),
        'kas_name':         (r.get('KAS_NAME') or r.get('KURZNAME')
                              or r.get('MATCHCODE')),
        'warengruppe':      r.get('WARENGRUPPE'),
        'ek_preis':         float(r.get('EK_PREIS') or 0),
        'vk5b':             float(r.get('VK5B') or 0),
        'lager':            float(r.get('MENGE_AKT') or 0),
        'default_lief_id':  r.get('DEFAULT_LIEF_ID'),
        'barcodes':         [b for b in (r.get('BARCODE'),
                                          r.get('BARCODE2'),
                                          r.get('BARCODE3')) if b],
        'ean_match':        bool(ausschluss_barcode
                                  and ausschluss_barcode in
                                  [r.get(k) for k in
                                   ('BARCODE', 'BARCODE2', 'BARCODE3')
                                   if r.get(k)]),
    } for r in rows]


# ── Lieferanten-Artikel-Cache (Phase 4) ─────────────────────────────────────

# Verzeichnis fuer lokal gecachte Lieferanten-Bilder.
# Wir spiegeln die existierende ``kiosk-app/app/produktbilder/``-Logik
# (von der die Admin-App ihren ``/produktbilder/<path>``-Endpoint
# bedient) und legen unsere Bilder unter
# ``produktbilder/lieferanten/<KUERZEL>/<artnr>.<ext>`` ab.
_REPO_ROOT_GUESS = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..'))
_PRODUKTBILDER_BASE = os.environ.get('PRODUKTBILDER_DIR') or os.path.join(
    _REPO_ROOT_GUESS, 'kiosk-app', 'app', 'produktbilder')
_LIEF_BILD_DIR = os.path.join(_PRODUKTBILDER_BASE, 'lieferanten')


def _download_lief_bild(url: str, lief_kuerzel: str,
                        artnr: str) -> Optional[str]:
    """Laedt das Produktbild von ``url`` herunter und speichert es
    lokal. Liefert den relativen Pfad (zur Verwendung am
    ``/produktbilder/<path>``-Endpoint), oder ``None`` bei Fehler.

    Pfadschema: ``lieferanten/<KUERZEL>/<artnr>.<ext>``.
    """
    if not (url and lief_kuerzel and artnr):
        return None
    try:
        import requests as _req
    except ImportError:
        log.warning('requests fehlt – Bild-Download uebersprungen.')
        return None

    kuerzel = re.sub(r'[^A-Za-z0-9_-]', '_', lief_kuerzel)[:20]
    artnr_safe = re.sub(r'[^A-Za-z0-9_-]', '_', artnr)[:40]
    zielordner = os.path.join(_LIEF_BILD_DIR, kuerzel)
    os.makedirs(zielordner, exist_ok=True)

    try:
        r = _req.get(url, timeout=15, allow_redirects=True)
    except Exception as exc:
        log.warning('Bild-GET %s: %s', url, exc)
        return None
    if r.status_code != 200:
        log.warning('Bild-Status %s fuer %s', r.status_code, url)
        return None

    ctype = (r.headers.get('Content-Type') or '').lower()
    ext = 'jpg'
    if 'png' in ctype:
        ext = 'png'
    elif 'webp' in ctype:
        ext = 'webp'
    elif 'gif' in ctype:
        ext = 'gif'
    else:
        # Aus der URL ableiten, falls kein Content-Type
        from urllib.parse import urlparse
        path = urlparse(url).path
        if '.' in path:
            kandidat = path.rsplit('.', 1)[-1].lower()[:5]
            if kandidat in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                ext = 'jpeg' if kandidat == 'jpeg' else kandidat
                if ext == 'jpeg':
                    ext = 'jpg'

    dateiname = f'{artnr_safe}.{ext}'
    pfad = os.path.join(zielordner, dateiname)
    try:
        with open(pfad, 'wb') as f:
            f.write(r.content)
    except Exception as exc:
        log.warning('Bild-Save %s: %s', pfad, exc)
        return None

    return f'lieferanten/{kuerzel}/{dateiname}'


def lief_artikel_speichern(lief_rec_id: int, artnr: str,
                           parsed: Optional[dict],
                           fehler: Optional[str] = None) -> int:
    """UPSERT eines Stammdaten-Cache-Eintrags pro Lieferanten-Artikel.
    Liefert die REC_ID. ``parsed`` ist das dict aus
    ``common.einkauf_lief_web._utz_item_to_parsed`` (kann None sein,
    wenn nur ein Fehler-Eintrag persistiert werden soll).
    """
    p = parsed or {}
    bild = (p.get('bild_url') or '')[:500]
    bild_lokal = (p.get('bild_lokal') or '')[:255]
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO XT_EINKAUF_LIEF_ARTIKEL
              (LIEF_REC_ID, ARTIKEL_NR_LIEF, INTERNAL_ID, SLUG,
               BEZEICHNUNG, BARCODE_STUECK, BARCODE_KT,
               EK_NETTO, UVP_BRUTTO, MWST_PCT, VPE_EK,
               INHALT, EINHEIT, BILD_URL, BILD_LOKAL, VERFUEGBARKEIT,
               ABFRAGE_FEHLER, ABGEFRAGT_AT)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
              INTERNAL_ID    = VALUES(INTERNAL_ID),
              SLUG           = VALUES(SLUG),
              BEZEICHNUNG    = VALUES(BEZEICHNUNG),
              BARCODE_STUECK = VALUES(BARCODE_STUECK),
              BARCODE_KT     = VALUES(BARCODE_KT),
              EK_NETTO       = VALUES(EK_NETTO),
              UVP_BRUTTO     = VALUES(UVP_BRUTTO),
              MWST_PCT       = VALUES(MWST_PCT),
              VPE_EK         = VALUES(VPE_EK),
              INHALT         = VALUES(INHALT),
              EINHEIT        = VALUES(EINHEIT),
              BILD_URL       = VALUES(BILD_URL),
              BILD_LOKAL     = COALESCE(VALUES(BILD_LOKAL), BILD_LOKAL),
              VERFUEGBARKEIT = VALUES(VERFUEGBARKEIT),
              ABFRAGE_FEHLER = VALUES(ABFRAGE_FEHLER),
              ABGEFRAGT_AT   = CURRENT_TIMESTAMP
        """, (
            int(lief_rec_id),
            (artnr or '')[:40],
            str(p.get('internal_id') or '')[:40] or None,
            (p.get('slug') or '')[:160] or None,
            (p.get('bezeichnung') or '')[:255] or None,
            (p.get('barcode_stueck') or '')[:40] or None,
            (p.get('barcode_kt') or '')[:40] or None,
            p.get('ek_netto') if p.get('ek_netto') not in (0, 0.0) else None,
            p.get('uvp_brutto') if p.get('uvp_brutto') not in (0, 0.0) else None,
            p.get('mwst_pct'),
            p.get('vpe_ek'),
            (p.get('inhalt') or '')[:60] or None,
            (p.get('einheit') or '')[:40] or None,
            bild or None,
            bild_lokal or None,
            (p.get('verfuegbarkeit') or '')[:80] or None,
            (fehler or '')[:500] or None,
        ))
        return int(cur.lastrowid)


def lief_artikel_holen(lief_rec_id: int, artnr: str) -> Optional[dict]:
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT * FROM XT_EINKAUF_LIEF_ARTIKEL
                WHERE LIEF_REC_ID = %s AND ARTIKEL_NR_LIEF = %s
            """, (int(lief_rec_id), (artnr or '')[:40]))
            return cur.fetchone()
    except Exception as exc:
        log.warning("lief_artikel_holen: %s", exc)
        return None


def lief_artikel_anreichern_position(lief_rec_id: int, artnr: str) -> dict:
    """Holt frische Stammdaten via Web-Treiber, laedt das Produktbild
    lokal nach und persistiert alles.
    Liefert ``{'ok': bool, 'parsed': dict|None, 'msg': str|None}``."""
    from common import einkauf_lief_web as _web
    res = _web.web_artikel_diagnose(lief_rec_id, artnr)
    if not res.get('ok'):
        lief_artikel_speichern(lief_rec_id, artnr, parsed=None,
                               fehler=str(res.get('msg') or 'unbekannt'))
        return {'ok': False, 'parsed': None,
                'msg': str(res.get('msg') or '')}
    parsed = (res.get('probe') or {}).get('parsed') or {}

    # Bild herunterladen, wenn noch nicht im lokalen Cache.
    if parsed.get('bild_url'):
        cached = lief_artikel_holen(lief_rec_id, artnr) or {}
        if not (cached.get('BILD_LOKAL') or '').strip():
            kuerzel = ''
            try:
                lief = holen(lief_rec_id) or {}
                kuerzel = lief.get('KUERZEL') or ''
            except Exception:
                pass
            lokal = _download_lief_bild(parsed['bild_url'], kuerzel, artnr)
            if lokal:
                parsed['bild_lokal'] = lokal
        else:
            parsed['bild_lokal'] = cached.get('BILD_LOKAL') or ''

    lief_artikel_speichern(lief_rec_id, artnr, parsed=parsed)
    return {'ok': True, 'parsed': parsed, 'msg': None}


def bestellung_anreichern(bestellung_rec_id: int,
                          ueberspringe_aktuelle: bool = True) -> dict:
    """Reichert alle Positionen einer Bestellung mit
    Lieferanten-Stammdaten an. ``ueberspringe_aktuelle`` (Default
    True) ueberspringt Positionen, fuer die wir den Cache-Eintrag
    juenger als 24 h haben.

    Synchron – kann bei vielen Positionen einige Minuten dauern.
    """
    head = bestellung_holen(bestellung_rec_id)
    if not head:
        return {'ok': False, 'msg': 'Bestellung nicht gefunden.'}
    lief_rec_id = head.get('LIEF_REC_ID')
    pos = head.get('positionen') or []
    if not pos:
        return {'ok': False, 'msg': 'Bestellung hat keine Positionen.'}

    n_total = len(pos)
    n_ok    = 0
    n_skip  = 0
    n_err   = 0
    fehler_liste: list[str] = []
    from datetime import datetime, timedelta
    schwelle = datetime.now() - timedelta(hours=24)

    for p in pos:
        artnr = (p.get('ARTIKEL_NR_LIEF') or '').strip()
        if not artnr:
            n_skip += 1
            continue
        if ueberspringe_aktuelle:
            cached = lief_artikel_holen(lief_rec_id, artnr)
            cached_at = cached and cached.get('ABGEFRAGT_AT')
            if cached_at and cached_at >= schwelle and (cached.get('BARCODE_STUECK')
                                                         or cached.get('BEZEICHNUNG')):
                n_skip += 1
                continue
        res = lief_artikel_anreichern_position(lief_rec_id, artnr)
        if res.get('ok'):
            n_ok += 1
        else:
            n_err += 1
            fehler_liste.append(f"{artnr}: {res.get('msg', '?')[:120]}")

    return {
        'ok':         True,
        'total':      n_total,
        'aktualisiert': n_ok,
        'uebersprungen': n_skip,
        'fehler':     n_err,
        'fehler_liste': fehler_liste[:10],
    }


def cao_sync_plan(bestellung_rec_id: int) -> dict:
    """Generiert eine read-only Vorschau, was ein CAO-Sync (Phase 5/6)
    pro Position der Bestellung tun WUERDE. KEIN Schreibvorgang.

    Returns: ``{
      'ok': bool,
      'bestellung': {rec_id, lief_kuerzel, lief_bez, cao_lief_id,
                     bestell_nr, datum, gesamtsumme_netto, n_pos},
      'positionen': [
        {pos_rec_id, pos_nr, artikel_nr_lief, bezeichnung_lief,
         menge, preis_netto,
         match_quelle, cao_artikel_rec_id, cao_artikel_label,
         aktion: 'preis_verknuepfen' | 'artikel_anlegen' | 'in_cao' | 'offen',
         hinweise: list[str],
         artikel_insert: dict | None,         # falls 'artikel_anlegen'
         artikel_preis_insert: dict | None,   # immer wenn ARTIKEL bekannt/neu
        }, ...
      ],
      'aggregat': {n_match, n_neu_anlegen, n_in_cao, n_offen,
                   neue_artikel_pro_warengruppe: {...},
                   neue_preisverknuepfungen: int,
                   bestell_pos_zu_schreiben: int}
    }``
    """
    head = bestellung_holen(bestellung_rec_id)
    if not head:
        return {'ok': False, 'msg': 'Bestellung nicht gefunden.'}
    matches = cao_match_positionen(bestellung_rec_id)
    cao_lief_id = head.get('CAO_LIEF_ID')

    # MwSt → CAO STEUER_CODE
    def _steuer_code(mwst_pct):
        try:
            v = int(mwst_pct or 0)
        except (TypeError, ValueError):
            return None
        if v in (19,): return 1
        if v in (7,):  return 2
        if v == 0:     return 0
        return None

    pos_plan: list[dict] = []
    n_match = n_neu = n_in_cao = n_offen = 0
    neue_artikel = 0
    neue_preise  = 0
    fehlende_warengruppe = 0

    for m in matches:
        lief = m.get('lief_cache') or {}
        cao  = m.get('cao') or {}
        quelle = m.get('match_quelle') or 'kein'
        pos_status = m.get('pos_status') or 'neu'

        hinweise: list[str] = []
        artikel_insert  = None
        preis_insert    = None
        cao_label = ''

        # Warengruppe: bei Match aus CAO uebernehmen, sonst „klaeren"
        wg = cao.get('warengruppe') if cao else None

        if pos_status == 'in_cao':
            aktion = 'in_cao'
            n_in_cao += 1
            cao_label = (f'CAO #{cao.get("rec_id")}'
                         if cao else 'bereits eingebucht')
        elif quelle in ('barcode', 'lieferant', 'global', 'manuell'):
            aktion = 'preis_verknuepfen'
            n_match += 1
            cao_label = (f'CAO #{cao.get("rec_id")} '
                         f'{cao.get("matchcode") or cao.get("kas_name") or ""}')
            cache_lief = lief_artikel_holen(head.get('LIEF_REC_ID') or 0,
                                             m.get('artikel_nr_lief') or '')
            vpe_ek = (int(cache_lief['VPE_EK'])
                       if cache_lief and cache_lief.get('VPE_EK') else None)

            # ARTIKEL_PREIS-Aktion: Helper teilt Logik mit
            # cao_match_positionen. Bestehende „falsche"-BESTNUM-
            # Eintraege bleiben bewusst unangetastet; ihre Bereinigung
            # ist ein eigenstaendiger Teilprozess.
            aktion_info = _lief_preis_aktion(
                cao.get('rec_id'), cao_lief_id,
                neue_bestnum=m.get('artikel_nr_lief') or '',
                neuer_preis=m.get('preis_netto'),
                neue_vpe=vpe_ek,
            )
            preis_insert = {
                'tabelle':   'ARTIKEL_PREIS',
                'art':       aktion_info['art'],
                'grund':     aktion_info['grund'],
                'ARTIKEL_ID': cao.get('rec_id'),
                'ADRESS_ID':  cao_lief_id,
                'PREIS_TYP':  5,
                'PT2':        'EK',
                'BESTNUM':    m.get('artikel_nr_lief'),
                'PREIS':      m.get('preis_netto'),
                'VPE':        vpe_ek,
            }
            if aktion_info.get('alt'):
                preis_insert['_alt'] = aktion_info['alt']
            if aktion_info.get('andere_bestnums'):
                preis_insert['_andere_bestnums'] = aktion_info['andere_bestnums']
                hinweise.append(
                    f'CAO hat bei diesem Artikel bereits andere Lieferanten-'
                    f'Bestellnummern unter UTZ: '
                    f'{", ".join(aktion_info["andere_bestnums"])}. '
                    f'Diese werden NICHT veraendert – wir legen '
                    f'{m.get("artikel_nr_lief")!r} als zusaetzliche Zeile an. '
                    f'Bereinigung der Alt-Eintraege ist ein separater Prozess.')
            neue_preise += 1
            if not cao_lief_id:
                hinweise.append('Lieferant ohne CAO_LIEF_ID — '
                                'ARTIKEL_PREIS-Verknuepfung nicht moeglich; '
                                'Lieferant zuerst zuordnen.')
        elif quelle == 'mehrdeutig':
            aktion = 'offen'
            n_offen += 1
            cao_label = 'mehrdeutig — bitte manuell zuordnen'
            hinweise.append('Mehrere CAO-Treffer mit gleicher BESTNUM '
                            'unter verschiedenen Lieferanten gefunden.')
        elif quelle == 'unsicher':
            aktion = 'offen'
            n_offen += 1
            cao_label = (f'CAO #{cao.get("rec_id")} '
                         f'{cao.get("matchcode") or ""} (EAN-Konflikt)')
            hinweise.append('CAO-Artikel hat einen anderen Stueck-EAN als '
                            'der Lieferanten-Cache – wahrscheinlich nicht '
                            'derselbe Artikel. Bitte „neu anlegen" oder '
                            'manuell den richtigen Stamm zuordnen.')
        elif quelle == 'neu_anlegen' or pos_status == 'neu_anlegen':
            aktion = 'artikel_anlegen'
            n_neu += 1
            neue_artikel += 1
            # Defaults aus dem Lieferanten-Cache
            cache_lief = lief_artikel_holen(head.get('LIEF_REC_ID') or 0,
                                             m.get('artikel_nr_lief') or '')
            cl = cache_lief or {}
            artikel_insert = {
                'tabelle':       'ARTIKEL',
                'art':           'INSERT',
                'MATCHCODE':     (cl.get('BEZEICHNUNG')
                                   or m.get('bezeichnung_lief') or '').upper()[:255],
                'KAS_NAME':      cl.get('BEZEICHNUNG')
                                  or m.get('bezeichnung_lief') or '',
                'KURZNAME':      ((cl.get('BEZEICHNUNG')
                                   or m.get('bezeichnung_lief') or '')[:40]),
                'BARCODE':       cl.get('BARCODE_STUECK') or '',
                'BARCODE2':      cl.get('BARCODE_KT') or '',
                'EK_PREIS':      m.get('preis_netto') or cl.get('EK_NETTO'),
                'VK1B':          None,
                'STEUER_CODE':   _steuer_code(cl.get('MWST_PCT')),
                'WARENGRUPPE':   None,    # offen – User-Entscheidung
                'DEFAULT_LIEF_ID': cao_lief_id,
                'NO_VK_FLAG':    'N',
            }
            preis_insert = {
                'tabelle':       'ARTIKEL_PREIS',
                'art':           'INSERT (nach ARTIKEL-Anlage)',
                'ARTIKEL_ID':    '<neue ARTIKEL.REC_ID>',
                'ADRESS_ID':     cao_lief_id,
                'PREIS_TYP':     5,
                'PT2':           'EK',
                'BESTNUM':       m.get('artikel_nr_lief'),
                'PREIS':         m.get('preis_netto'),
                'VPE':           cl.get('VPE_EK'),
            }
            neue_preise += 1
            if artikel_insert['STEUER_CODE'] is None:
                hinweise.append(f'MwSt-Code unklar (mwst_pct={cl.get("MWST_PCT")})'
                                ' — Default 0 oder bitte klaeren.')
            if artikel_insert['WARENGRUPPE'] is None:
                hinweise.append('Warengruppe muss vor dem Anlegen zugeordnet werden.')
                fehlende_warengruppe += 1
            if not artikel_insert['BARCODE']:
                hinweise.append('Stueck-EAN fehlt — Stammdaten anreichern oder '
                                'manuell setzen.')
            if not cao_lief_id:
                hinweise.append('Lieferant ohne CAO_LIEF_ID — bitte ADRESSEN-Eintrag zuordnen.')
        else:
            # quelle == 'kein' und kein Status gesetzt
            aktion = 'offen'
            n_offen += 1
            cao_label = 'noch nicht zugeordnet'
            if m.get('vorschlaege'):
                hinweise.append('Bitte „CAO-Match prüfen" + einen Vorschlag '
                                'uebernehmen oder als „neu anlegen" markieren.')
            else:
                hinweise.append('Keine CAO-Treffer und keine Bezeichnungs-'
                                'Vorschlaege – Position als „neu anlegen" '
                                'markieren.')

        pos_plan.append({
            'pos_rec_id':            m.get('pos_rec_id'),
            'pos_nr':                m.get('pos_nr'),
            'artikel_nr_lief':       m.get('artikel_nr_lief'),
            'bezeichnung_lief':      m.get('bezeichnung_lief'),
            'menge':                 m.get('menge'),
            'preis_netto':           m.get('preis_netto'),
            'match_quelle':          quelle,
            'pos_status':            pos_status,
            'cao_artikel_rec_id':    (cao.get('rec_id') if cao else None),
            'cao_artikel_label':     cao_label,
            'aktion':                aktion,
            'hinweise':              hinweise,
            'artikel_insert':        artikel_insert,
            'artikel_preis_insert':  preis_insert,
        })

    bestell_aktion = {
        'tabelle': 'BESTELLUNG',
        'art':     'INSERT (Phase 6)',
        'ADRESS_ID':       cao_lief_id,
        'BEST_DAT':        head.get('EMAIL_DATUM'),
        'EXT_BESTELL_NR':  head.get('BESTELL_NR'),
        'GESAMTSUMME':     head.get('GESAMTSUMME_NETTO'),
        'ANZ_POSITIONEN':  len(pos_plan),
    }

    return {
        'ok': True,
        'bestellung': {
            'rec_id':            bestellung_rec_id,
            'lief_kuerzel':      head.get('LIEF_KUERZEL'),
            'lief_bez':          head.get('LIEF_BEZ'),
            'cao_lief_id':       cao_lief_id,
            'bestell_nr':        head.get('BESTELL_NR'),
            'email_datum':       head.get('EMAIL_DATUM'),
            'gesamtsumme_netto': float(head.get('GESAMTSUMME_NETTO') or 0),
        },
        'positionen': pos_plan,
        'aggregat': {
            'n_match':                  n_match,
            'n_neu_anlegen':            n_neu,
            'n_in_cao':                 n_in_cao,
            'n_offen':                  n_offen,
            'neue_artikel':             neue_artikel,
            'neue_preisverknuepfungen': neue_preise,
            'fehlende_warengruppe':     fehlende_warengruppe,
            'bestell_aktion':           bestell_aktion,
            'cao_lief_fehlt':           not bool(cao_lief_id),
        },
    }


def cao_sync_artikel_preis(bestellung_rec_id: int,
                            dry_run: bool = False,
                            ma_name: Optional[str] = None) -> dict:
    """Schreibt die Lieferantenpreis-Verknuepfungen einer Bestellung
    nach CAO (Phase 5a). Nur ``ARTIKEL_PREIS``-Tabelle, KEIN
    Stammartikel-Anlegen (Phase 5b).

    Pro Position mit aktiver Match-Quelle (barcode/lieferant/global/
    manuell) und Status ``neu`` oder ``matched``:

        UNVERAENDERT  → nichts schreiben, Status auf 'in_cao' setzen
        UPDATE        → UPDATE ARTIKEL_PREIS SET PREIS, VPE, GEAEND,
                        GEAEND_NAME (Match auf
                        ARTIKEL_ID + ADRESS_ID + PREIS_TYP=5 + BESTNUM)
        INSERT        → INSERT INTO ARTIKEL_PREIS – Defaults:
                        PT2='EK', PREIS_TYP=5, GUELTIG_VON=NULL,
                        VPE, GEAEND=NOW(), GEAEND_NAME=ma_name
        NICHT_MOEGLICH → Skip mit Begruendung

    Positionen mit Status ``in_cao``, ``neu_anlegen``, ``fehler`` oder
    Match-Quelle ``kein`` werden uebersprungen.

    Returns:
        ``{'ok', 'dry_run', 'updated', 'inserted', 'unchanged',
            'skipped', 'fehler': [{pos_nr, artnr, msg}], 'aktionen'}``
    """
    head = bestellung_holen(bestellung_rec_id)
    if not head:
        return {'ok': False, 'msg': 'Bestellung nicht gefunden.'}
    matches = cao_match_positionen(bestellung_rec_id)
    if not matches:
        return {'ok': False, 'msg': 'Bestellung hat keine Positionen.'}

    n_upd = n_ins = n_unch = n_skip = 0
    fehler: list[dict] = []
    aktionen: list[dict] = []

    for m in matches:
        pos_id = m.get('pos_rec_id')
        pos_nr = m.get('pos_nr')
        artnr  = m.get('artikel_nr_lief') or ''
        pa     = m.get('preis_aktion') or {}
        art    = pa.get('art')
        cao    = m.get('cao') or {}
        pos_status_alt = (m.get('pos_status') or 'neu').lower()

        if pos_status_alt in ('in_cao', 'neu_anlegen', 'fehler',
                               'manuell_klaeren'):
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': f'Status={pos_status_alt}'})
            continue
        if m.get('match_quelle') == 'kein':
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': 'kein CAO-Match'})
            continue
        if art == 'NICHT_MOEGLICH':
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': pa.get('grund') or 'nicht moeglich'})
            continue
        if art not in ('UNVERAENDERT', 'UPDATE', 'INSERT'):
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': 'unbekannte Aktion'})
            continue

        artikel_id = int(cao.get('rec_id') or 0)
        adress_id  = int(head.get('CAO_LIEF_ID') or 0)
        if not (artikel_id and adress_id) and art != 'UNVERAENDERT':
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': 'CAO-Lief- oder Artikel-ID fehlt'})
            continue

        preis = float(m.get('preis_netto') or 0)
        vpe   = m.get('vpe_lief')

        if dry_run:
            if art == 'UNVERAENDERT': n_unch += 1
            elif art == 'UPDATE':     n_upd += 1
            elif art == 'INSERT':     n_ins += 1
            aktionen.append({'pos_nr': pos_nr, 'art': art,
                              'artnr': artnr, 'cao_id': artikel_id,
                              'preis': preis, 'vpe': vpe,
                              'grund': pa.get('grund')})
            continue

        # Live-Schreiben
        try:
            if art == 'UNVERAENDERT':
                n_unch += 1
            elif art == 'UPDATE':
                # WHERE auf den echten PK (ohne BESTNUM-Filter), und
                # BESTNUM mit-aktualisieren — die Mail-BESTNUM ist die
                # aktuelle Quelle vom Lieferanten und ueberschreibt
                # einen evtl. abweichenden Alt-Wert in CAO.
                with get_db_transaction() as cur:
                    cur.execute("""
                        UPDATE ARTIKEL_PREIS
                           SET PREIS       = %s,
                               VPE         = %s,
                               BESTNUM     = %s,
                               GEAEND      = NOW(),
                               GEAEND_NAME = %s
                         WHERE ARTIKEL_ID = %s
                           AND ADRESS_ID  = %s
                           AND PREIS_TYP  = 5
                    """, (preis, vpe, artnr,
                          (ma_name or 'CAO-XT')[:100],
                          artikel_id, adress_id))
                n_upd += 1
            elif art == 'INSERT':
                with get_db_transaction() as cur:
                    cur.execute("""
                        INSERT INTO ARTIKEL_PREIS
                          (ARTIKEL_ID, ADRESS_ID, PREIS_TYP, PT2,
                           BESTNUM, PREIS, VPE,
                           GUELTIG_VON, GUELTIG_BIS,
                           GEAEND, GEAEND_NAME)
                        VALUES (%s, %s, 5, 'EK', %s, %s, %s,
                                NULL, NULL, NOW(), %s)
                    """, (artikel_id, adress_id, artnr, preis, vpe,
                          (ma_name or 'CAO-XT')[:100]))
                n_ins += 1
            with get_db_transaction() as cur:
                cur.execute("""
                    UPDATE XT_EINKAUF_BESTELLPOS
                       SET STATUS = 'in_cao'
                     WHERE REC_ID = %s
                """, (pos_id,))
            aktionen.append({'pos_nr': pos_nr, 'art': art,
                              'artnr': artnr, 'cao_id': artikel_id,
                              'preis': preis, 'vpe': vpe})
        except Exception as exc:
            log.exception('cao_sync_artikel_preis pos %s', pos_nr)
            fehler.append({'pos_nr': pos_nr, 'artnr': artnr,
                            'msg': str(exc)[:200]})
            try:
                with get_db_transaction() as cur:
                    cur.execute("""
                        UPDATE XT_EINKAUF_BESTELLPOS
                           SET STATUS = 'fehler',
                               ANMERKUNG = %s
                         WHERE REC_ID = %s
                    """, (f'CAO-Sync: {str(exc)[:240]}', pos_id))
            except Exception:
                pass

    # Bestellung-Status: nur wenn keine Position mehr offen ist
    if not dry_run:
        try:
            with get_db_transaction() as cur:
                cur.execute("""
                    SELECT COUNT(*) AS n_offen
                    FROM XT_EINKAUF_BESTELLPOS
                    WHERE BEST_REC_ID = %s
                      AND STATUS NOT IN ('in_cao', 'neu_anlegen',
                                          'fehler', 'manuell_klaeren')
                """, (bestellung_rec_id,))
                offen = int((cur.fetchone() or {'n_offen': 0})['n_offen'])
                if offen == 0:
                    cur.execute("""
                        UPDATE XT_EINKAUF_BESTELLUNG
                           SET STATUS = 'in_cao'
                         WHERE REC_ID = %s
                    """, (bestellung_rec_id,))
        except Exception as exc:
            log.warning('Bestellung-Status-Update %s: %s',
                        bestellung_rec_id, exc)

    return {
        'ok':        True,
        'dry_run':   dry_run,
        'updated':   n_upd,
        'inserted':  n_ins,
        'unchanged': n_unch,
        'skipped':   n_skip,
        'fehler':    fehler,
        'aktionen':  aktionen,
    }


def position_zuordnen(pos_rec_id: int,
                      cao_artikel_rec_id: Optional[int] = None,
                      neu_anlegen: bool = False,
                      manuell_klaeren: bool = False,
                      anmerkung: Optional[str] = None,
                      ma_id: Optional[int] = None) -> dict:
    """Manuelle Zuordnung einer Bestellposition.

    Modi:
        cao_artikel_rec_id != None  → STATUS='matched', ARTIKEL_REC_ID
        neu_anlegen=True            → STATUS='neu_anlegen' (Phase 5b
                                       wird Artikel anlegen)
        manuell_klaeren=True        → STATUS='manuell_klaeren' (kein
                                       Auto-Sync; Lieferant kontaktieren,
                                       Stammdaten manuell ergaenzen)
        sonst                       → Reset auf STATUS='neu'

    Schreibt nur in XT-Tabellen, NICHT in CAO.
    """
    if cao_artikel_rec_id is not None:
        new_status = 'matched'
        artrec = int(cao_artikel_rec_id)
    elif neu_anlegen:
        new_status = 'neu_anlegen'
        artrec = None
    elif manuell_klaeren:
        new_status = 'manuell_klaeren'
        artrec = None
    else:
        new_status = 'neu'
        artrec = None
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                UPDATE XT_EINKAUF_BESTELLPOS
                   SET ARTIKEL_REC_ID = %s,
                       STATUS         = %s,
                       ANMERKUNG      = COALESCE(%s, ANMERKUNG)
                 WHERE REC_ID = %s
            """, (artrec, new_status, anmerkung, int(pos_rec_id)))
            if cur.rowcount == 0:
                return {'ok': False, 'msg': 'Position nicht gefunden.'}
        return {'ok': True, 'status': new_status,
                'artikel_rec_id': artrec}
    except Exception as exc:
        log.exception('position_zuordnen %s', pos_rec_id)
        return {'ok': False, 'msg': str(exc)}


def _lief_preis_aktion(cao_artikel_rec_id: Optional[int],
                        cao_lief_id: Optional[int],
                        neue_bestnum: str,
                        neuer_preis: Optional[float],
                        neue_vpe: Optional[int]) -> dict:
    """Berechnet die ARTIKEL_PREIS-Aktion fuer einen Match.

    Returns: dict mit
        art:        'UNVERAENDERT' | 'UPDATE' | 'INSERT' | 'NICHT_MOEGLICH'
        grund:      lokalisierter Klartext fuers UI
        alt:        {BESTNUM, PREIS, VPE} | None
        andere_bestnums: list[str]   – Legacy-Feld, immer leer (siehe
                                       Hinweis unten).

    DB-Constraint: ARTIKEL_PREIS hat den Primary Key
    (ARTIKEL_ID, ADRESS_ID, PREIS_TYP) — die ``BESTNUM`` ist NICHT
    Teil des PKs. Pro (Artikel, Lieferant, Preis-Typ=5) gibt es also
    GENAU EINEN Eintrag. Wir matchen daher auf den PK und ueber-
    schreiben bei abweichender BESTNUM — die Lieferanten-Mail ist
    immer die frische Quelle und der CAO-Stand wird mit ihr in
    Einklang gebracht. Frueher hatte diese Funktion auf BESTNUM
    mit-gefiltert und bei Abweichung INSERT empfohlen — das fuehrte
    in 27 Positionen zu „Duplicate entry"-Fehlern, weil die DB den
    zweiten Eintrag unter gleicher PK-Tripel ablehnt.
    """
    if not (cao_artikel_rec_id and cao_lief_id):
        # Ohne Lief-Verknuepfung kann der Sync den Eintrag nicht setzen
        if not cao_artikel_rec_id:
            return {'art': 'NICHT_MOEGLICH', 'grund': 'kein CAO-Artikel',
                    'alt': None, 'andere_bestnums': []}
        return {'art': 'NICHT_MOEGLICH',
                'grund': 'Lieferant ohne CAO_LIEF_ID — '
                          'Verknüpfung erst nach Adress-Zuordnung möglich',
                'alt': None, 'andere_bestnums': []}

    bestnum = (neue_bestnum or '').strip()
    existing = None
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT BESTNUM, PREIS, VPE
                FROM ARTIKEL_PREIS
                WHERE ARTIKEL_ID = %s
                  AND ADRESS_ID  = %s
                  AND PREIS_TYP  = 5
            """, (int(cao_artikel_rec_id), int(cao_lief_id)))
            existing = cur.fetchone()
    except Exception as exc:
        log.warning('_lief_preis_aktion %s: %s', cao_artikel_rec_id, exc)
        return {'art': 'NICHT_MOEGLICH', 'grund': f'DB-Fehler: {exc}',
                'alt': None, 'andere_bestnums': []}

    if existing:
        alt_bestnum = (existing.get('BESTNUM') or '').strip()
        alt_preis   = float(existing.get('PREIS') or 0)
        alt_vpe     = existing.get('VPE')
        diff_preis   = abs((neuer_preis or 0) - alt_preis)
        diff_vpe     = (neue_vpe or 0) != (int(alt_vpe) if alt_vpe else 0)
        diff_bestnum = bestnum != alt_bestnum
        if diff_preis < 0.0001 and not diff_vpe and not diff_bestnum:
            return {
                'art': 'UNVERAENDERT',
                'grund': f'Eintrag mit BESTNUM {bestnum} und EK '
                         f'{alt_preis:.4f} € ist bereits gepflegt.',
                'alt': dict(existing),
                'andere_bestnums': [],
            }
        teile = []
        if diff_preis >= 0.0001:
            teile.append(f'EK {alt_preis:.4f} → {neuer_preis or 0:.4f} €')
        if diff_vpe:
            teile.append(f'VPE {alt_vpe} → {neue_vpe}')
        if diff_bestnum:
            teile.append(f'BESTNUM {alt_bestnum!r} → {bestnum!r}')
        return {
            'art': 'UPDATE',
            'grund': 'Bestehender Eintrag wird aktualisiert: '
                     + ', '.join(teile) + '.',
            'alt': dict(existing),
            'andere_bestnums': [],
        }

    # Kein Eintrag → INSERT
    return {
        'art': 'INSERT',
        'grund': ('Bisher kein Lieferantenpreis vom aktuellen '
                  'Lieferanten hinterlegt. Neue Zeile wird angelegt.'),
        'alt': None,
        'andere_bestnums': [],
    }


def cao_match_positionen(rec_id: int) -> list[dict]:
    """Read-only-Vorschau: pro Position der Bestellung pruefen, ob in CAO
    schon ein passender Artikel hinterlegt ist.

    Match-Strategie:
      1. Wenn der Lieferant einen ``CAO_LIEF_ID`` hat: in
         ``ARTIKEL_PREIS`` nach ``PREIS_TYP=5 AND ADRESS_ID=<lief>
         AND PT2=<UTZ-ArtNr>`` suchen → eindeutiger Treffer (Lieferanten-
         spezifisch, „enger" Match).
      2. Fallback ohne Lieferanten-Filter: ``PREIS_TYP=5 AND PT2=...``.
         Mehrere Treffer moeglich → wird als ``mehrdeutig`` markiert.
      3. Kein Match → Position muss neu angelegt werden.

    Liefert pro Position ein dict mit::

        {
          'pos_rec_id', 'pos_nr', 'artikel_nr_lief', 'bezeichnung_lief',
          'menge', 'preis_netto', 'zeilen_betrag',
          'match_quelle': 'lieferant' | 'global' | 'mehrdeutig' | 'kein',
          'cao': {  # nur wenn match_quelle != 'kein'
            'rec_id', 'artnum', 'matchcode', 'kas_name', 'warengruppe',
            'steuer_code', 'ek_preis', 'vk5b', 'lager', 'aktiv'
          } | None,
          'ek_diff':  float | None,    # NEUER_EK - CAO_EK
          'ek_diff_pct': float | None, # in % vom CAO-EK
        }
    """
    head = bestellung_holen(rec_id)
    if not head:
        return []

    cao_lief = head.get('CAO_LIEF_ID')
    out: list[dict] = []
    for p in head.get('positionen') or []:
        artnr = (p.get('ARTIKEL_NR_LIEF') or '').strip()
        if not artnr:
            out.append({
                'pos_rec_id':       p.get('REC_ID'),
                'pos_nr':           p.get('POS_NR'),
                'artikel_nr_lief':  None,
                'bezeichnung_lief': p.get('BESCHREIBUNG_LIEF'),
                'menge':            float(p.get('MENGE') or 0),
                'preis_netto':      float(p.get('PREIS_NETTO') or 0),
                'zeilen_betrag':    float(p.get('ZEILEN_BETRAG') or 0),
                'match_quelle':     'kein',
                'cao':              None,
                'ek_diff':          None,
                'ek_diff_pct':      None,
            })
            continue

        cao_treffer: Optional[dict] = None
        match_quelle = 'kein'

        # Cache-Eintrag des Lieferanten-Artikels (kann Barcode liefern)
        lief_cache = lief_artikel_holen(head.get('LIEF_REC_ID') or 0, artnr) \
                     if head.get('LIEF_REC_ID') else None
        barcode_stk = (lief_cache or {}).get('BARCODE_STUECK') or ''
        barcode_kt  = (lief_cache or {}).get('BARCODE_KT') or ''

        # Manuelle User-Zuordnung hat hoechste Prioritaet.
        man_status = (p.get('STATUS') or '').lower()
        man_rec    = p.get('ARTIKEL_REC_ID')
        if man_status == 'manuell_klaeren':
            match_quelle = 'manuell_klaeren'
        elif man_status == 'neu_anlegen':
            match_quelle = 'neu_anlegen'
        elif man_rec:
            try:
                with get_db() as cur:
                    cur.execute("""
                        SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME,
                               a.KURZNAME, a.WARENGRUPPE, a.STEUER_CODE,
                               a.EK_PREIS, a.VK5B, a.MENGE_AKT, a.NO_VK_FLAG,
                               a.USERFELD_02
                        FROM ARTIKEL a WHERE a.REC_ID = %s
                    """, (int(man_rec),))
                    row = cur.fetchone()
                if row:
                    cao_treffer = row
                    match_quelle = 'manuell'
            except Exception as exc:
                log.warning('manuell-Match Position %s: %s', artnr, exc)

        try:
            with get_db() as cur:
                # 0. Hoechste Prioritaet: Barcode-Match (Stueck-EAN gegen
                #    ARTIKEL.BARCODE/2/3). Eindeutigste Identifikation,
                #    deshalb vor allen anderen Pfaden.
                # TRIM beidseitig, weil CAO-Stammdaten oft Whitespace im
                # Barcode-Feld haben.
                if cao_treffer is None and barcode_stk:
                    bc = barcode_stk.strip()
                    cur.execute("""
                        SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME,
                               a.KURZNAME, a.WARENGRUPPE, a.STEUER_CODE,
                               a.EK_PREIS, a.VK5B, a.MENGE_AKT, a.NO_VK_FLAG,
                               a.USERFELD_02
                        FROM ARTIKEL a
                        WHERE TRIM(a.BARCODE)  = %s
                           OR TRIM(a.BARCODE2) = %s
                           OR TRIM(a.BARCODE3) = %s
                        ORDER BY (a.NO_VK_FLAG = 'N') DESC, a.REC_ID
                        LIMIT 1
                    """, (bc, bc, bc))
                    row = cur.fetchone()
                    if row:
                        cao_treffer = row
                        match_quelle = 'barcode'

                # 1. Enger Match (Lieferanten-spezifisch)
                if cao_treffer is None and cao_lief:
                    cur.execute("""
                        SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME,
                               a.KURZNAME, a.WARENGRUPPE, a.STEUER_CODE,
                               a.EK_PREIS, a.VK5B, a.MENGE_AKT, a.NO_VK_FLAG,
                               a.USERFELD_02
                        FROM ARTIKEL_PREIS ap
                        JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID
                        WHERE ap.PREIS_TYP = 5
                          AND ap.BESTNUM = %s
                          AND ap.ADRESS_ID = %s
                        ORDER BY ap.GUELTIG_VON DESC
                        LIMIT 1
                    """, (artnr, cao_lief))
                    row = cur.fetchone()
                    if row:
                        cao_treffer = row
                        match_quelle = 'lieferant'

                # 2. Globaler Fallback
                if cao_treffer is None:
                    cur.execute("""
                        SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME,
                               a.KURZNAME, a.WARENGRUPPE, a.STEUER_CODE,
                               a.EK_PREIS, a.VK5B, a.MENGE_AKT, a.NO_VK_FLAG,
                               a.USERFELD_02,
                               (SELECT COUNT(*) FROM ARTIKEL_PREIS x
                                WHERE x.PREIS_TYP = 5 AND x.BESTNUM = %s
                               ) AS n_treffer
                        FROM ARTIKEL_PREIS ap
                        JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID
                        WHERE ap.PREIS_TYP = 5 AND ap.BESTNUM = %s
                        ORDER BY ap.GUELTIG_VON DESC
                        LIMIT 1
                    """, (artnr, artnr))
                    row = cur.fetchone()
                    if row:
                        cao_treffer = row
                        match_quelle = ('mehrdeutig'
                                        if int(row.get('n_treffer') or 1) > 1
                                        else 'global')
        except Exception as exc:
            log.warning("cao_match Position %s: %s", artnr, exc)

        # Barcode-Konflikt-Check fuer 'global'/'mehrdeutig': wenn der
        # Lief-Cache eine Stueck-EAN hat und der gefundene CAO-Artikel
        # andere Barcodes hat, ist der Match wackelig – wir markieren
        # ihn als 'unsicher' und zeigen ihn als gelbe Pille.
        if (cao_treffer and barcode_stk
                and match_quelle in ('global', 'mehrdeutig')):
            if _barcode_konflikt(barcode_stk, cao_treffer.get('REC_ID')):
                match_quelle = 'unsicher'

        cao_block = None
        ek_diff = None
        ek_diff_pct = None
        if cao_treffer:
            cao_ek = float(cao_treffer.get('EK_PREIS') or 0)
            neuer_ek = float(p.get('PREIS_NETTO') or 0)
            ek_diff = neuer_ek - cao_ek if cao_ek else None
            if cao_ek > 0 and ek_diff is not None:
                ek_diff_pct = (ek_diff / cao_ek) * 100.0
            cao_block = {
                'rec_id':     cao_treffer.get('REC_ID'),
                'artnum':     cao_treffer.get('ARTNUM'),
                'matchcode':  cao_treffer.get('MATCHCODE'),
                'kas_name':   (cao_treffer.get('KAS_NAME')
                                or cao_treffer.get('KURZNAME')
                                or cao_treffer.get('MATCHCODE')),
                'warengruppe': cao_treffer.get('WARENGRUPPE'),
                'steuer_code': cao_treffer.get('STEUER_CODE'),
                'ek_preis':    cao_ek,
                'vk5b':        float(cao_treffer.get('VK5B') or 0),
                'lager':       float(cao_treffer.get('MENGE_AKT') or 0),
                'aktiv':       (cao_treffer.get('NO_VK_FLAG') != 'Y'
                                and not (cao_treffer.get('USERFELD_02') or '').strip()),
            }

        # Bei „kein"-Treffer: Bezeichnungs-Vorschlaege liefern.
        # Verwendet die saubere Cache-Bezeichnung (falls vorhanden) und
        # filtert via Stueck-EAN: CAO-Artikel mit anderem Barcode werden
        # explizit verworfen (waere kein gleicher Artikel mehr).
        vorschlaege: list[dict] = []
        if match_quelle == 'kein':
            bez_fuer_suche = ((lief_cache or {}).get('BEZEICHNUNG')
                               or p.get('BESCHREIBUNG_LIEF') or '')
            try:
                vorschlaege = cao_artikel_vorschlag(
                    bez_fuer_suche,
                    cao_lief_id=cao_lief, limit=3,
                    ausschluss_barcode=(barcode_stk or '').strip())
            except Exception as exc:
                log.warning("Vorschlag fuer Pos %s: %s", artnr, exc)
                vorschlaege = []

            # Aufwertung: wenn ein Vorschlag den IDENTISCHEN Stueck-EAN
            # hat, ist er de facto ein Barcode-Match (der direkte
            # Barcode-Pfad weiter oben hat ihn vermutlich verfehlt –
            # z.B. weil das Bezeichnungs-Token-Match anders sortiert
            # oder weil Whitespace im Barcode-Feld inzwischen anders
            # liegt). Wir nehmen den ersten EAN-Match-Vorschlag und
            # erheben ihn zu match_quelle='barcode'.
            if barcode_stk and vorschlaege:
                ean_match = next(
                    (v for v in vorschlaege if v.get('ean_match')), None)
                if ean_match:
                    try:
                        with get_db() as cur:
                            cur.execute("""
                                SELECT a.REC_ID, a.ARTNUM, a.MATCHCODE,
                                       a.KAS_NAME, a.KURZNAME, a.WARENGRUPPE,
                                       a.STEUER_CODE, a.EK_PREIS, a.VK5B,
                                       a.MENGE_AKT, a.NO_VK_FLAG, a.USERFELD_02
                                FROM ARTIKEL a WHERE a.REC_ID = %s
                            """, (int(ean_match['rec_id']),))
                            row = cur.fetchone()
                        if row:
                            cao_treffer = row
                            match_quelle = 'barcode'
                            vorschlaege = []
                    except Exception as exc:
                        log.warning("EAN-Vorschlag-Aufwertung %s: %s",
                                    artnr, exc)

        # Lieferanten-Stammdaten aus dem Cache (fuer Bild + Barcode-Anzeige)
        lief_block = None
        vpe_lief = None
        if lief_cache:
            bild_lokal = lief_cache.get('BILD_LOKAL') or ''
            lief_block = {
                'bezeichnung':     lief_cache.get('BEZEICHNUNG'),
                'barcode_stueck':  lief_cache.get('BARCODE_STUECK'),
                'barcode_kt':      lief_cache.get('BARCODE_KT'),
                'bild_url':        (f'/produktbilder/{bild_lokal}'
                                     if bild_lokal else
                                     (lief_cache.get('BILD_URL') or '')),
                'bild_lokal':      bool(bild_lokal),
                'verfuegbarkeit':  lief_cache.get('VERFUEGBARKEIT'),
                'vpe_ek':          lief_cache.get('VPE_EK'),
            }
            try:
                vpe_lief = (int(lief_cache['VPE_EK'])
                             if lief_cache.get('VPE_EK') else None)
            except (TypeError, ValueError):
                vpe_lief = None

        # ARTIKEL_PREIS-Aktion-Vorschau bei matchenden Positionen
        preis_aktion = None
        if cao_block and match_quelle in ('barcode', 'lieferant', 'global',
                                            'manuell'):
            preis_aktion = _lief_preis_aktion(
                cao_block.get('rec_id'), cao_lief,
                neue_bestnum=artnr,
                neuer_preis=float(p.get('PREIS_NETTO') or 0),
                neue_vpe=vpe_lief,
            )

        # Bezeichnung: bevorzugt aus dem Lief-Cache (saubere
        # UTZ-API-Bezeichnung), Fallback auf die Email-Bezeichnung
        # (die oft Encoding-Fehler ?-statt-Umlaut hat).
        cache_bez = (lief_cache or {}).get('BEZEICHNUNG') or ''
        email_bez = p.get('BESCHREIBUNG_LIEF') or ''
        bez_aktiv = cache_bez.strip() or email_bez.strip()

        # WARENGRUPPE-Vorschlag fuer neu-anzulegende Positionen
        # (Phase 5b). Nur wenn die Vorschlags-Liste konsistent ist
        # (alle Vorschlaege haben dieselbe WG), wird der Wert als
        # Vorschlag gemeldet — der User muss bestaetigen.
        wg_vorschlag_id = None
        if vorschlaege and not cao_block:
            wgs = {v.get('warengruppe') for v in vorschlaege
                    if v.get('warengruppe')}
            if len(wgs) == 1:
                wg_vorschlag_id = next(iter(wgs))

        out.append({
            'pos_rec_id':       p.get('REC_ID'),
            'pos_nr':           p.get('POS_NR'),
            'artikel_nr_lief':  artnr,
            'bezeichnung_lief': bez_aktiv,
            'bezeichnung_email': email_bez,
            'bezeichnung_cache': cache_bez,
            'menge':            float(p.get('MENGE') or 0),
            'preis_netto':      float(p.get('PREIS_NETTO') or 0),
            'zeilen_betrag':    float(p.get('ZEILEN_BETRAG') or 0),
            'pos_status':       p.get('STATUS') or 'neu',
            'match_quelle':     match_quelle,
            'cao':              cao_block,
            'ek_diff':          ek_diff,
            'ek_diff_pct':      ek_diff_pct,
            'vorschlaege':      vorschlaege,
            'lief_cache':       lief_block,
            'vpe_lief':         vpe_lief,
            'preis_aktion':     preis_aktion,
            # Stammdaten-Vollstaendigkeits-Check fuer Phase 5b:
            # Position kann nur dann sauber als neuer CAO-Artikel
            # angelegt werden, wenn der Lieferanten-Cache zumindest
            # Bezeichnung + Stueck-EAN liefert. Sonst „manuell klaeren".
            'kann_angelegt_werden': bool(
                lief_cache
                and (lief_cache.get('BEZEICHNUNG') or '').strip()
                and (lief_cache.get('BARCODE_STUECK') or '').strip()
            ),
            # Phase 5b: User-gewaehlte WARENGRUPPE_ID (NULL bis
            # explizit gesetzt). + Vorschlag aus Match-Hits.
            'warengruppe_id':    p.get('WARENGRUPPE_ID'),
            'wg_vorschlag_id':   wg_vorschlag_id,
        })
    return out


def bestellung_holen(rec_id: int) -> Optional[dict]:
    """Liefert Header + Positionen einer Bestellung."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT b.*,
                       l.KUERZEL    AS LIEF_KUERZEL,
                       l.BEZEICHNUNG AS LIEF_BEZ,
                       l.CAO_LIEF_ID AS CAO_LIEF_ID
                FROM XT_EINKAUF_BESTELLUNG b
                JOIN XT_EINKAUF_LIEFERANT l ON l.REC_ID = b.LIEF_REC_ID
                WHERE b.REC_ID = %s
            """, (rec_id,))
            head = cur.fetchone()
            if not head:
                return None
            cur.execute("""
                SELECT REC_ID, POS_NR, ARTIKEL_NR_LIEF, BESCHREIBUNG_LIEF,
                       MENGE, PREIS_NETTO, ZEILEN_BETRAG, ARTIKEL_REC_ID,
                       WARENGRUPPE_ID, STATUS, ANMERKUNG
                FROM XT_EINKAUF_BESTELLPOS
                WHERE BEST_REC_ID = %s
                ORDER BY POS_NR
            """, (rec_id,))
            head['positionen'] = list(cur.fetchall() or [])
        return head
    except Exception as exc:
        log.warning("bestellung_holen(%s): %s", rec_id, exc)
        return None


# ── IMAP (Legacy-Pfad – aktuell nicht im UI) ────────────────────────────────

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


# ── Poller-Heartbeat (Phase 2b) ──────────────────────────────────────────────

def poller_status_lesen() -> Optional[dict]:
    """Liefert die Heartbeat-Zeile oder None (Daemon noch nie gelaufen)."""
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT * FROM XT_EINKAUF_POLLER_STATUS WHERE REC_ID = 1")
            return cur.fetchone()
    except Exception as exc:
        log.warning("poller_status_lesen: %s", exc)
        return None


def poller_status_schreiben(*, gmail_ok: bool,
                            last_error: Optional[str],
                            neu_gefunden: int,
                            hostname: Optional[str]) -> None:
    """UPSERT der Single-Row Heartbeat. Bei Erfolg wird LAST_SUCCESS_AT
    aktualisiert; LAST_ERROR bleibt bis zum naechsten Erfolg stehen.
    """
    from datetime import datetime, timezone
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                INSERT INTO XT_EINKAUF_POLLER_STATUS
                  (REC_ID, LAST_RUN_AT, LAST_SUCCESS_AT, GMAIL_OK,
                   LAST_ERROR, ZYKLUS_COUNT, NEU_GEFUNDEN, HOSTNAME)
                VALUES (1, %s, %s, %s, %s, 1, %s, %s)
                ON DUPLICATE KEY UPDATE
                  LAST_RUN_AT     = VALUES(LAST_RUN_AT),
                  LAST_SUCCESS_AT = CASE WHEN VALUES(GMAIL_OK) = 1
                                          THEN VALUES(LAST_RUN_AT)
                                          ELSE LAST_SUCCESS_AT END,
                  GMAIL_OK        = VALUES(GMAIL_OK),
                  LAST_ERROR      = VALUES(LAST_ERROR),
                  ZYKLUS_COUNT    = ZYKLUS_COUNT + 1,
                  NEU_GEFUNDEN    = NEU_GEFUNDEN + VALUES(NEU_GEFUNDEN),
                  HOSTNAME        = VALUES(HOSTNAME)
            """, (jetzt, jetzt if gmail_ok else None,
                  1 if gmail_ok else 0,
                  (last_error or '')[:500] or None,
                  int(neu_gefunden), hostname))
    except Exception as exc:
        log.warning("poller_status_schreiben: %s", exc)


# ── Phase 5b: Stammartikel-Anlage in CAO ──────────────────────────────

def cao_warengruppen_baum() -> dict:
    """Liefert die CAO-WARENGRUPPEN als Baum + Flachliste (fuer UI).

    Returns::

        {
          'baum':  [ {id, name, kinder: [...], def_ekto, def_akto,
                      steuer_code, vk5_faktor}, ... ],
          'flach': [ {id, name, top_id, def_ekto, def_akto,
                      steuer_code, vk5_faktor}, ... ],
        }

    Sortierung: SORT-Spalte, dann NAME. Top-Level = TOP_ID = -1.
    """
    flach: list[dict] = []
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT ID, TOP_ID, NAME, DEF_EKTO, DEF_AKTO,
                       STEUER_CODE, VK1_FAKTOR, VK5_FAKTOR, SORT
                FROM WARENGRUPPEN
                ORDER BY TOP_ID, SORT, NAME
            """)
            for r in cur.fetchall() or []:
                flach.append({
                    'id':           int(r['ID']),
                    'top_id':       int(r['TOP_ID']) if r['TOP_ID'] is not None else -1,
                    'name':         r['NAME'] or '',
                    'def_ekto':     r['DEF_EKTO'],
                    'def_akto':     r['DEF_AKTO'],
                    'steuer_code':  int(r['STEUER_CODE']) if r['STEUER_CODE'] is not None else 0,
                    'vk1_faktor':   float(r['VK1_FAKTOR'] or 0),
                    'vk5_faktor':   float(r['VK5_FAKTOR'] or 0),
                })
    except Exception as exc:
        log.warning('cao_warengruppen_baum: %s', exc)
        return {'baum': [], 'flach': []}

    # Baum aufbauen: zuerst per ID indexieren, dann Kinder anhaengen.
    by_id = {n['id']: dict(n, kinder=[]) for n in flach}
    roots: list[dict] = []
    for n in flach:
        node = by_id[n['id']]
        if n['top_id'] == -1 or n['top_id'] not in by_id:
            roots.append(node)
        else:
            by_id[n['top_id']]['kinder'].append(node)
    return {'baum': roots, 'flach': flach}


def position_warengruppe_setzen(pos_rec_id: int,
                                 warengruppe_id: Optional[int]) -> dict:
    """Setzt die WARENGRUPPE_ID einer Bestellposition (Phase 5b).

    ``warengruppe_id=None`` loescht die Auswahl wieder. Validiert die
    WG-ID gegen ``WARENGRUPPEN`` (verhindert Tippfehler/Phantom-IDs).
    """
    try:
        with get_db_transaction() as cur:
            if warengruppe_id is not None:
                cur.execute("SELECT ID FROM WARENGRUPPEN WHERE ID = %s",
                            (int(warengruppe_id),))
                if not cur.fetchone():
                    return {'ok': False,
                            'msg': f'Warengruppe {warengruppe_id} existiert nicht.'}
            cur.execute("""
                UPDATE XT_EINKAUF_BESTELLPOS
                   SET WARENGRUPPE_ID = %s
                 WHERE REC_ID = %s
            """, (int(warengruppe_id) if warengruppe_id is not None else None,
                  int(pos_rec_id)))
            if cur.rowcount == 0:
                return {'ok': False, 'msg': 'Position nicht gefunden.'}
        return {'ok': True, 'warengruppe_id': warengruppe_id}
    except Exception as exc:
        log.exception('position_warengruppe_setzen %s', pos_rec_id)
        return {'ok': False, 'msg': str(exc)}


# ── ARTNUM-Vergabe via REGISTRY ──────────────────────────────────────

def _next_artnum(cur) -> str:
    """Holt die naechste ARTNUM aus dem REGISTRY-Counter und erhoeht ihn.

    REGISTRY-Eintrag fuer ARTIKELNUMMER:
      MAINKEY='MAIN\\NUMBERS', NAME='ARTIKELNUMMER',
      VAL_INT=98 (QUELLE-Code), VAL_INT2=<letzte vergebene Nummer>,
      VAL_CHAR='000000' (Padding-Format, hier 6-stellig, fuehrende Nullen).

    Aufruf MUSS innerhalb einer Transaktion erfolgen, damit zwei
    parallele Insert-Threads nicht dieselbe Nummer bekommen.
    """
    cur.execute("""
        SELECT VAL_INT2, VAL_CHAR
        FROM REGISTRY
        WHERE MAINKEY = 'MAIN\\\\NUMBERS' AND NAME = 'ARTIKELNUMMER'
        FOR UPDATE
    """)
    row = cur.fetchone()
    if not row:
        raise RuntimeError(
            "REGISTRY-Eintrag MAIN\\NUMBERS / ARTIKELNUMMER fehlt — "
            "CAO Faktura sollte ihn beim ersten Start anlegen."
        )
    naechste = int(row['VAL_INT2'] or 0) + 1
    pad = (row['VAL_CHAR'] or '000000')
    # Padding-Format: Anzahl '0'-Zeichen ergibt die Stellenanzahl
    n_stellen = pad.count('0') if pad.count('0') > 0 else 6
    artnum = f"{naechste:0{n_stellen}d}"
    cur.execute("""
        UPDATE REGISTRY
        SET VAL_INT2 = %s
        WHERE MAINKEY = 'MAIN\\\\NUMBERS' AND NAME = 'ARTIKELNUMMER'
    """, (naechste,))
    return artnum


# ── ARTIKEL_LOG-CONCAT_WS (aus cao_faktura.exe) ──────────────────────

# Reverse-engineered aus cao_faktura.exe, Offset 0x1300696. Format-
# Version 'V1', 41 Felder. Diese Formel reproduziert exakt das, was
# CAO selbst beim Schreiben in ARTIKEL_LOG als HASHSTRING benutzt.
_ARTIKEL_LOG_HASHSTRING_SQL = """
SELECT CONCAT_WS('|',
   'V1', REC_ID, ARTIKEL_ID, IFNULL(ARTNUM,'-'), IFNULL(EK_PREIS,0),
   IFNULL(VK1,0), IFNULL(VK2,0), IFNULL(VK3,0), IFNULL(VK4,0),
   IFNULL(VK5,0), SHOP_PREIS_LISTE, VPE, VPE_EK, PR_EINHEIT,
   INVENTUR_WERT, PROVIS_PROZ, STEUER_CODE, ALTTEIL_FLAG, ME,
   IFNULL(ERLOES_KTO,0), IFNULL(AUFW_KTO,0), INFO, GEAEND, GEAND_NAME,
   IFNULL(KURZNAME,''),
   IFNULL(AKTION_VK1,0), IFNULL(AKTION_VK2,0), IFNULL(AKTION_VK3,0),
   IFNULL(AKTION_VK4,0), IFNULL(AKTION_VK5,0),
   IFNULL(AKTION_VON,0), IFNULL(AKTION_BIS,0),
   IFNULL(STAFEL_MENGE2,0), IFNULL(STAFEL_PROZ2,0),
   IFNULL(STAFEL_MENGE3,0), IFNULL(STAFEL_PROZ3,0),
   IFNULL(STAFEL_MENGE4,0), IFNULL(STAFEL_PROZ4,0),
   IFNULL(STAFEL_MENGE5,0), IFNULL(STAFEL_PROZ5,0),
   IFNULL(STEUER_SATZ,0)
) AS HASHSTRING
FROM ARTIKEL_LOG WHERE REC_ID = %s
"""


def cao_sync_artikel(bestellung_rec_id: int,
                      dry_run: bool = False,
                      ma_id: Optional[int] = None,
                      ma_name: Optional[str] = None) -> dict:
    """Phase 5b: Legt Stammartikel in CAO an + ARTIKEL_LOG-Snapshot
    + XT_ARTIKEL_VK_KONTROLLE-Eintrag.

    Pro Position mit STATUS='neu_anlegen', WARENGRUPPE_ID gesetzt und
    Lief-Cache vollstaendig (BEZEICHNUNG + BARCODE_STUECK):

        1. ARTNUM aus REGISTRY-Counter holen + UPDATE
        2. WARENGRUPPE-Defaults laden (DEF_EKTO/AKTO, STEUER_CODE,
           VK5_FAKTOR)
        3. INSERT INTO ARTIKEL — Defaults aus WG, Daten aus
           Position + Lief-Cache, HASHSUM='$$' (CAO-Default)
        4. ARTIKEL_LOG-CONCAT_WS holen (V1-Formel von CAO)
        5. HASHSUM via cao_log_hashsum.compute('ARTIKEL_LOG', ...)
        6. INSERT INTO ARTIKEL_LOG mit XT-HASHSUM
        7. UPDATE XT_EINKAUF_BESTELLPOS: STATUS='matched',
           ARTIKEL_REC_ID=neue ID — damit der nachfolgende
           ARTIKEL_PREIS-Sync (Phase 5a) ihn als Match aufgreift
        8. XT_ARTIKEL_VK_KONTROLLE-Eintrag mit GRUND='neu' anlegen
           (User pflegt VK manuell nach)

    Positionen ohne WG_ID werden als FEHLER gemeldet (User soll erst
    waehlen). Positionen mit Lief-Cache-Luecken werden uebersprungen.

    Returns::

        {'ok': bool,
         'dry_run': bool,
         'angelegt': int,                # erfolgreiche Anlagen
         'uebersprungen': int,
         'fehler': [{pos_nr, artnr, msg}, ...],
         'aktionen': [...],              # detail-log
         'artikel_rec_ids': [int, ...]   # neu erzeugte ARTIKEL.REC_IDs
        }
    """
    from common import cao_log_hashsum  # lokaler Import (vermeidet Zyklus)
    from common import cao_hashsum as _cao_hashsum

    head = bestellung_holen(bestellung_rec_id)
    if not head:
        return {'ok': False, 'msg': 'Bestellung nicht gefunden.'}
    matches = cao_match_positionen(bestellung_rec_id)
    if not matches:
        return {'ok': False, 'msg': 'Bestellung hat keine Positionen.'}

    # Pre-Check: Salt fuer ARTIKEL_LOG MUSS gepflegt sein, sonst
    # bricht cao_log_hashsum.compute() pro Position mit SaltFehlt ab —
    # und der ARTIKEL-INSERT, der davor passiert, wuerde halb angelegt
    # bleiben (ARTIKEL existiert in CAO ohne XT-Hash + ohne Bestell-
    # positions-Verknuepfung). Lieber EINMAL frueh und klar abbrechen,
    # bevor irgendwas in CAO geschrieben wird.
    try:
        _cao_hashsum.get_salt(_cao_hashsum.KEY_ARTIKEL_LOG)
    except _cao_hashsum.SaltFehlt as exc:
        return {
            'ok': False,
            'msg': str(exc),
            'angelegt': 0,
            'uebersprungen': 0,
            'fehler': [],
            'aktionen': [],
            'artikel_rec_ids': [],
        }

    n_neu = n_skip = 0
    fehler: list[dict] = []
    aktionen: list[dict] = []
    neue_ids: list[int] = []

    # Cache: WARENGRUPPEN-Defaults pro WG_ID, einmal je Sync laden
    wg_defaults: dict[int, dict] = {}

    def _wg_defaults(cur, wg_id: int) -> Optional[dict]:
        if wg_id in wg_defaults:
            return wg_defaults[wg_id]
        cur.execute("""
            SELECT ID, NAME, DEF_EKTO, DEF_AKTO, STEUER_CODE,
                   VK1_FAKTOR, VK5_FAKTOR
            FROM WARENGRUPPEN WHERE ID = %s
        """, (wg_id,))
        wg_defaults[wg_id] = cur.fetchone()
        return wg_defaults[wg_id]

    # MWST-Saetze aus REGISTRY (MAIN\MWST/NAME='0','1','2',...) fuer
    # ARTIKEL_LOG.STEUER_SATZ (CAO speichert dort den prozentualen
    # Wert, nicht nur den Code).
    mwst_map: dict[int, float] = {}
    try:
        with get_db() as cur:
            cur.execute("""SELECT NAME, VAL_DOUBLE FROM REGISTRY
                           WHERE MAINKEY = 'MAIN\\\\MWST'
                             AND VAL_DOUBLE IS NOT NULL""")
            for r in cur.fetchall() or []:
                try:
                    mwst_map[int(r['NAME'])] = float(r['VAL_DOUBLE'])
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        log.warning('mwst-map laden: %s', exc)

    for m in matches:
        pos_id = m.get('pos_rec_id')
        pos_nr = m.get('pos_nr')
        artnr  = m.get('artikel_nr_lief') or ''
        pos_status = (m.get('pos_status') or 'neu').lower()

        # Nur Positionen mit explizitem 'neu_anlegen'-Auftrag
        if pos_status != 'neu_anlegen':
            n_skip += 1
            continue
        # Stammdaten muessen vorhanden sein
        if not m.get('kann_angelegt_werden'):
            n_skip += 1
            aktionen.append({'pos_nr': pos_nr, 'art': 'SKIP',
                              'grund': 'Lief-Cache unvollstaendig'})
            continue
        # Warengruppe muss gesetzt sein
        wg_id = m.get('warengruppe_id')
        if not wg_id:
            fehler.append({'pos_nr': pos_nr, 'artnr': artnr,
                           'msg': 'Warengruppe nicht gewaehlt'})
            n_skip += 1
            continue

        lief_block = m.get('lief_cache') or {}
        bez       = (lief_block.get('bezeichnung') or
                     m.get('bezeichnung_lief') or '')[:255]
        barcode_s = lief_block.get('barcode_stueck') or ''
        barcode_k = lief_block.get('barcode_kt') or ''
        ek_preis  = float(m.get('preis_netto') or 0)
        vpe_ek    = m.get('vpe_lief')

        try:
            with get_db_transaction() as cur:
                # 1. WG-Defaults laden
                wg = _wg_defaults(cur, int(wg_id))
                if not wg:
                    raise RuntimeError(f'Warengruppe {wg_id} verschwunden')

                # VK5: nur wenn Faktor > 0 setzen, sonst 0 lassen
                vk5_faktor = float(wg.get('VK5_FAKTOR') or 0)
                vk5 = round(ek_preis * (1 + vk5_faktor), 4) \
                       if vk5_faktor > 0 else 0

                # 2. ARTNUM holen (nur Live-Sync; Dry-Run liest nur)
                if dry_run:
                    cur.execute("""
                        SELECT VAL_INT2, VAL_CHAR FROM REGISTRY
                        WHERE MAINKEY='MAIN\\\\NUMBERS' AND NAME='ARTIKELNUMMER'
                    """)
                    row = cur.fetchone() or {}
                    naechste = int(row.get('VAL_INT2') or 0) + 1
                    pad = (row.get('VAL_CHAR') or '000000')
                    n_stellen = pad.count('0') if pad.count('0') > 0 else 6
                    artnum = f"{naechste:0{n_stellen}d}"
                    aktionen.append({
                        'pos_nr': pos_nr, 'art': 'DRY_RUN',
                        'artnum': artnum, 'wg_id': int(wg_id),
                        'wg_name': wg.get('NAME'),
                        'matchcode': bez,
                        'ek_preis': ek_preis, 'vk5': vk5,
                        'barcode': barcode_s,
                    })
                    n_neu += 1
                    continue

                artnum = _next_artnum(cur)

                # 3. ARTIKEL-INSERT
                cur.execute("""
                    INSERT INTO ARTIKEL
                      (ARTNUM, MATCHCODE, KAS_NAME, KURZNAME,
                       WARENGRUPPE, BARCODE, BARCODE2,
                       EK_PREIS, VK1, VK2, VK3, VK4, VK5,
                       VPE_EK, STEUER_CODE,
                       ERLOES_KTO, AUFW_KTO,
                       ERSTELLT, ERST_NAME)
                    VALUES
                      (%s, %s, %s, %s,
                       %s, %s, %s,
                       %s, 0, 0, 0, 0, %s,
                       %s, %s,
                       %s, %s,
                       NOW(), %s)
                """, (
                    artnum, bez, bez[:150], bez[:150],
                    int(wg_id),
                    barcode_s or None,
                    barcode_k or None,
                    ek_preis,
                    vk5,
                    int(vpe_ek) if vpe_ek else 1,
                    wg.get('STEUER_CODE') or 2,
                    wg.get('DEF_EKTO'),
                    wg.get('DEF_AKTO'),
                    (ma_name or 'XT-Einkauf')[:100],
                ))
                artikel_id = cur.lastrowid
                neue_ids.append(int(artikel_id))

                # 4. ARTIKEL_LOG-INSERT (HASHSUM zunaechst leer; wird in
                # Schritt 7 ueberschrieben)
                steuer_satz = mwst_map.get(int(wg.get('STEUER_CODE') or 0), 0.0)
                cur.execute("""
                    INSERT INTO ARTIKEL_LOG
                      (ARTIKEL_ID, ARTNUM, EK_PREIS,
                       VK1, VK2, VK3, VK4, VK5,
                       VPE, VPE_EK, PR_EINHEIT, INVENTUR_WERT, PROVIS_PROZ,
                       STEUER_CODE, ALTTEIL_FLAG, ME,
                       ERLOES_KTO, AUFW_KTO,
                       INFO, GEAEND, GEAND_NAME,
                       KURZNAME, STEUER_SATZ,
                       HASHSUM)
                    SELECT
                      a.REC_ID, a.ARTNUM, a.EK_PREIS,
                      a.VK1, a.VK2, a.VK3, a.VK4, a.VK5,
                      a.VPE, a.VPE_EK, a.PR_EINHEIT, a.INVENTUR_WERT, a.PROVIS_PROZ,
                      a.STEUER_CODE, a.ALTTEIL_FLAG,
                      IFNULL(m.BEZEICHNUNG, '-'),
                      a.ERLOES_KTO, a.AUFW_KTO,
                      'Artikel angelegt', NOW(), %s,
                      a.KURZNAME,
                      %s,
                      ''
                    FROM ARTIKEL a
                    LEFT JOIN MENGENEINHEIT m ON m.REC_ID = a.ME_ID
                    WHERE a.REC_ID = %s
                """, ((ma_name or 'XT-Einkauf')[:50], steuer_satz,
                       int(artikel_id)))
                log_rec_id = cur.lastrowid

                # 5. HASHSTRING aus dem frisch geschriebenen LOG-Eintrag holen
                cur.execute(_ARTIKEL_LOG_HASHSTRING_SQL, (log_rec_id,))
                hs_row = cur.fetchone()
                hashstring = (hs_row or {}).get('HASHSTRING') or ''

                # 6. Vorgaenger-HASHSUM (wenn vorhanden)
                cur.execute("""
                    SELECT HASHSUM FROM ARTIKEL_LOG
                    WHERE REC_ID < %s
                    ORDER BY REC_ID DESC LIMIT 1
                """, (log_rec_id,))
                prev_row = cur.fetchone()
                prev_hashsum = (prev_row or {}).get('HASHSUM')

                # 7. XT-HASHSUM berechnen + UPDATE
                neue_hashsum = cao_log_hashsum.compute(
                    table_name='ARTIKEL_LOG',
                    hashstring=hashstring,
                    previous_hashsum=prev_hashsum,
                )
                cur.execute("""
                    UPDATE ARTIKEL_LOG SET HASHSUM = %s WHERE REC_ID = %s
                """, (neue_hashsum, log_rec_id))

                # 8. XT_EINKAUF_BESTELLPOS aktualisieren — diese Position
                #    ist jetzt 'matched' und triggert den ARTIKEL_PREIS-
                #    Sync (Phase 5a) im Folgeschritt korrekt.
                cur.execute("""
                    UPDATE XT_EINKAUF_BESTELLPOS
                       SET ARTIKEL_REC_ID = %s, STATUS = 'matched'
                     WHERE REC_ID = %s
                """, (int(artikel_id), int(pos_id)))

                # 9. VK-Kontrolle-Eintrag (Erinnerung an User)
                cur.execute("""
                    INSERT INTO XT_ARTIKEL_VK_KONTROLLE
                      (ARTIKEL_REC_ID, GRUND, NEU_EK, QUELLE_BEST,
                       ANGELEGT_VON, ANMERKUNG)
                    VALUES (%s, 'neu', %s, %s, %s, %s)
                """, (int(artikel_id), ek_preis,
                      int(bestellung_rec_id), ma_id,
                      f'Phase 5b: angelegt ueber Bestellung '
                      f'{head.get("BESTELL_NR") or bestellung_rec_id} '
                      f'(Lief={head.get("LIEF_KUERZEL") or "?"}). '
                      f'VK5={vk5} (Faktor={vk5_faktor})'))

                aktionen.append({
                    'pos_nr': pos_nr, 'art': 'INSERT',
                    'artikel_rec_id': int(artikel_id),
                    'artnum': artnum, 'matchcode': bez,
                    'wg_id': int(wg_id), 'wg_name': wg.get('NAME'),
                    'ek_preis': ek_preis, 'vk5': vk5,
                    'log_rec_id': log_rec_id,
                })
                n_neu += 1

        except Exception as exc:
            log.exception('cao_sync_artikel pos %s', pos_id)
            fehler.append({'pos_nr': pos_nr, 'artnr': artnr,
                            'msg': str(exc)})
            # Position als 'fehler' markieren
            try:
                with get_db_transaction() as cur2:
                    cur2.execute("""
                        UPDATE XT_EINKAUF_BESTELLPOS
                           SET STATUS = 'fehler',
                               ANMERKUNG = CONCAT(IFNULL(ANMERKUNG,''),
                                                   '\nPhase 5b: ', %s)
                         WHERE REC_ID = %s
                    """, (str(exc)[:300], int(pos_id)))
            except Exception:
                pass

    return {
        'ok':              True,
        'dry_run':         dry_run,
        'angelegt':        n_neu,
        'uebersprungen':   n_skip,
        'fehler':          fehler,
        'aktionen':        aktionen,
        'artikel_rec_ids': neue_ids,
    }
