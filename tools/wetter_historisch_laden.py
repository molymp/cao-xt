"""One-Shot: Historische Wetterdaten Habach laden.

Quelle: Open-Meteo Archive (CC-BY 4.0, kein API-Key).
Zeitraum: per ``--von`` / ``--bis`` oder Default 2018-01-01 .. heute.

Usage::

    python3 tools/wetter_historisch_laden.py            # 2018-heute
    python3 tools/wetter_historisch_laden.py --von 2020-01-01
    python3 tools/wetter_historisch_laden.py --forecast # naechste 7 Tage
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config  # noqa: E402
from common.db import init_pool  # noqa: E402
from modules.orga.bestellvorschlag import schema, wetter  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger(__name__)


def _date(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--von', type=_date,
                   default=_dt.date(2018, 1, 1))
    p.add_argument('--bis', type=_date,
                   default=_dt.date.today())
    p.add_argument('--forecast', action='store_true',
                   help='Zusaetzlich 7 Tage Forecast holen')
    args = p.parse_args()

    cfg = load_db_config('XT')
    init_pool('wetter_pool', db_config=cfg)
    log.info('DB: %s@%s:%s/%s', cfg['user'], cfg['host'],
             cfg['port'], cfg['name'])

    schema.run_migration()

    log.info('Archive: %s .. %s', args.von, args.bis)
    # Open-Meteo Archive akzeptiert lange Zeitraeume, aber wir
    # batchen jahresweise — robuster bei einzelnem Fehler.
    total = 0
    jahr = args.von.year
    while jahr <= args.bis.year:
        s = max(args.von, _dt.date(jahr, 1, 1))
        e = min(args.bis, _dt.date(jahr, 12, 31))
        if s > e:
            jahr += 1
            continue
        try:
            n = wetter.archive_laden(s, e)
            total += n
        except Exception as exc:
            log.warning('Jahr %d fehlgeschlagen: %s', jahr, exc)
        jahr += 1

    if args.forecast:
        try:
            n = wetter.forecast_laden(tage=7)
            log.info('Forecast: %d Tage', n)
        except Exception as exc:
            log.warning('Forecast fehlgeschlagen: %s', exc)

    state = wetter.wetter_zaehler()
    log.info('XT_WETTER_HABACH: %s Zeilen, %s .. %s',
             state.get('n'), state.get('frueh'), state.get('spaet'))
    log.info('Geladen total: %d', total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
