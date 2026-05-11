"""One-Shot: Schulferien Bayern laden.

Quelle: openholidaysapi.org (Open-Data, kein API-Key).

Usage::

    python3 tools/schulferien_laden.py                   # 2018..heute+2
    python3 tools/schulferien_laden.py --von 2020 --bis 2027
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
from common.db import init_pool, get_db  # noqa: E402
from modules.orga.bestellvorschlag import schema, schulferien  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger(__name__)


def main() -> int:
    heute = _dt.date.today()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--von', type=int, default=2018)
    p.add_argument('--bis', type=int, default=heute.year + 2)
    args = p.parse_args()

    cfg = load_db_config('XT')
    init_pool('schulferien_pool', db_config=cfg)
    log.info('DB: %s@%s:%s/%s', cfg['user'], cfg['host'],
             cfg['port'], cfg['name'])

    schema.run_migration()

    for jahr in range(args.von, args.bis + 1):
        try:
            n = schulferien.jahr_laden(jahr)
            log.info('Jahr %d: %d Eintraege geladen', jahr, n)
        except Exception as exc:
            log.warning('Jahr %d fehlgeschlagen: %s', jahr, exc)

    with get_db() as cur:
        cur.execute("""
            SELECT COUNT(*) AS n, MIN(von_datum) AS frueh,
                   MAX(bis_datum) AS spaet
            FROM XT_SCHULFERIEN_BY
        """)
        s = cur.fetchone()
    log.info('XT_SCHULFERIEN_BY: %s Zeilen, %s .. %s',
             s.get('n'), s.get('frueh'), s.get('spaet'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
