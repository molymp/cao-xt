"""Watchdog fuer den HACCP-Poller.

Kann von cron minutenweise gestartet werden. Liest den Heartbeat aus
``XT_HACCP_POLLER_STATUS``; ist der letzte Lauf aelter als der konfigurierte
Grenzwert oder steht ``TFA_OK = 0``, geht eine Mail an die Stufe-1-Empfaenger
der Alarmkette.

Start:
    python -m modules.haccp.watchdog [--max-alter-min 10] [--cooldown-min 60]
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, 'orga-app', 'app'))
sys.path.insert(0, _REPO_ROOT)

import config as wc  # noqa: E402

from common.db import init_pool  # noqa: E402
from common.email import email_senden  # noqa: E402
from modules.haccp import models as m  # noqa: E402


log = logging.getLogger('haccp.watchdog')


def _alter_min(ts: datetime | None, jetzt: datetime) -> float:
    if ts is None:
        return 10 ** 9
    return (jetzt - ts).total_seconds() / 60


def pruefen(max_alter_min: int, cooldown_min: int) -> int:
    """Liefert Exit-Code: 0 = OK, 1 = Alarm gesendet, 2 = Alarm unterdrueckt (cooldown),
    3 = kein Heartbeat jemals."""
    jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
    status = m.poller_status_lesen()
    if not status:
        _alarm_mailen('Poller noch nie gelaufen',
                      'XT_HACCP_POLLER_STATUS enthaelt keinen Eintrag.')
        return 3

    alter_run = _alter_min(status['LAST_RUN_AT'], jetzt)
    alter_success = _alter_min(status['LAST_SUCCESS_AT'], jetzt)
    tfa_ok = bool(status['TFA_OK'])

    # Cooldown: nicht spammen. WATCHDOG_ALARM_AT enthaelt letzten Alarm.
    alter_letzter_alarm = _alter_min(status.get('WATCHDOG_ALARM_AT'), jetzt)

    problem = None
    if alter_run > max_alter_min:
        problem = (f'Poller-Heartbeat zu alt ({alter_run:.0f} min, '
                   f'Limit {max_alter_min} min).')
    elif not tfa_ok:
        problem = (f'Letzter TFA-Abruf fehlgeschlagen: '
                   f'{status.get("LAST_ERROR") or "—"} '
                   f'(letzter Erfolg vor {alter_success:.0f} min).')

    if not problem:
        log.info('OK (run vor %.0f min, success vor %.0f min)',
                 alter_run, alter_success)
        return 0

    if alter_letzter_alarm < cooldown_min:
        log.warning('Problem erkannt (%s), aber Cooldown aktiv '
                    '(%.0f < %s min).', problem, alter_letzter_alarm, cooldown_min)
        return 2

    details = (
        f"Host: {status.get('HOSTNAME') or '—'}\n"
        f"Letzter Lauf:    {status['LAST_RUN_AT']}  (vor {alter_run:.0f} min)\n"
        f"Letzter Erfolg:  {status.get('LAST_SUCCESS_AT') or '—'}\n"
        f"TFA_OK:          {tfa_ok}\n"
        f"Letzter Fehler:  {status.get('LAST_ERROR') or '—'}\n"
        f"Zyklus-Count:    {status['ZYKLUS_COUNT']}\n"
    )
    _alarm_mailen(problem, details)
    m.poller_watchdog_alarm_markieren()
    return 1


def _alarm_mailen(kurz: str, details: str) -> None:
    kette = [e for e in m.alarmkette_aktiv() if int(e['STUFE']) == 1]
    if not kette:
        log.warning('Kein Stufe-1-Empfaenger konfiguriert — keine Mail gesendet.')
        return
    betreff = f'[HACCP Watchdog] {kurz}'
    text = (f'HACCP-Poller meldet ein Problem.\n\n{kurz}\n\n{details}\n\n'
            f'Check von {socket.gethostname()} um '
            f'{datetime.now(timezone.utc).replace(tzinfo=None).isoformat()} UTC.\n')
    for e in kette:
        r = email_senden(e['EMAIL'], betreff, text)
        log.info('Watchdog-Mail an %s: %s', e['EMAIL'], r.get('modus'))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
    )
    p = argparse.ArgumentParser()
    p.add_argument('--max-alter-min', type=int,
                   default=int(os.environ.get(
                       'HACCP_WATCHDOG_MAX_ALTER_MIN',
                       max(10, wc.HACCP_POLL_INTERVALL_S // 60 * 3))))
    p.add_argument('--cooldown-min', type=int,
                   default=int(os.environ.get(
                       'HACCP_WATCHDOG_COOLDOWN_MIN', 60)))
    args = p.parse_args()

    init_pool('haccp_watchdog_pool', pool_size=1, db_config={
        'host': wc.DB_HOST, 'port': wc.DB_PORT,
        'name': wc.DB_NAME, 'user': wc.DB_USER, 'password': wc.DB_PASSWORD,
    })
    return pruefen(args.max_alter_min, args.cooldown_min)


if __name__ == '__main__':
    sys.exit(main())
