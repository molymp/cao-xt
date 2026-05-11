"""Schema-Migration fuer Betriebserfolg-Modul.

Zwei Tabellen:
* XT_BETRIEBSERFOLG_MONAT — pro Monat eingegebene Werte (Verderb,
  MA-Stunden, Krankstunden, Fixkosten).
* Konfigurations-Defaults laufen ueber bestehende XT_EINSTELLUNGEN
  (Schluessel ``betrieb.*``).
"""
from __future__ import annotations

import logging

from common.db import get_db

log = logging.getLogger(__name__)

# Default-Werte fuer die XT_EINSTELLUNGEN (Schluessel: Wert)
KONFIG_DEFAULTS: dict[str, tuple[str, str]] = {
    'betrieb.rohertrag_pct':       ('30.00', 'Rohertragsquote in % vom Umsatz'),
    'betrieb.personalkosten_pct':  ('24.74', 'Personalkosten in % vom Umsatz'),
    'betrieb.sonst_kosten_pct':    ('10.12', 'sonstige Kosten in % vom Umsatz'),
    'betrieb.ideal_mai':           ('110.00', 'Ideal-MAI in EUR/Std'),
    'betrieb.max_mai':             ('234.54', 'Maximalwert MAI Betrieb in EUR/Std'),
    'betrieb.stundensatz_netto':   ('20.26', 'aktueller Stundensatz Netto in EUR/Std (Personalkosten-Brutto je MA-Std)'),
}


def run_migration() -> None:
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_BETRIEBSERFOLG_MONAT (
                  jahr             SMALLINT     NOT NULL,
                  monat            TINYINT      NOT NULL,
                  verderb_eur      DECIMAL(10,2) NULL DEFAULT 0,
                  ma_einsatz_std   DECIMAL(8,2)  NULL DEFAULT 0,
                  krankstunden     DECIMAL(8,2)  NULL DEFAULT 0,
                  fixkosten_eur    DECIMAL(10,2) NULL DEFAULT 0,
                  anmerkung        TEXT          NULL,
                  erfasst_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  erfasst_von      INT           NULL,
                  geaend_at        DATETIME      NULL ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (jahr, monat)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Monatliche Betriebserfolg-Eingabewerte'
            """)
            # Default-Einstellungen anlegen (nur wenn fehlend)
            for schl, (wert, _) in KONFIG_DEFAULTS.items():
                cur.execute(
                    "INSERT IGNORE INTO XT_EINSTELLUNGEN "
                    "(schluessel, wert) VALUES (%s, %s)",
                    (schl, wert))
        log.info('Migration: XT_BETRIEBSERFOLG_MONAT + Konfig-Defaults geprueft.')
    except Exception as exc:
        log.warning('Betriebserfolg-Migration fehlgeschlagen: %s', exc)
