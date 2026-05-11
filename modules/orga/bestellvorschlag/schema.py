"""
Schema-Migration fuer das Bestellvorschlag-Modul (Backwaren / Luidl).

Legt die XT-Tabellen fuer Wetter-Cache und Schulferien an. Feiertage
laufen ueber python-``holidays`` (kein Schema noetig).

Idempotent — wird aus dem Orga-App-Start ueber run_migration() einmal
ausgeloest.
"""
from __future__ import annotations

import logging

from common.db import get_db

log = logging.getLogger(__name__)


def run_migration() -> None:
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_WETTER_HABACH (
                  datum            DATE          NOT NULL PRIMARY KEY,
                  tmax_c           DECIMAL(4,1)  NULL,
                  tmin_c           DECIMAL(4,1)  NULL,
                  niederschlag_mm  DECIMAL(5,1)  NULL,
                  sonnenstunden    DECIMAL(4,1)  NULL,
                  windgeschw_kmh   DECIMAL(4,1)  NULL,
                  schnee_cm        DECIMAL(4,1)  NULL,
                  quelle           VARCHAR(40)   NOT NULL DEFAULT 'open-meteo',
                  geladen_am       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Tageswetter Habach (Lkr. WM, 47.7404N/11.3036E)'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_SCHULFERIEN_BY (
                  rec_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  jahr       SMALLINT     NOT NULL,
                  name       VARCHAR(60)  NOT NULL,
                  von_datum  DATE         NOT NULL,
                  bis_datum  DATE         NOT NULL,
                  quelle     VARCHAR(40)  NULL,
                  geladen_am DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE KEY uq_periode (von_datum, bis_datum, name),
                  INDEX idx_zeitraum (von_datum, bis_datum)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Schulferien Bayern, inklusiv Start- und End-Datum'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_BESTELLVORSCHLAG_FEEDBACK (
                  rec_id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  ziel_datum      DATE          NOT NULL,
                  erstellt_am     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  modell_version  VARCHAR(40)   NULL,
                  vorschlag_menge DECIMAL(10,2) NULL,
                  tatsaechlich    DECIMAL(10,2) NULL,
                  anmerkung       TEXT          NULL,
                  INDEX idx_datum (ziel_datum)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Lerndaten Bestellvorschlag vs. Realitaet'
            """)
        log.info('Migration: XT_WETTER_HABACH / XT_SCHULFERIEN_BY / '
                 'XT_BESTELLVORSCHLAG_FEEDBACK geprueft.')
    except Exception as exc:
        log.warning('Bestellvorschlag-Schema-Migration fehlgeschlagen: %s', exc)
