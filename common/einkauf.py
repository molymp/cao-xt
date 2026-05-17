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

from contextlib import contextmanager

from common.db import get_db, get_db_transaction
from common import konfig as _konfig
from common.cao_lock import cao_record_lock, LOCK_MOD_XT_EK_SYNC


@contextmanager
def _xt_ekbestell_sync_lock_tx(bestellung_rec_id: int):
    """Schreib-Transaktion für ``cao_sync_ekbestell`` mit Dorfkern-
    internem Lock auf der **Quell**-Bestellung (XT_EINKAUF_BESTELLUNG.
    REC_ID). Kein CAO-Lock: die Ziel-EKBESTELL.REC_ID existiert noch
    nicht und CAO kennt XT_*-Tabellen nicht. Zweck: zwei gleichzeitige
    Syncs derselben XT-Bestellung serialisieren (Check-then-Act-Schutz
    gegen Doppel-Anlage). Re-Check des Guards MUSS unter diesem Lock
    erfolgen.
    """
    with get_db_transaction() as cur:
        with cao_record_lock(cur, LOCK_MOD_XT_EK_SYNC,
                             int(bestellung_rec_id)):
            yield cur

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
                # Phase 5b-Verbesserung: EK_BEZUG_DEFAULT pro Lieferant.
                # 'STK' = Lieferant fakturiert pro Stueck (UTZ-Default),
                # 'VPE_EK' = pro Einkaufs-Verpackung (Karton/Kiste).
                # Sync rechnet beim Schreiben auf Stueck-EK um, damit
                # ARTIKEL.EK_PREIS und Faktor-Kalkulation konsistent
                # bleiben.
                ('EK_BEZUG_DEFAULT',
                 "ENUM('STK','VPE_EK') NOT NULL DEFAULT 'STK' "
                 "AFTER PARSER_KEY"),
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

            # Bild-Cache jetzt in CAO BINAERDATEN (BLOB) statt im
            # Filesystem. BILD_BINAER_ID = REC_ID in BINAERDATEN. Bei
            # Stammdaten-Match wird der Eintrag auf MODUL_ID=1020
            # (Artikel) umgetaggt — siehe common.binaerdaten. BILD_LOKAL
            # bleibt vorerst als Fallback bestehen.
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'XT_EINKAUF_LIEF_ARTIKEL'
                  AND COLUMN_NAME  = 'BILD_BINAER_ID'
            """)
            if int((cur.fetchone() or {}).get('n', 0)) == 0:
                cur.execute("ALTER TABLE XT_EINKAUF_LIEF_ARTIKEL "
                            "ADD COLUMN BILD_BINAER_ID INT UNSIGNED NULL "
                            "AFTER BILD_LOKAL, "
                            "ADD INDEX idx_bild_binaer (BILD_BINAER_ID)")

            # Phase 5b-Verbesserung: EK_BEZUG-Override pro Lief-Artikel.
            # NULL = nimm Lieferanten-Default (XT_EINKAUF_LIEFERANT.
            # EK_BEZUG_DEFAULT). Erlaubt Artikel-spezifische Abweichungen,
            # z.B. wenn UTZ einen einzelnen Bier-Karton-Preis schickt
            # obwohl Default 'STK' ist.
            cur.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'XT_EINKAUF_LIEF_ARTIKEL'
                  AND COLUMN_NAME  = 'EK_BEZUG'
            """)
            if int((cur.fetchone() or {}).get('n', 0)) == 0:
                cur.execute("ALTER TABLE XT_EINKAUF_LIEF_ARTIKEL "
                            "ADD COLUMN EK_BEZUG ENUM('STK','VPE_EK') "
                            "NULL AFTER VPE_EK")

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

            # Phase 6: Verknuepfung XT-Bestellung ↔ CAO-EKBESTELL.
            # Wird gefuellt sobald die Bestellung als CAO-EKBESTELL
            # gebucht wurde. Vor Phase 6 ist die Spalte NULL.
            for col, ddl in [
                ('CAO_EKBESTELL_REC_ID',
                 'INT NULL AFTER GESAMTSUMME_NETTO'),
                ('CAO_BELEGNUM',
                 'VARCHAR(20) NULL AFTER CAO_EKBESTELL_REC_ID'),
            ]:
                cur.execute("""
                    SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME   = 'XT_EINKAUF_BESTELLUNG'
                      AND COLUMN_NAME  = %s
                """, (col,))
                if int((cur.fetchone() or {}).get('n', 0)) == 0:
                    cur.execute(
                        f"ALTER TABLE XT_EINKAUF_BESTELLUNG "
                        f"ADD COLUMN {col} {ddl}"
                    )

            # Phase 5b-Verbesserung: XT_ARTIKEL_EK_BEZUG — Override
            # des EK-Bezugs am Artikel selbst (ARTIKEL.EK_PREIS).
            # CAO speichert dort uneinheitlich mal Stueck-, mal Karton-
            # EK (Marlboro Gold: VPE_EK=12, EK_PREIS=60€ → Karton).
            # Damit unsere Faktor-Anzeige stimmt, ohne ARTIKEL.EK_PREIS
            # in CAO anzufassen, merken wir uns hier den Bezug pro
            # Artikel. Default fuer alle Artikel ohne Eintrag = 'STK'.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_ARTIKEL_EK_BEZUG (
                  ARTIKEL_ID    INT          NOT NULL PRIMARY KEY,
                  EK_BEZUG      ENUM('STK','VPE_EK') NOT NULL,
                  GEAENDERT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                              ON UPDATE CURRENT_TIMESTAMP,
                  GEAENDERT_VON INT          NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Phase 5b: EK-Bezug fuer ARTIKEL.EK_PREIS (Stueck vs. Karton)'
            """)

            # Phase 5b-Verbesserung: XT_ARTIKEL_PREIS_BEZUG — Override
            # des EK-Bezugs ('STK' / 'VPE_EK') pro CAO-Lief-Artikel-Kombi.
            # Lebt unabhaengig vom Einkauf-Cache (XT_EINKAUF_LIEF_ARTIKEL),
            # damit der User auch fuer CAO-Lieferanten ohne UTZ-Anbindung
            # (C&C, Inventurberichtigung etc.) den Bezug umschalten kann.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_ARTIKEL_PREIS_BEZUG (
                  ARTIKEL_ID    INT          NOT NULL,
                  ADRESS_ID     INT          NOT NULL,
                  EK_BEZUG      ENUM('STK','VPE_EK') NOT NULL,
                  GEAENDERT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                              ON UPDATE CURRENT_TIMESTAMP,
                  GEAENDERT_VON INT          NULL,
                  PRIMARY KEY (ARTIKEL_ID, ADRESS_ID),
                  INDEX idx_adress (ADRESS_ID)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Phase 5b: EK-Bezug-Override pro CAO-Artikel × Lieferant'
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

    # CAO-Bilder-Tabelle: Standard-BINAER_TYP "Produktbild" anlegen,
    # damit Lieferanten-Bilder kategorisiert werden koennen.
    try:
        from . import binaerdaten as _bd
        _bd.run_migration()
    except Exception as exc:
        log.warning("BINAER_TYPEN-Init fehlgeschlagen: %s", exc)


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
           "WEB_USERNAME, WEB_KUNDEN_NR, WEB_KEY, PARSER_KEY, "
           "EK_BEZUG_DEFAULT, AKTIV, "
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
                "EK_BEZUG_DEFAULT, "
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
        'EK_BEZUG_DEFAULT',
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
        elif k == 'EK_BEZUG_DEFAULT':
            v_norm = (str(v).strip().upper()
                       if v is not None else 'STK')
            if v_norm not in ('STK', 'VPE_EK'):
                v_norm = 'STK'
            felder.append('EK_BEZUG_DEFAULT = %s')
            werte.append(v_norm)
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
                        artnr: str) -> Optional[dict]:
    """Laedt das Produktbild von ``url`` und liefert die Bytes plus
    Metadaten (oder None bei Fehler).

    Rueckgabe-Dict::

        {'rel_pfad': 'lieferanten/<KUERZEL>/<artnr>.<ext>',
         'datei':    '<artnr>.<ext>',
         'daten':    <bytes>,
         'url':      <urspruengliche URL>}

    Schreibt das Bild ZUSAETZLICH ins Filesystem (Legacy-Cache),
    damit bestehende Filesystem-Konsumenten weiterlaufen, solange wir
    noch nicht alle Templates auf BINAERDATEN umgestellt haben.
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

    # Filesystem-Cache (Legacy) — best effort, Fehler tolerieren.
    rel_pfad = f'lieferanten/{kuerzel}/{dateiname}'
    try:
        zielordner = os.path.join(_LIEF_BILD_DIR, kuerzel)
        os.makedirs(zielordner, exist_ok=True)
        pfad = os.path.join(zielordner, dateiname)
        with open(pfad, 'wb') as f:
            f.write(r.content)
    except Exception as exc:
        log.warning('Bild-FS-Save best-effort fehlgeschlagen %s: %s',
                    rel_pfad, exc)

    return {
        'rel_pfad': rel_pfad,
        'datei':    dateiname,
        'daten':    r.content,
        'url':      url,
    }


def _bild_in_binaerdaten_speichern(lief_art_rec_id: int,
                                    bild_info: dict,
                                    erst_name: str = 'Einkauf-Poller'
                                    ) -> Optional[int]:
    """Speichert ein Lieferanten-Bild als BLOB in CAO ``BINAERDATEN``.

    Verwendet die XT-Sonder-MODUL_ID 91020 (Lieferantenartikel-Cache).
    Sobald der Lief-Artikel auf einen CAO-``ARTIKEL.REC_ID`` gemappt
    wird, kann ``binaerdaten.binaer_umtaggen`` den Eintrag auf
    MODUL_ID=1020 verschieben. Liefert die ``BINAERDATEN.REC_ID``
    oder ``None`` bei Fehler.
    """
    if not bild_info or not bild_info.get('daten'):
        return None
    try:
        from . import binaerdaten as _bd
        typ_id = _bd.typ_id_holen(_bd.TYP_NAME_PRODUKTBILD)
        return _bd.binaer_speichern_oder_ersetzen(
            modul_id=_bd.MODUL_ID_XT_LIEF_ARTIKEL_CACHE,
            referenz_id=int(lief_art_rec_id),
            binaer_typ=typ_id,
            pfad=bild_info.get('url') or bild_info.get('rel_pfad') or '',
            datei=bild_info.get('datei') or '',
            daten=bild_info.get('daten') or b'',
            primaer=True,
            erst_name=erst_name,
        )
    except Exception as exc:
        log.warning("BINAERDATEN-Save fuer LIEF_ART %s fehlgeschlagen: %s",
                    lief_art_rec_id, exc)
        return None


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
        # ON DUPLICATE KEY UPDATE liefert lastrowid=0, wenn ein
        # bestehender Datensatz aktualisiert wurde — dann den
        # vorhandenen REC_ID per UNIQUE-Schluessel nachschlagen.
        rec_id = int(cur.lastrowid or 0)
        if not rec_id:
            cur.execute("""
                SELECT REC_ID FROM XT_EINKAUF_LIEF_ARTIKEL
                WHERE LIEF_REC_ID = %s AND ARTIKEL_NR_LIEF = %s
            """, (int(lief_rec_id), (artnr or '')[:40]))
            row = cur.fetchone()
            rec_id = int((row or {}).get('REC_ID') or 0)
        return rec_id


def lief_artikel_ek_bezug_setzen(lief_rec_id: int, artnr: str,
                                   ek_bezug: Optional[str]) -> dict:
    """Setzt den EK-Bezug-Override (Phase 5b-Verbesserung) fuer einen
    Lief-Artikel. ``ek_bezug='STK'`` oder ``'VPE_EK'`` oder ``None``
    (=Override entfernen, Lieferanten-Default greift wieder).
    """
    if ek_bezug is not None and ek_bezug not in ('STK', 'VPE_EK'):
        return {'ok': False, 'msg': f'Ungueltiger Bezug: {ek_bezug!r}'}
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                UPDATE XT_EINKAUF_LIEF_ARTIKEL
                   SET EK_BEZUG = %s
                 WHERE LIEF_REC_ID = %s AND ARTIKEL_NR_LIEF = %s
            """, (ek_bezug, int(lief_rec_id), (artnr or '')[:40]))
            n = cur.rowcount
        return {'ok': True, 'updated': n, 'ek_bezug': ek_bezug}
    except Exception as exc:
        return {'ok': False, 'msg': str(exc)}


def lieferant_ek_bezug_default_setzen(lief_rec_id: int,
                                       ek_bezug: str) -> dict:
    """Setzt den EK-Bezug-Default eines Lieferanten ('STK' / 'VPE_EK').
    Greift fuer alle seine Lief-Artikel ohne expliziten Override.
    """
    if ek_bezug not in ('STK', 'VPE_EK'):
        return {'ok': False, 'msg': f'Ungueltiger Bezug: {ek_bezug!r}'}
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                UPDATE XT_EINKAUF_LIEFERANT
                   SET EK_BEZUG_DEFAULT = %s
                 WHERE REC_ID = %s
            """, (ek_bezug, int(lief_rec_id)))
            n = cur.rowcount
        return {'ok': True, 'updated': n, 'ek_bezug_default': ek_bezug}
    except Exception as exc:
        return {'ok': False, 'msg': str(exc)}


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
    bild_info: Optional[dict] = None
    if parsed.get('bild_url'):
        cached = lief_artikel_holen(lief_rec_id, artnr) or {}
        if not cached.get('BILD_BINAER_ID') and \
                not (cached.get('BILD_LOKAL') or '').strip():
            kuerzel = ''
            try:
                lief = holen(lief_rec_id) or {}
                kuerzel = lief.get('KUERZEL') or ''
            except Exception:
                pass
            bild_info = _download_lief_bild(parsed['bild_url'],
                                            kuerzel, artnr)
            if bild_info:
                parsed['bild_lokal'] = bild_info.get('rel_pfad') or ''
        else:
            parsed['bild_lokal'] = cached.get('BILD_LOKAL') or ''

    lief_art_rec_id = lief_artikel_speichern(lief_rec_id, artnr,
                                              parsed=parsed)
    # Bild in BINAERDATEN ablegen (XT-Cache MODUL_ID 91020) und die
    # ID am Cache-Eintrag persistieren.
    if bild_info and lief_art_rec_id:
        binaer_id = _bild_in_binaerdaten_speichern(lief_art_rec_id,
                                                     bild_info)
        if binaer_id:
            try:
                with get_db_transaction() as cur:
                    cur.execute(
                        "UPDATE XT_EINKAUF_LIEF_ARTIKEL "
                        "SET BILD_BINAER_ID = %s WHERE REC_ID = %s",
                        (binaer_id, lief_art_rec_id))
            except Exception as exc:
                log.warning(
                    "BILD_BINAER_ID-Update fuer LIEF_ART %s: %s",
                    lief_art_rec_id, exc)
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

        # ARTIKEL_PREIS.PREIS bekommt den STUECK-EK, nicht den
        # Mail-Roh-Wert — siehe _stueck_ek + cao_match_positionen.
        # Damit bleibt der Faktor-Mechanismus konsistent zu CAO
        # (CAO speichert auch in ARTIKEL_PREIS Stueck-Preise).
        preis = float(m.get('stueck_ek') or m.get('preis_netto') or 0)
        vpe   = m.get('vpe_lief')

        if dry_run:
            if art == 'UNVERAENDERT': n_unch += 1
            elif art == 'UPDATE':     n_upd += 1
            elif art == 'INSERT':     n_ins += 1
            aktionen.append({'pos_nr': pos_nr, 'art': art,
                              'artnr': artnr, 'cao_id': artikel_id,
                              'preis': preis, 'vpe': vpe,
                              'ek_bezug': m.get('ek_bezug'),
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
                # VK-Kontroll-Trigger bei EK-Aenderung: alt-EK aus
                # `pa.alt` (vom Match-Service ermittelt) gegen den
                # neuen Preis vergleichen — wenn abweichend (>= 0.01€),
                # XT_ARTIKEL_VK_KONTROLLE-Eintrag mit GRUND='ek_geaendert'
                # idempotent setzen.
                alt = (pa or {}).get('alt') or {}
                alt_preis = float(alt.get('PREIS') or 0)
                if abs((preis or 0) - alt_preis) >= 0.01:
                    _vk_kontrolle_ek_eintrag(
                        artikel_rec_id=artikel_id,
                        alt_ek=alt_preis,
                        neu_ek=preis,
                        bestellung_rec_id=bestellung_rec_id,
                        ma_id=None,  # Phase 5a hat keinen ma_id-Kontext
                        bestell_nr=head.get('BESTELL_NR') or '',
                        lief_kuerzel=head.get('LIEF_KUERZEL') or '?',
                    )
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

            # Lief-Bild auf den verlinkten CAO-Artikel umtaggen
            # (XT-Cache MODUL_ID=91020 -> CAO Artikel MODUL_ID=1020),
            # damit es im CAO-Faktura-Reiter "Dateilinks" auftaucht.
            if cao_artikel_rec_id is not None:
                try:
                    cur.execute("""
                        SELECT ela.BILD_BINAER_ID
                        FROM XT_EINKAUF_BESTELLPOS bp
                        JOIN XT_EINKAUF_BESTELLUNG b
                          ON b.REC_ID = bp.BEST_REC_ID
                        JOIN XT_EINKAUF_LIEF_ARTIKEL ela
                          ON ela.LIEF_REC_ID = b.LIEF_REC_ID
                         AND ela.ARTIKEL_NR_LIEF = bp.ARTIKEL_NR_LIEF
                        WHERE bp.REC_ID = %s
                          AND ela.BILD_BINAER_ID IS NOT NULL
                        LIMIT 1
                    """, (int(pos_rec_id),))
                    row = cur.fetchone() or {}
                    bid = row.get('BILD_BINAER_ID')
                    if bid:
                        cur.execute("""
                            UPDATE BINAERDATEN
                               SET MODUL_ID = 1020, REFERENZ_ID = %s
                             WHERE REC_ID = %s AND MODUL_ID = 91020
                        """, (int(cao_artikel_rec_id), int(bid)))
                except Exception as exc:
                    log.warning(
                        'Bild-Umtaggen (Pos %s -> Artikel %s): %s',
                        pos_rec_id, cao_artikel_rec_id, exc)
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


def _lief_preis_aktion_aus_bulk(cao_artikel_rec_id: Optional[int],
                                 cao_lief_id: Optional[int],
                                 neue_bestnum: str,
                                 neuer_preis: Optional[float],
                                 neue_vpe: Optional[int],
                                 preis_map: dict[int, dict]) -> dict:
    """Wie ``_lief_preis_aktion`` — aber ohne DB-Roundtrip.

    Liest den existierenden ARTIKEL_PREIS-Eintrag aus dem
    vorgeladenen ``preis_map`` (artikel_id → row). Verwendet von
    ``cao_match_positionen`` zur Performance-Optimierung
    (Bulk-Lookup statt Pro-Pos-Query).
    """
    if not (cao_artikel_rec_id and cao_lief_id):
        if not cao_artikel_rec_id:
            return {'art': 'NICHT_MOEGLICH', 'grund': 'kein CAO-Artikel',
                    'alt': None, 'andere_bestnums': []}
        return {'art': 'NICHT_MOEGLICH',
                'grund': 'Lieferant ohne CAO_LIEF_ID — '
                          'Verknüpfung erst nach Adress-Zuordnung möglich',
                'alt': None, 'andere_bestnums': []}

    bestnum = (neue_bestnum or '').strip()
    existing = preis_map.get(int(cao_artikel_rec_id))

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
            teile.append(f'VPE {alt_vpe or 0} → {neue_vpe or 0}')
        if diff_bestnum:
            teile.append(f'BESTNUM {alt_bestnum or "—"} → {bestnum}')
        return {
            'art': 'UPDATE',
            'grund': 'Bestehender Eintrag wird aktualisiert: '
                     + '; '.join(teile) + '.',
            'alt': dict(existing),
            'andere_bestnums': [],
        }

    return {
        'art': 'INSERT',
        'grund': ('Bisher kein Lieferantenpreis vom aktuellen '
                  'Lieferanten hinterlegt. Neue Zeile wird angelegt.'),
        'alt': None,
        'andere_bestnums': [],
    }


def _vk_kontrolle_ek_eintrag(artikel_rec_id: int,
                              alt_ek: float,
                              neu_ek: float,
                              bestellung_rec_id: int,
                              ma_id: Optional[int],
                              bestell_nr: str = '',
                              lief_kuerzel: str = '?') -> None:
    """Idempotenter VK-Kontroll-Eintrag bei EK-Aenderung.

    Wird aus :func:`cao_sync_artikel_preis` (Phase 5a) bei
    ``art='UPDATE'`` mit Preisaenderung aufgerufen.

    Logik:
      - Wenn fuer ``ARTIKEL_REC_ID`` schon ein OFFENER Eintrag mit
        ``GRUND='ek_geaendert'`` existiert: ``NEU_EK`` aktualisieren
        (``ALT_EK`` bleibt — das ist der "Vor-Sync"-Wert, den der User
        weiterhin als Referenz braucht).
      - Sonst: neuen Eintrag anlegen.

    Fehler werden geloggt aber NICHT propagiert — die VK-Kontrolle ist
    eine "Nice-to-have"-Audit-Spur, sie soll den Sync nicht abbrechen
    falls die Tabelle noch nicht existiert (Migration-Race).
    """
    try:
        with get_db_transaction() as cur:
            cur.execute("""
                SELECT REC_ID, ALT_EK FROM XT_ARTIKEL_VK_KONTROLLE
                WHERE ARTIKEL_REC_ID = %s
                  AND GRUND          = 'ek_geaendert'
                  AND ERLEDIGT_AT IS NULL
                ORDER BY REC_ID DESC LIMIT 1
            """, (int(artikel_rec_id),))
            row = cur.fetchone()
            anm = (f'Phase 5a: EK-Aenderung ueber Bestellung '
                    f'{bestell_nr or bestellung_rec_id} '
                    f'(Lief={lief_kuerzel}). '
                    f'EK {float(alt_ek):.4f} → {float(neu_ek):.4f} €.')
            if row:
                cur.execute("""
                    UPDATE XT_ARTIKEL_VK_KONTROLLE
                       SET NEU_EK = %s,
                           QUELLE_BEST = %s,
                           ANMERKUNG = %s
                     WHERE REC_ID = %s
                """, (neu_ek, int(bestellung_rec_id), anm, row['REC_ID']))
            else:
                cur.execute("""
                    INSERT INTO XT_ARTIKEL_VK_KONTROLLE
                      (ARTIKEL_REC_ID, GRUND, ALT_EK, NEU_EK,
                       QUELLE_BEST, ANGELEGT_VON, ANMERKUNG)
                    VALUES (%s, 'ek_geaendert', %s, %s, %s, %s, %s)
                """, (int(artikel_rec_id), alt_ek, neu_ek,
                       int(bestellung_rec_id), ma_id, anm))
    except Exception as exc:
        log.warning('VK-Kontroll-Eintrag (ek_geaendert) fuer '
                    'ARTIKEL %s fehlgeschlagen: %s',
                    artikel_rec_id, exc)


def _effektiver_ek_bezug(lief_cache: Optional[dict],
                          lieferant_default: Optional[str],
                          artikel_rec_id: Optional[int] = None,
                          adress_id: Optional[int] = None) -> tuple[str, str]:
    """Liefert ``(bezug, quelle)`` fuer einen Lief-Artikel.

    Reihenfolge (erstes Treffer gewinnt):
        1. CAO-Override (XT_ARTIKEL_PREIS_BEZUG) — falls
           ARTIKEL_REC_ID und ADRESS_ID gesetzt sind. Diese Tabelle
           wird vom Preispflege-UI gefuellt und ist die "moderne"
           Override-Quelle pro CAO-Artikel × Lieferant.
        2. Lief-Cache-Override (XT_EINKAUF_LIEF_ARTIKEL.EK_BEZUG) —
           Legacy-Pfad, gefuellt vom alten Einkauf-Match-UI.
        3. Lieferanten-Default (XT_EINKAUF_LIEFERANT.EK_BEZUG_DEFAULT)
        4. Fallback 'STK'

    Returns: ``(bezug, quelle)`` mit ``quelle`` in
    ``'cao' | 'cache' | 'lieferant' | 'default'``.
    """
    # 1. CAO-Override (neueste Override-Quelle)
    if artikel_rec_id and adress_id:
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT EK_BEZUG FROM XT_ARTIKEL_PREIS_BEZUG
                    WHERE ARTIKEL_ID = %s AND ADRESS_ID = %s
                """, (int(artikel_rec_id), int(adress_id)))
                row = cur.fetchone()
            v = (row or {}).get('EK_BEZUG') or ''
            if v in ('STK', 'VPE_EK'):
                return v, 'cao'
        except Exception as exc:
            log.warning('_effektiver_ek_bezug CAO-Override-Lookup: %s', exc)

    # 2. Legacy: Lief-Cache-Override
    if lief_cache:
        v = (lief_cache.get('EK_BEZUG') or '').strip()
        if v in ('STK', 'VPE_EK'):
            return v, 'cache'

    # 3. Lieferanten-Default
    if lieferant_default in ('STK', 'VPE_EK'):
        return lieferant_default, 'lieferant'

    # 4. System-Default
    return 'STK', 'default'


def _stueck_ek(roh_ek: Optional[float],
                vpe_ek: Optional[float],
                bezug: str) -> float:
    """Rechnet einen Mail-EK auf Stueck-EK um.

    bezug='STK'    → unveraendert (= roh_ek ist schon Stueck-Preis)
    bezug='VPE_EK' → roh_ek / vpe_ek (Karton/Kisten-Preis auf Stueck)

    Wenn vpe_ek <= 0 oder None: faellt auf 'STK' zurueck (sicher, kein
    Division-by-zero).
    """
    ek = float(roh_ek or 0)
    if bezug == 'VPE_EK':
        try:
            v = float(vpe_ek or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return round(ek / v, 4)
    return round(ek, 4)


_ARTIKEL_FELDER = (
    'a.REC_ID, a.ARTNUM, a.MATCHCODE, a.KAS_NAME, a.KURZNAME, '
    'a.WARENGRUPPE, a.STEUER_CODE, a.EK_PREIS, a.VK5B, a.MENGE_AKT, '
    'a.NO_VK_FLAG, a.USERFELD_02'
)


def _bulk_lief_artikel(cur, lief_rec_id: int,
                        artnrs: list[str]) -> dict[str, dict]:
    """Bulk-Lookup XT_EINKAUF_LIEF_ARTIKEL fuer alle Artikel-Nrn eines
    Lieferanten. Liefert dict ARTIKEL_NR_LIEF → row."""
    if not lief_rec_id or not artnrs:
        return {}
    ph = ','.join(['%s'] * len(artnrs))
    cur.execute(
        f"SELECT * FROM XT_EINKAUF_LIEF_ARTIKEL "
        f"WHERE LIEF_REC_ID = %s AND ARTIKEL_NR_LIEF IN ({ph})",
        (int(lief_rec_id), *[a[:40] for a in artnrs])
    )
    return {r['ARTIKEL_NR_LIEF']: r for r in cur.fetchall()}


def _bulk_artikel_by_recids(cur, rec_ids: list[int]) -> dict[int, dict]:
    """Bulk-Lookup ARTIKEL by REC_ID (fuer manuelle Matches)."""
    if not rec_ids:
        return {}
    ph = ','.join(['%s'] * len(rec_ids))
    cur.execute(
        f"SELECT {_ARTIKEL_FELDER} FROM ARTIKEL a WHERE a.REC_ID IN ({ph})",
        rec_ids
    )
    return {int(r['REC_ID']): r for r in cur.fetchall()}


def _bulk_barcode_match(cur, barcodes: list[str]) -> dict[str, dict]:
    """Bulk-Lookup ARTIKEL via TRIM(BARCODE/2/3) IN (...).

    Liefert dict barcode → row (nur ein Treffer pro Barcode, wir nehmen
    den mit NO_VK_FLAG='N' und niedrigster REC_ID)."""
    if not barcodes:
        return {}
    bcs = sorted({b.strip() for b in barcodes if b and b.strip()})
    if not bcs:
        return {}
    ph = ','.join(['%s'] * len(bcs))
    cur.execute(
        f"SELECT {_ARTIKEL_FELDER}, "
        f"  TRIM(a.BARCODE) AS bc1, TRIM(a.BARCODE2) AS bc2, "
        f"  TRIM(a.BARCODE3) AS bc3 "
        f"FROM ARTIKEL a "
        f"WHERE TRIM(a.BARCODE)  IN ({ph}) "
        f"   OR TRIM(a.BARCODE2) IN ({ph}) "
        f"   OR TRIM(a.BARCODE3) IN ({ph}) "
        f"ORDER BY (a.NO_VK_FLAG = 'N') DESC, a.REC_ID",
        (*bcs, *bcs, *bcs)
    )
    out: dict[str, dict] = {}
    for r in cur.fetchall():
        for bc_field in ('bc1', 'bc2', 'bc3'):
            bc = r.get(bc_field) or ''
            if bc and bc in bcs and bc not in out:
                out[bc] = r
    return out


def _bulk_lief_artikel_preis(cur, artnrs: list[str],
                              cao_lief: int) -> dict[str, dict]:
    """Bulk-Lookup ARTIKEL_PREIS (Lief-spezifisch) via BESTNUM IN +
    ADRESS_ID=cao_lief, PREIS_TYP=5. Liefert artnr → row."""
    if not artnrs or not cao_lief:
        return {}
    ph = ','.join(['%s'] * len(artnrs))
    cur.execute(
        f"SELECT {_ARTIKEL_FELDER}, ap.BESTNUM AS bestnum_match "
        f"FROM ARTIKEL_PREIS ap "
        f"JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID "
        f"WHERE ap.PREIS_TYP = 5 AND ap.ADRESS_ID = %s "
        f"  AND ap.BESTNUM IN ({ph}) "
        f"ORDER BY ap.GUELTIG_VON DESC",
        (int(cao_lief), *artnrs)
    )
    out: dict[str, dict] = {}
    for r in cur.fetchall():
        bn = r.get('bestnum_match') or ''
        if bn and bn not in out:
            out[bn] = r
    return out


def _bulk_global_artikel_preis(cur, artnrs: list[str]) -> dict[str, dict]:
    """Bulk-Lookup ARTIKEL_PREIS global via BESTNUM IN + PREIS_TYP=5.
    Liefert dict artnr → {row, n_treffer} (n_treffer fuer mehrdeutig)."""
    if not artnrs:
        return {}
    ph = ','.join(['%s'] * len(artnrs))
    # 1. Treffer-Counts pro BESTNUM
    cur.execute(
        f"SELECT BESTNUM, COUNT(*) AS n FROM ARTIKEL_PREIS "
        f"WHERE PREIS_TYP=5 AND BESTNUM IN ({ph}) "
        f"GROUP BY BESTNUM",
        artnrs
    )
    counts = {r['BESTNUM']: int(r['n']) for r in cur.fetchall()}
    if not counts:
        return {}
    # 2. Erster Treffer pro BESTNUM (sortiert nach GUELTIG_VON DESC)
    cur.execute(
        f"SELECT {_ARTIKEL_FELDER}, ap.BESTNUM AS bestnum_match "
        f"FROM ARTIKEL_PREIS ap "
        f"JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID "
        f"WHERE ap.PREIS_TYP = 5 AND ap.BESTNUM IN ({ph}) "
        f"ORDER BY ap.GUELTIG_VON DESC",
        artnrs
    )
    out: dict[str, dict] = {}
    for r in cur.fetchall():
        bn = r.get('bestnum_match') or ''
        if bn and bn not in out:
            out[bn] = {'row': r, 'n_treffer': counts.get(bn, 1)}
    return out


def _bulk_artikel_preis_lief(cur, artikel_ids: list[int],
                              cao_lief: int) -> dict[int, dict]:
    """Bulk-Lookup ARTIKEL_PREIS-PT2 fuer (artikel_id, cao_lief, PT5).
    Genutzt fuer _lief_preis_aktion. Liefert artikel_id → {BESTNUM,PREIS,VPE}."""
    if not artikel_ids or not cao_lief:
        return {}
    ph = ','.join(['%s'] * len(artikel_ids))
    cur.execute(
        f"SELECT ARTIKEL_ID, BESTNUM, PREIS, VPE FROM ARTIKEL_PREIS "
        f"WHERE ARTIKEL_ID IN ({ph}) AND ADRESS_ID = %s AND PREIS_TYP = 5",
        (*artikel_ids, int(cao_lief))
    )
    return {int(r['ARTIKEL_ID']): r for r in cur.fetchall()}


def _bulk_xt_artikel_preis_bezug(cur, paare: list[tuple[int, int]]
                                  ) -> dict[tuple[int, int], str]:
    """Bulk-Lookup XT_ARTIKEL_PREIS_BEZUG fuer (artikel_id, adress_id)-
    Tupel. Liefert dict (aid, addr) → EK_BEZUG."""
    if not paare:
        return {}
    # OR-Chain ueber Tupel — MariaDB unterstuetzt (a,b) IN ((1,2),(3,4))
    paare_uniq = sorted(set(paare))
    placeholders = ','.join(['(%s,%s)'] * len(paare_uniq))
    flat: list[int] = []
    for a, b in paare_uniq:
        flat.extend([a, b])
    cur.execute(
        f"SELECT ARTIKEL_ID, ADRESS_ID, EK_BEZUG "
        f"FROM XT_ARTIKEL_PREIS_BEZUG "
        f"WHERE (ARTIKEL_ID, ADRESS_ID) IN ({placeholders})",
        flat
    )
    return {(int(r['ARTIKEL_ID']), int(r['ADRESS_ID'])):
            (r.get('EK_BEZUG') or '') for r in cur.fetchall()}


def cao_match_positionen(rec_id: int) -> list[dict]:
    """Read-only-Vorschau: pro Position der Bestellung pruefen, ob in CAO
    schon ein passender Artikel hinterlegt ist.

    Match-Strategie:
      0. Manuelle Zuordnung (XT_EINKAUF_BESTELLPOS.STATUS) hat Vorrang.
      1. Barcode-Match: TRIM(ARTIKEL.BARCODE/2/3) = lief_cache.BARCODE_STUECK
      2. Lief-spezifisch: ARTIKEL_PREIS PT5 + ADRESS_ID=lief + BESTNUM=artnr
      3. Global: ARTIKEL_PREIS PT5 + BESTNUM=artnr (mehrdeutig wenn n>1)
      4. Vorschlaege: cao_artikel_vorschlag(bezeichnung) — nur bei kein-Match

    Performance: alle DB-Reads werden BULK ausgefuehrt vor der
    Pos-Loop, danach laeuft der Pro-Pos-Code als reines Python. Vorher
    war pro Pos 5-9 DB-Calls × 47 Pos = 47×9 ~14s. Jetzt ~6 Bulk-Querys
    + leichte Pro-Pos-Aufrufe (cao_artikel_vorschlag und
    _barcode_konflikt) — ca. 10x schneller bei 50+-Pos-Bestellungen.
    """
    head = bestellung_holen(rec_id)
    if not head:
        return []

    cao_lief = head.get('CAO_LIEF_ID')
    lief_rec_id = head.get('LIEF_REC_ID') or 0
    positionen = list(head.get('positionen') or [])

    # ── Bulk-Pre-Load ALL data we need before the loop ─────────
    artnrs = sorted({(p.get('ARTIKEL_NR_LIEF') or '').strip()
                      for p in positionen
                      if (p.get('ARTIKEL_NR_LIEF') or '').strip()})
    manuell_ids = sorted({int(p['ARTIKEL_REC_ID']) for p in positionen
                           if p.get('ARTIKEL_REC_ID')
                           and (p.get('STATUS') or '').lower()
                              not in ('manuell_klaeren', 'neu_anlegen')})

    with get_db() as cur:
        lief_cache_map = _bulk_lief_artikel(cur, lief_rec_id, artnrs)
        manuell_artikel = _bulk_artikel_by_recids(cur, manuell_ids)
        # Barcode-Match via Stueck-EAN aus dem Lief-Cache
        barcodes = sorted({(c.get('BARCODE_STUECK') or '').strip()
                            for c in lief_cache_map.values()
                            if (c.get('BARCODE_STUECK') or '').strip()})
        barcode_match_map = _bulk_barcode_match(cur, barcodes)
        # Lief-spezifischer ARTIKEL_PREIS-Match
        lief_match_map = _bulk_lief_artikel_preis(cur, artnrs, cao_lief or 0)
        # Globaler Fallback
        global_match_map = _bulk_global_artikel_preis(cur, artnrs)

    # Wir brauchen pro Match auch das ARTIKEL_PREIS-Tupel
    # (fuer _lief_preis_aktion). Erstmal alle Kandidaten-Artikel-IDs
    # einsammeln, danach Bulk-Lookup.
    out: list[dict] = []

    # Pass 1: Match-Quelle pro Pos bestimmen, cao_treffer assignen
    pos_state: list[dict] = []
    for p in positionen:
        artnr = (p.get('ARTIKEL_NR_LIEF') or '').strip()
        if not artnr:
            pos_state.append({'pos': p, 'artnr': '', 'cao_treffer': None,
                              'match_quelle': 'kein',
                              'lief_cache': None})
            continue

        lief_cache = lief_cache_map.get(artnr)
        barcode_stk = (lief_cache or {}).get('BARCODE_STUECK') or ''

        man_status = (p.get('STATUS') or '').lower()
        man_rec    = p.get('ARTIKEL_REC_ID')
        cao_treffer = None
        match_quelle = 'kein'
        if man_status == 'manuell_klaeren':
            match_quelle = 'manuell_klaeren'
        elif man_status == 'neu_anlegen':
            match_quelle = 'neu_anlegen'
        elif man_rec:
            cao_treffer = manuell_artikel.get(int(man_rec))
            if cao_treffer:
                match_quelle = 'manuell'

        if cao_treffer is None and barcode_stk:
            cao_treffer = barcode_match_map.get(barcode_stk.strip())
            if cao_treffer:
                match_quelle = 'barcode'
        if cao_treffer is None and cao_lief:
            cao_treffer = lief_match_map.get(artnr)
            if cao_treffer:
                match_quelle = 'lieferant'
        if cao_treffer is None:
            gm = global_match_map.get(artnr)
            if gm:
                cao_treffer = gm['row']
                match_quelle = ('mehrdeutig'
                                 if int(gm.get('n_treffer') or 1) > 1
                                 else 'global')

        # Barcode-Konflikt-Check (nur global/mehrdeutig)
        # Bulk-fy spaeter wenn relevant — typischerweise wenige Positionen
        if (cao_treffer and barcode_stk
                and match_quelle in ('global', 'mehrdeutig')):
            if _barcode_konflikt(barcode_stk, cao_treffer.get('REC_ID')):
                match_quelle = 'unsicher'

        pos_state.append({
            'pos': p, 'artnr': artnr,
            'lief_cache': lief_cache,
            'cao_treffer': cao_treffer,
            'match_quelle': match_quelle,
        })

    # Bulk-Lookup ARTIKEL_PREIS (PT5) fuer alle gematchten Artikel-IDs
    # — fuer _lief_preis_aktion in der naechsten Pos-Loop
    artikel_ids_match = sorted({int(s['cao_treffer']['REC_ID'])
                                 for s in pos_state
                                 if s['cao_treffer']})
    with get_db() as cur:
        artikel_preis_map = _bulk_artikel_preis_lief(
            cur, artikel_ids_match, cao_lief or 0)

    # Bulk-Lookup XT_ARTIKEL_PREIS_BEZUG fuer alle (aid, cao_lief)-Paare
    bezug_paare = [(int(s['cao_treffer']['REC_ID']), int(cao_lief))
                    for s in pos_state
                    if s['cao_treffer'] and cao_lief]
    with get_db() as cur:
        bezug_override_map = _bulk_xt_artikel_preis_bezug(cur, bezug_paare)

    # Pass 2: pro Pos das finale Output-Dict bauen
    for s in pos_state:
        p = s['pos']
        artnr = s['artnr']
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

        cao_treffer = s['cao_treffer']
        match_quelle = s['match_quelle']
        lief_cache = s['lief_cache']
        barcode_stk = (lief_cache or {}).get('BARCODE_STUECK') or ''

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
            bild_binaer_id = lief_cache.get('BILD_BINAER_ID') or 0
            # Bild-URL-Prio: BINAERDATEN-BLOB > Filesystem-Cache > externe URL.
            if bild_binaer_id:
                bild_url_eff = f'/binaer/{int(bild_binaer_id)}'
            elif bild_lokal:
                bild_url_eff = f'/produktbilder/{bild_lokal}'
            else:
                bild_url_eff = lief_cache.get('BILD_URL') or ''
            lief_block = {
                'bezeichnung':     lief_cache.get('BEZEICHNUNG'),
                'barcode_stueck':  lief_cache.get('BARCODE_STUECK'),
                'barcode_kt':      lief_cache.get('BARCODE_KT'),
                'bild_url':        bild_url_eff,
                'bild_lokal':      bool(bild_lokal or bild_binaer_id),
                'verfuegbarkeit':  lief_cache.get('VERFUEGBARKEIT'),
                'vpe_ek':          lief_cache.get('VPE_EK'),
                # Fuer cao_sync_artikel: Bild beim Stammdaten-Match aus
                # dem XT-Cache (MODUL_ID=91020) auf den neu angelegten
                # ARTIKEL (MODUL_ID=1020) umtaggen.
                'lief_art_rec_id': lief_cache.get('REC_ID'),
                'bild_binaer_id':  bild_binaer_id or None,
            }
            try:
                vpe_lief = (int(lief_cache['VPE_EK'])
                             if lief_cache.get('VPE_EK') else None)
            except (TypeError, ValueError):
                vpe_lief = None

        # EK-Bezug ermitteln (CAO-Override > Lief-Cache > Lief-Default
        # > 'STK'). Bulk-Override aus bezug_override_map nutzen (vermeidet
        # eine Pro-Pos-Query an XT_ARTIKEL_PREIS_BEZUG).
        cao_id_for_bezug = (cao_block or {}).get('rec_id')
        ek_bezug = None
        ek_bezug_quelle_neu = 'default'
        if cao_id_for_bezug and cao_lief:
            ov = bezug_override_map.get(
                (int(cao_id_for_bezug), int(cao_lief)))
            if ov in ('STK', 'VPE_EK'):
                ek_bezug, ek_bezug_quelle_neu = ov, 'cao'
        if ek_bezug is None and lief_cache:
            v = (lief_cache.get('EK_BEZUG') or '').strip()
            if v in ('STK', 'VPE_EK'):
                ek_bezug, ek_bezug_quelle_neu = v, 'cache'
        if ek_bezug is None:
            v = head.get('LIEF_EK_BEZUG_DEFAULT')
            if v in ('STK', 'VPE_EK'):
                ek_bezug, ek_bezug_quelle_neu = v, 'lieferant'
        if ek_bezug is None:
            ek_bezug, ek_bezug_quelle_neu = 'STK', 'default'
        roh_ek = float(p.get('PREIS_NETTO') or 0)
        stueck_ek = _stueck_ek(roh_ek, vpe_lief, ek_bezug)

        # ARTIKEL_PREIS-Aktion-Vorschau aus dem Bulk-Lookup
        # artikel_preis_map (vermeidet Pro-Pos-Query).
        preis_aktion = None
        if cao_block and match_quelle in ('barcode', 'lieferant', 'global',
                                            'manuell'):
            preis_aktion = _lief_preis_aktion_aus_bulk(
                cao_block.get('rec_id'), cao_lief,
                neue_bestnum=artnr,
                neuer_preis=stueck_ek,
                neue_vpe=vpe_lief,
                preis_map=artikel_preis_map,
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
            # EK-Bezug + Stueck-EK (Phase 5b-Verbesserung):
            # ek_bezug         = 'STK' oder 'VPE_EK' (effektiv)
            # ek_bezug_quelle  = 'cao' | 'cache' | 'lieferant' | 'default'
            #                    (Reihenfolge in _effektiver_ek_bezug)
            # stueck_ek        = preis_netto bei 'STK',
            #                    preis_netto / vpe_lief bei 'VPE_EK'.
            # → ARTIKEL.EK_PREIS und ARTIKEL_PREIS.PREIS bekommen
            #   immer stueck_ek geschrieben.
            'ek_bezug':         ek_bezug,
            'ek_bezug_quelle':  ek_bezug_quelle_neu,
            'stueck_ek':        stueck_ek,
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
                       l.CAO_LIEF_ID AS CAO_LIEF_ID,
                       l.EK_BEZUG_DEFAULT AS LIEF_EK_BEZUG_DEFAULT
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

def _next_registry_nummer(cur, name: str) -> str:
    """Holt die naechste Nummer aus REGISTRY MAIN\\NUMBERS / <name>
    und erhoeht den Counter atomar (FOR UPDATE).

    Beispiele:
      ``ARTIKELNUMMER`` (VAL_CHAR='000000', 6-stellig) — fuer ARTNUM
      ``EK-BEST`` (VAL_CHAR='000000', 6-stellig) — fuer EKBESTELL.BELEGNUM
      ``VK-KASSE`` etc.

    VAL_CHAR enthaelt das Padding-Pattern (Anzahl '0'-Zeichen = Stellen).
    Aufruf muss innerhalb einer Transaktion erfolgen.
    """
    cur.execute("""
        SELECT VAL_INT2, VAL_CHAR
        FROM REGISTRY
        WHERE MAINKEY = 'MAIN\\\\NUMBERS' AND NAME = %s
        FOR UPDATE
    """, (name,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(
            f"REGISTRY-Eintrag MAIN\\NUMBERS / {name} fehlt — "
            "CAO Faktura sollte ihn beim ersten Start anlegen."
        )
    naechste = int(row['VAL_INT2'] or 0) + 1
    pad = (row['VAL_CHAR'] or '000000')
    n_stellen = pad.count('0') if pad.count('0') > 0 else 6
    nummer = f"{naechste:0{n_stellen}d}"
    cur.execute("""
        UPDATE REGISTRY
        SET VAL_INT2 = %s
        WHERE MAINKEY = 'MAIN\\\\NUMBERS' AND NAME = %s
    """, (naechste, name))
    return nummer


def _next_artnum(cur) -> str:
    """Naechste ARTNUM aus REGISTRY (Wrapper auf _next_registry_nummer)."""
    return _next_registry_nummer(cur, 'ARTIKELNUMMER')


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
        # ARTIKEL.EK_PREIS bekommt immer den STUECK-EK — siehe
        # _stueck_ek + cao_match_positionen. Damit ist der Faktor
        # (vk5_netto / EK_PREIS) konsistent berechnet, egal ob der
        # Lieferant Stueck- oder Karton-Preise schickt.
        ek_preis  = float(m.get('stueck_ek') or m.get('preis_netto') or 0)
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

                # 10. Lieferanten-Bild auf den neu angelegten Artikel
                # umtaggen (XT-Cache 91020 -> CAO 1020). Damit ist das
                # Bild ab sofort im CAO-Faktura-Artikelstamm-Reiter
                # "Dateilinks" sichtbar.
                bild_binaer_id = (lief_block or {}).get('bild_binaer_id')
                if bild_binaer_id:
                    try:
                        cur.execute("""
                            UPDATE BINAERDATEN
                               SET MODUL_ID = 1020, REFERENZ_ID = %s
                             WHERE REC_ID = %s
                               AND MODUL_ID = 91020
                        """, (int(artikel_id), int(bild_binaer_id)))
                    except Exception as exc:
                        log.warning(
                            "Bild-Umtaggen (BINAERDATEN.REC_ID=%s -> "
                            "Artikel %s) fehlgeschlagen: %s",
                            bild_binaer_id, artikel_id, exc)

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


# ── Phase 6: EKBESTELL + EKBESTELL_POS in CAO anlegen ───────────────

# Mapping ARTIKEL.STEUER_CODE → MWST-Klasse-Index in EKBESTELL
# (CAO speichert NSUMME_0..NSUMME_3 + MWST_0..MWST_3 fuer 4 Steuer-
# Klassen). Steuer-Code 0 = "ohne MwSt" → Klasse 0.
_STEUER_CODE_TO_MWST_KLASSE = {0: 0, 1: 1, 2: 2, 3: 3}


def cao_sync_ekbestell(bestellung_rec_id: int,
                        dry_run: bool = False,
                        ma_id: Optional[int] = None,
                        ma_name: Optional[str] = None) -> dict:
    """Phase 6: legt eine CAO-Einkaufsbestellung (EKBESTELL +
    EKBESTELL_POS) aus einer Lieferanten-Bestellbestaetigung an.

    Voraussetzungen:
      * Bestellung existiert in XT_EINKAUF_BESTELLUNG
      * CAO-Lieferant ist verknuepft (head.CAO_LIEF_ID)
      * Alle relevanten Positionen sind STATUS='in_cao' (= Phase 5a/5b
        durchgelaufen, jede Position hat eine ARTIKEL_REC_ID)
      * Bestellung ist noch nicht in CAO gebucht
        (CAO_EKBESTELL_REC_ID IS NULL)

    Schreibt:
      * INSERT INTO EKBESTELL — Header mit BELEGNUM aus REGISTRY,
        ADDR_ID = Lieferant, KUN_*-Felder aus ADRESSEN-Snapshot,
        STADIUM=2 (offen/bestellt), HASHSUM='$$' (CAO-Default).
      * INSERT INTO EKBESTELL_POS pro Position — MENGE und EPREIS
        in Stueck (per ek_bezug umgerechnet), GPREIS = MENGE*EPREIS.
      * Updates XT_EINKAUF_BESTELLUNG.CAO_EKBESTELL_REC_ID +
        CAO_BELEGNUM.

    Schreibt NICHT ins JOURNAL — bei Habacher-Praxis (verifiziert in
    cao_XT_DEV: 333 EKBESTELL-Eintraege, 0 JOURNAL.QUELLE=06) ist die
    Einkaufsbestellung nur in EKBESTELL. Wareneingang (Phase 7) und
    EK-Rechnung (Phase 8) erzeugen spaeter JOURNAL-Eintraege mit
    QUELLE=15/05 und JOURNALPOS.QUELLE_SRC=EKBESTELL_POS.REC_ID.

    Returns::
        {'ok': bool,
         'dry_run': bool,
         'belegnum': str,           # vergebene Bestellnummer
         'ekbestell_rec_id': int,   # neue REC_ID in EKBESTELL
         'positions': int,          # Anzahl angelegte Positionen
         'nsumme': float,           # Netto-Gesamt
         'bsumme': float,           # Brutto-Gesamt
         'fehler': [...]}
    """
    head = bestellung_holen(bestellung_rec_id)
    if not head:
        return {'ok': False, 'msg': 'Bestellung nicht gefunden.'}
    if head.get('CAO_EKBESTELL_REC_ID'):
        return {'ok': False,
                'msg': f'Bestellung ist schon in CAO als BELEGNUM '
                       f'{head.get("CAO_BELEGNUM")} angelegt '
                       f'(EKBESTELL.REC_ID={head.get("CAO_EKBESTELL_REC_ID")}).'}
    cao_lief = head.get('CAO_LIEF_ID')
    if not cao_lief:
        return {'ok': False,
                'msg': 'Lieferant ohne CAO-Adress-Zuordnung — '
                       'erst unter "Einkauf → Lieferanten" verknuepfen.'}

    # Match-Positionen holen — wir nehmen nur 'in_cao'-Positionen
    # (= Phase 5a hat ARTIKEL_PREIS verknuepft, ARTIKEL_REC_ID gesetzt).
    matches = cao_match_positionen(bestellung_rec_id)
    if not matches:
        return {'ok': False, 'msg': 'Bestellung hat keine Positionen.'}

    relevante = [m for m in matches
                  if (m.get('pos_status') or '') == 'in_cao'
                     and (m.get('cao') or {}).get('rec_id')]
    skipped = len(matches) - len(relevante)
    if not relevante:
        return {'ok': False,
                'msg': 'Keine Position auf STATUS=in_cao mit '
                       'ARTIKEL_REC_ID — erst "🚀 In CAO einbuchen" '
                       'ausfuehren.'}

    # Lieferanten-Adresse + LIEF-spezifische Felder
    # (LIEF_LIEFART/ZAHLART, KRD_NUM, NET_SKONTO, Bank-Daten).
    lief_adr = None
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT REC_ID, MATCHCODE, ANREDE, NAME1, NAME2, NAME3,
                       STRASSE, HAUSNR, ADRESSZUSATZ, PLZ, ORT, LAND,
                       UST_NUM,
                       KRD_NUM,           -- → GEGENKONTO
                       LIEF_LIEFART,      -- → LIEFART
                       LIEF_ZAHLART,      -- → ZAHLART
                       NET_SKONTO,
                       KUNNUM2            -- unsere Kunden-Nr. beim Lief
                FROM ADRESSEN WHERE REC_ID = %s
            """, (int(cao_lief),))
            lief_adr = cur.fetchone() or {}
    except Exception as exc:
        return {'ok': False, 'msg': f'Adresse {cao_lief} laden: {exc}'}

    # Zahlungsart-Daten aus ZAHLUNGSARTEN (fuer ZAHLART_NAME/KURZ/LANG
    # + SOLL_NTAGE/STAGE/SKONTO).
    zahlart_id = lief_adr.get('LIEF_ZAHLART')
    zahlart_data = {}
    if zahlart_id and int(zahlart_id) > 0:
        try:
            with get_db() as cur:
                cur.execute("""SELECT NAME, TEXT_KURZ, TEXT_LANG,
                                       NETTO_TAGE, SKONTO_TAGE, SKONTO_PROZ
                                FROM ZAHLUNGSARTEN WHERE REC_ID = %s""",
                            (int(zahlart_id),))
                zahlart_data = cur.fetchone() or {}
        except Exception:
            pass

    # Lieferart-Daten aus LIEFERARTEN (fuer LIEFART_NAME/LANG)
    liefart_id = lief_adr.get('LIEF_LIEFART')
    liefart_data = {}
    if liefart_id and int(liefart_id) > 0:
        try:
            with get_db() as cur:
                cur.execute("""SELECT NAME, TEXT_KURZ, TEXT_LANG
                                FROM LIEFERARTEN WHERE REC_ID = %s""",
                            (int(liefart_id),))
                liefart_data = cur.fetchone() or {}
        except Exception:
            pass

    # MwSt-Saetze aus REGISTRY MAIN\\MWST. Codes:
    #   0 = ohne MwSt    1 = voll (19%)    2 = ermaessigt (7%)
    #   3 = Reserve (7.8%)   4 = AT-MwSt (10%)
    mwst_per_code: dict[int, float] = {0: 0.0}
    try:
        with get_db() as cur:
            cur.execute("""SELECT NAME, VAL_DOUBLE FROM REGISTRY
                           WHERE MAINKEY = 'MAIN\\\\MWST'
                             AND VAL_DOUBLE IS NOT NULL""")
            for r in cur.fetchall() or []:
                try:
                    mwst_per_code[int(r['NAME'])] = float(r['VAL_DOUBLE'])
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        log.warning('mwst-saetze laden: %s', exc)
    # Aliasing fuer den alten Variablennamen weiter unten
    mwst_satz_per_code = mwst_per_code

    # Erst Sammel-Lookup der Artikel-Stammdaten fuer alle Positionen
    # (BARCODE, GEWICHT, ME_ID, AUFW_KTO, WARENGRUPPE) plus WG-Name +
    # Mengeneinheit-Bezeichnung/Code. Spart einen Roundtrip pro Pos.
    art_ids = [int((m.get('cao') or {}).get('rec_id') or 0)
               for m in relevante]
    art_ids = [a for a in art_ids if a > 0]
    art_data: dict[int, dict] = {}
    if art_ids:
        try:
            with get_db() as cur:
                placeholders = ','.join(['%s'] * len(art_ids))
                cur.execute(f"""
                    SELECT a.REC_ID, a.ARTNUM, a.BARCODE, a.WARENGRUPPE,
                           a.GEWICHT, a.AUFW_KTO, a.ME_ID,
                           wg.NAME       AS WGR_NAME,
                           me.BEZEICHNUNG AS ME_BEZ,
                           me.ME_CODE    AS ME_CODE
                    FROM ARTIKEL a
                    LEFT JOIN WARENGRUPPEN wg  ON wg.ID = a.WARENGRUPPE
                    LEFT JOIN MENGENEINHEIT me ON me.REC_ID = a.ME_ID
                    WHERE a.REC_ID IN ({placeholders})
                """, art_ids)
                for r in cur.fetchall() or []:
                    art_data[int(r['REC_ID'])] = r
        except Exception as exc:
            log.warning('Artikel-Stamm-Lookup: %s', exc)

    pos_daten: list[dict] = []
    n_summen = [0.0, 0.0, 0.0, 0.0]
    m_summen = [0.0, 0.0, 0.0, 0.0]
    gewicht_total = 0.0
    fehler: list[dict] = []

    for m in relevante:
        cao = m.get('cao') or {}
        artikel_id = int(cao.get('rec_id') or 0)
        a = art_data.get(artikel_id, {})
        st_code = int(cao.get('steuer_code') or 0)
        klasse  = _STEUER_CODE_TO_MWST_KLASSE.get(st_code, 0)
        menge   = float(m.get('menge') or 0)
        # ARTIKEL.EPREIS ist Stueck-EK — wir liefern stueck_ek aus
        # cao_match_positionen (bereits per ek_bezug korrigiert).
        stueck_ek = float(m.get('stueck_ek') or m.get('preis_netto') or 0)
        gpreis = round(menge * stueck_ek, 2)
        n_summen[klasse] += gpreis
        mwst_satz = mwst_satz_per_code.get(st_code, 0.0) / 100.0
        m_summen[klasse] += round(gpreis * mwst_satz, 2)
        # Header-Gesamtgewicht: Stueck-Gewicht × Menge
        stueck_gewicht = float(a.get('GEWICHT') or 0)
        gewicht_total += stueck_gewicht * menge

        pos_daten.append({
            'pos_nr':       int(m.get('pos_nr') or 0),
            'artikel_id':   artikel_id,
            'artnum':       a.get('ARTNUM') or cao.get('artnum') or '',
            'matchcode':    cao.get('matchcode') or cao.get('kas_name') or '',
            'kurzname':     cao.get('kas_name') or cao.get('matchcode') or '',
            'bezeichnung':  m.get('bezeichnung_lief') or '',
            'menge':        menge,
            'epreis':       stueck_ek,
            'gpreis':       gpreis,
            'liefartnum':   m.get('artikel_nr_lief') or '',
            'st_code':      st_code,
            'mwst_klasse':  klasse,
            'vpe_lief':     m.get('vpe_lief'),
            'pos_rec_id':   m.get('pos_rec_id'),
            # Aus ARTIKEL-Stamm
            'barcode':      (a.get('BARCODE') or '').strip(),
            'wgr':          int(a.get('WARENGRUPPE') or -1),
            'wgr_name':     a.get('WGR_NAME') or '',
            'gewicht':      stueck_gewicht,
            'aufw_kto':     int(a.get('AUFW_KTO') or -1),
            'me_einheit':   a.get('ME_BEZ') or '',
            'me_code':      a.get('ME_CODE') or '',
        })

    nsumme = round(sum(n_summen), 2)
    msumme = round(sum(m_summen), 2)
    bsumme = round(nsumme + msumme, 2)

    if dry_run:
        return {
            'ok':              True,
            'dry_run':         True,
            'belegnum':        '(naechste aus REGISTRY)',
            'ekbestell_rec_id': None,
            'positions':       len(pos_daten),
            'skipped':         skipped,
            'nsumme':          nsumme,
            'msumme':          msumme,
            'bsumme':          bsumme,
            'lief_name':       lief_adr.get('NAME1') or '?',
            'pos_preview':     [{
                'pos_nr':    p['pos_nr'],
                'artnum':    p['artnum'],
                'mc':        p['matchcode'][:60],
                'menge':     p['menge'],
                'epreis':    p['epreis'],
                'gpreis':    p['gpreis'],
            } for p in pos_daten[:8]],
        }

    # Live-Sync — alles in einer Transaktion
    from datetime import datetime as _dt, date as _date
    try:
        with _xt_ekbestell_sync_lock_tx(bestellung_rec_id) as cur:
            # Re-Check UNTER dem Lock: der Guard oben (head.CAO_
            # EKBESTELL_REC_ID) ist ein Check-then-Act. Zwei
            # gleichzeitige Syncs derselben Bestellung würden sonst
            # beide ein EKBESTELL anlegen. Jetzt sieht der zweite den
            # vom ersten gesetzten Wert und bricht idempotent ab —
            # BEVOR die BELEGNUM gezogen wird.
            cur.execute(
                "SELECT CAO_EKBESTELL_REC_ID, CAO_BELEGNUM "
                "FROM XT_EINKAUF_BESTELLUNG WHERE REC_ID=%s",
                (int(bestellung_rec_id),))
            _chk = cur.fetchone() or {}
            if _chk.get('CAO_EKBESTELL_REC_ID'):
                return {
                    'ok': False,
                    'msg': f'Bestellung ist schon in CAO als BELEGNUM '
                           f'{_chk.get("CAO_BELEGNUM")} angelegt '
                           f'(EKBESTELL.REC_ID='
                           f'{_chk.get("CAO_EKBESTELL_REC_ID")}).'}
            belegnum = _next_registry_nummer(cur, 'EK-BEST')
            heute = head.get('EMAIL_DATUM') or _dt.now()
            try:
                heute = heute.date() if hasattr(heute, 'date') else heute
            except Exception:
                heute = _date.today()

            # Helper: leere Strings statt NULL fuer text-Felder
            # (CAO-Konvention; CAO-Faktura selbst schreibt durchgaengig
            # '' statt NULL in optionalen varchar-Feldern).
            def _s(v): return (str(v) if v is not None else '').strip()

            # MWST-Saetze + Pro-Klasse-Bsumme. CAO speichert immer alle
            # 4 MWST_x-Saetze (auch wenn nicht alle benutzt werden).
            mwst_0 = mwst_per_code.get(0, 0.0)
            mwst_1 = mwst_per_code.get(1, 19.0)
            mwst_2 = mwst_per_code.get(2, 7.0)
            mwst_3 = mwst_per_code.get(3, 0.0)
            at_mwst = mwst_per_code.get(4, 10.0)
            b_summen = [round(n + m, 2)
                        for n, m in zip(n_summen, m_summen)]

            # Zahlungsziel + LIEFART-Defaults
            soll_ntage  = int(zahlart_data.get('NETTO_TAGE') or 0)
            soll_stage  = int(zahlart_data.get('SKONTO_TAGE') or 0)
            soll_skonto = float(zahlart_data.get('SKONTO_PROZ') or 0)

            # GEGENKONTO = Kreditoren-Konto des Lieferanten
            gegenkonto = int(lief_adr.get('KRD_NUM') or -1)

            # FIRMA_ID = Habacher-Default 8 (perspektivisch aus Terminal-
            # bzw. Session-Konfig ableiten; aktuell hardcoded).
            firma_id = 8

            cur.execute("""
                INSERT INTO EKBESTELL (
                  TERM_ID, MA_ID, ADDR_ID, BELEGNUM, BELEGDATUM,
                  LIEFART, ZAHLART, GEGENKONTO,
                  WAEHRUNG, KURS,
                  SOLL_STAGE, SOLL_SKONTO, SOLL_NTAGE,
                  STADIUM, GEWICHT,
                  MWST_0, MWST_1, MWST_2, MWST_3, AT_MWST,
                  NSUMME_0, NSUMME_1, NSUMME_2, NSUMME_3, NSUMME,
                  MSUMME_0, MSUMME_1, MSUMME_2, MSUMME_3, MSUMME,
                  BSUMME_0, BSUMME_1, BSUMME_2, BSUMME_3, BSUMME,
                  ERSTELLT, ERST_NAME,
                  KUN_NUM, KUN_ANREDE,
                  KUN_NAME1, KUN_NAME2, KUN_NAME3, KUN_ABTEILUNG,
                  KUN_STRASSE, KUN_HAUSNR, KUN_ADRESSZUSATZ,
                  KUN_LAND, KUN_PLZ, KUN_ORT, KUN_UST_NUM,
                  USR1, USR2, KOPFTEXT, FUSSTEXT, PROJEKT, ORGNUM,
                  LIEF_AB, BEST_NAME, INFO,
                  KUN_ADDR_ID,
                  LIEF_ANREDE, LIEF_NAME1, LIEF_NAME2, LIEF_NAME3,
                  LIEF_ABTEILUNG, LIEF_STRASSE, LIEF_HAUSNR,
                  LIEF_ADRESSZUSATZ, LIEF_LAND, LIEF_PLZ, LIEF_ORT,
                  FIRMA_ID,
                  ZAHLART_NAME, ZAHLART_KURZ, ZAHLART_LANG,
                  LIEFART_NAME, LIEFART_LANG,
                  LIEF_AGB, JSONDATEN,
                  HASHSUM
                ) VALUES (
                  1, %s, %s, %s, %s,
                  %s, %s, %s,
                  '€', 1.0,
                  %s, %s, %s,
                  2, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s,
                  %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, %s, %s,
                  '', '', '', '', '', '',
                  '', '', '',
                  -1,
                  '', '', '', '',
                  '', '', '',
                  '', '', '', '',
                  %s,
                  %s, %s, %s,
                  %s, %s,
                  '', '',
                  '$$'
                )
            """, (
                ma_id if ma_id is not None else -1,
                int(cao_lief), belegnum, heute,
                int(lief_adr.get('LIEF_LIEFART') or -1),
                int(lief_adr.get('LIEF_ZAHLART') or -1),
                gegenkonto,
                # SOLL-Felder
                soll_stage, soll_skonto, soll_ntage,
                # GEWICHT (Header-Summe)
                round(gewicht_total, 4),
                # MWST_x + AT_MWST
                mwst_0, mwst_1, mwst_2, mwst_3, at_mwst,
                # NSUMME_0..3 + Gesamt
                round(n_summen[0], 2), round(n_summen[1], 2),
                round(n_summen[2], 2), round(n_summen[3], 2),
                nsumme,
                # MSUMME_0..3 + Gesamt
                round(m_summen[0], 2), round(m_summen[1], 2),
                round(m_summen[2], 2), round(m_summen[3], 2),
                msumme,
                # BSUMME_0..3 + Gesamt
                b_summen[0], b_summen[1], b_summen[2], b_summen[3],
                bsumme,
                heute, (ma_name or 'CAO-XT')[:100],
                # KUN_*-Snapshot der Lieferanten-Adresse
                _s(lief_adr.get('KUNNUM2') or ''),
                _s(lief_adr.get('ANREDE')),
                _s(lief_adr.get('NAME1')),
                _s(lief_adr.get('NAME2')),
                _s(lief_adr.get('NAME3')),
                '',  # KUN_ABTEILUNG (haben wir nicht in ADRESSEN)
                _s(lief_adr.get('STRASSE')),
                _s(lief_adr.get('HAUSNR')),
                _s(lief_adr.get('ADRESSZUSATZ')),
                _s(lief_adr.get('LAND') or 'DE'),
                _s(lief_adr.get('PLZ')),
                _s(lief_adr.get('ORT')),
                _s(lief_adr.get('UST_NUM')),
                # FIRMA_ID
                firma_id,
                # ZAHLART/LIEFART Texte
                _s(zahlart_data.get('NAME')),
                _s(zahlart_data.get('TEXT_KURZ')),
                _s(zahlart_data.get('TEXT_LANG')),
                _s(liefart_data.get('NAME')),
                _s(liefart_data.get('TEXT_LANG')),
            ))
            ekbestell_rec_id = cur.lastrowid

            # EKBESTELL_POS pro Position. WICHTIG: BELEGNUM, ADDR_ID
            # werden in jede Position dupliziert (CAO-Konvention zur
            # schnellen Abfrage ohne JOIN). Alle text-Felder mit ''
            # default — CAO selbst schreibt nie NULL in optionale
            # varchar-Spalten.
            for p in pos_daten:
                cur.execute("""
                    INSERT INTO EKBESTELL_POS (
                      EKBESTELL_ID, BELEGNUM, ADDR_ID,
                      POSITION, VIEW_POS,
                      WARENGRUPPE, ARTIKELTYP,
                      ARTIKEL_ID, ARTNUM, BARCODE, MATCHCODE,
                      LAENGE, BREITE, HOEHE, GROESSE, DIMENSION,
                      GEWICHT, ME_EINHEIT,
                      PR_EINHEIT, VPE, MENGE,
                      EPREIS, GPREIS,
                      STEUER_CODE, ALTTEIL_PROZ, ALTTEIL_FLAG,
                      GEGENKTO, BRUTTO_FLAG, EKEINGANG,
                      BEZEICHNUNG, BEZEICHNUNG_LAND,
                      KURZBEZEICHNUNG, KURZBEZEICHNUNG_LAND,
                      WARENGRUPPENNAME,
                      LIEFARTNUM, LIEFPREIS, GLIEFPREIS,
                      PROJEKTPREIS,
                      ERSTELLT, ERST_NAME, ME_CODE,
                      LAGER_ID, FREITEXT, FREITEXT_LAND,
                      FARBE, MATERIAL,
                      STADIUM
                    ) VALUES (
                      %s, %s, %s,
                      %s, %s,
                      %s, 'N',
                      %s, %s, %s, %s,
                      '', '', '', '', '',
                      %s, %s,
                      1.000, %s, %s,
                      %s, %s,
                      %s, 0.00, 'N',
                      %s, 'N', 'N',
                      %s, '',
                      %s, '',
                      %s,
                      %s, %s, %s,
                      'N',
                      NOW(), %s, %s,
                      -2, '', '',
                      '', '',
                      2
                    )
                """, (
                    ekbestell_rec_id, belegnum, int(cao_lief),
                    p['pos_nr'], str(p['pos_nr']),
                    p['wgr'],
                    p['artikel_id'],
                    (p['artnum'] or '')[:100],
                    (p['barcode'] or '')[:20],
                    (p['matchcode'] or '')[:255],
                    p['gewicht'],
                    (p['me_einheit'] or '')[:50],
                    int(p['vpe_lief']) if p['vpe_lief'] else 1,
                    p['menge'],
                    p['epreis'], p['gpreis'],
                    p['st_code'],
                    p['aufw_kto'],
                    (p['bezeichnung'] or ''),
                    (p['kurzname'] or '')[:150],
                    (p['wgr_name'] or '')[:250],
                    (p['liefartnum'] or '')[:100],
                    p['epreis'],   # LIEFPREIS = Stueck-EK lt. Lieferant
                    p['gpreis'],   # GLIEFPREIS = Gesamt lt. Lieferant
                    (ma_name or 'CAO-XT')[:100],
                    (p['me_code'] or '')[:5],
                ))

            # XT-Bestellung mit CAO-IDs verknuepfen
            cur.execute("""
                UPDATE XT_EINKAUF_BESTELLUNG
                   SET CAO_EKBESTELL_REC_ID = %s,
                       CAO_BELEGNUM         = %s
                 WHERE REC_ID = %s
            """, (ekbestell_rec_id, belegnum, int(bestellung_rec_id)))
        return {
            'ok':              True,
            'dry_run':         False,
            'belegnum':        belegnum,
            'ekbestell_rec_id': ekbestell_rec_id,
            'positions':       len(pos_daten),
            'skipped':         skipped,
            'nsumme':          nsumme,
            'msumme':          msumme,
            'bsumme':          bsumme,
            'lief_name':       lief_adr.get('NAME1') or '?',
            'fehler':          fehler,
        }
    except Exception as exc:
        log.exception('cao_sync_ekbestell rec=%s', bestellung_rec_id)
        return {'ok': False, 'msg': f'CAO-Sync: {str(exc)[:300]}',
                'fehler': [{'msg': str(exc)}]}
