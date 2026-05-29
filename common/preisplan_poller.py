"""One-shot-Entrypoint: fällige Preisplan-Einträge anwenden, abgelaufene
Aktionen beenden. Per systemd-Timer (täglich) aufgerufen — oder manuell:

    python -m common.preisplan_poller
"""
from __future__ import annotations

import logging

from common import preisplan


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    res = preisplan.faellige_anwenden()
    logging.getLogger(__name__).info(
        "Preisplan-Lauf: %s angewendet, %s beendet",
        res['angewendet'], res['beendet'])


if __name__ == '__main__':
    main()
