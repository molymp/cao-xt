"""Schema-Migration Orga/Stammdaten.

XT_ARTIKEL_PREISPLAN — Dorfkern-Erweiterung (NICHT CAO): mehrere
geplante Aktionen/Preisänderungen je Artikel zum Stichtag, inkl.
Schilddruck-Status. Idempotent, beim Blueprint-Aufbau ausgelöst.
"""
from __future__ import annotations

import logging

from common.db import get_db

log = logging.getLogger(__name__)


def run_migration() -> None:
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_ARTIKEL_PREISPLAN (
                  rec_id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                  artikel_id    INT          NOT NULL,
                  art           VARCHAR(10)  NOT NULL DEFAULT 'aktion',
                  vk1 DECIMAL(12,4) NULL, vk2 DECIMAL(12,4) NULL,
                  vk3 DECIMAL(12,4) NULL, vk4 DECIMAL(12,4) NULL,
                  vk5 DECIMAL(12,4) NULL,
                  gueltig_ab    DATE         NOT NULL,
                  gueltig_bis   DATE         NULL,
                  status        VARCHAR(12)  NOT NULL DEFAULT 'geplant',
                  angewendet_am DATETIME     NULL,
                  vorher_json   TEXT         NULL,
                  schild_gedruckt TINYINT(1) NOT NULL DEFAULT 0,
                  notiz         VARCHAR(255) NULL,
                  erstellt      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  erst_name     VARCHAR(50)  NULL,
                  geaend        DATETIME     NULL,
                  geaend_name   VARCHAR(50)  NULL,
                  KEY ix_artikel (artikel_id),
                  KEY ix_ab (gueltig_ab),
                  KEY ix_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Dorfkern: geplante Aktionen/Preisaenderungen je Artikel'
            """)
        log.info("Migration: XT_ARTIKEL_PREISPLAN geprueft.")
    except Exception:  # noqa: BLE001
        log.exception("XT_ARTIKEL_PREISPLAN-Migration fehlgeschlagen")
