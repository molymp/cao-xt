"""
Admin-App: System → Einkauf-Poller.

Read-only-Status des ``einkauf-poller``-Daemons:
- Heartbeat aus ``XT_EINKAUF_POLLER_STATUS`` (LAST_RUN_AT,
  LAST_SUCCESS_AT, GMAIL_OK, LAST_ERROR, ZYKLUS_COUNT, NEU_GEFUNDEN,
  HOSTNAME).
- Konfiguration: Poll-Intervall (DORFKERN_KONFIG einkauf.gmail.poll_min),
  Gmail-Verbundenheit (Refresh-Token gesetzt?).
- Daemon-Lauf-Status aus installer/app_manager (PID + alive-Check).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

_HIER = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HIER, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer import app_manager       # noqa: E402
from common import einkauf as _einkauf  # noqa: E402

log = logging.getLogger(__name__)


def _iso(dt: Any) -> str:
    if dt is None:
        return ''
    if hasattr(dt, 'isoformat'):
        return dt.isoformat(sep=' ', timespec='seconds')
    return str(dt)


def _sekunden_seit(dt: Any):
    if dt is None or not hasattr(dt, 'timestamp'):
        return None
    try:
        jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
        return int((jetzt - dt).total_seconds())
    except Exception:
        return None


def status() -> dict[str, Any]:
    """Liefert den kompletten Zustand fuer die Admin-Seite.

    Rueckgabe::

        {
          'daemon':    {running, pid, module, log},
          'heartbeat': {vorhanden, last_run_at, last_success_at, gmail_ok,
                        last_error, zyklus_count, neu_gefunden, hostname,
                        sekunden_seit_run, sekunden_seit_success},
          'konfig':    {poll_min, gmail_verbunden, gmail_user_email,
                        hinweis}
        }
    """
    # Heartbeat
    heart: dict[str, Any] = {
        'vorhanden':              False,
        'last_run_at':            '',
        'last_success_at':        '',
        'gmail_ok':               False,
        'last_error':             '',
        'zyklus_count':           None,
        'neu_gefunden':           None,
        'hostname':               '',
        'sekunden_seit_run':      None,
        'sekunden_seit_success':  None,
    }
    try:
        row = _einkauf.poller_status_lesen()
        if row:
            heart.update({
                'vorhanden':             True,
                'last_run_at':           _iso(row.get('LAST_RUN_AT')),
                'last_success_at':       _iso(row.get('LAST_SUCCESS_AT')),
                'gmail_ok':              bool(row.get('GMAIL_OK')),
                'last_error':            (row.get('LAST_ERROR') or '').strip(),
                'zyklus_count':          int(row.get('ZYKLUS_COUNT') or 0),
                'neu_gefunden':          int(row.get('NEU_GEFUNDEN') or 0),
                'hostname':              (row.get('HOSTNAME') or '').strip(),
                'sekunden_seit_run':     _sekunden_seit(row.get('LAST_RUN_AT')),
                'sekunden_seit_success': _sekunden_seit(row.get('LAST_SUCCESS_AT')),
            })
    except Exception as exc:
        log.warning('Einkauf-Heartbeat nicht lesbar: %s', exc)
        heart['last_error'] = f'Tabelle nicht lesbar: {exc}'

    # Daemon-Zustand
    try:
        daemon_stat = app_manager.status_app('einkauf-poller')
    except Exception as exc:
        log.warning('app_manager.status_app fehlgeschlagen: %s', exc)
        daemon_stat = {'running': False, 'pid': None, 'log': ''}

    daemon = {
        'running': bool(daemon_stat.get('running')),
        'pid':     daemon_stat.get('pid'),
        'module':  app_manager.APPS.get('einkauf-poller', {}).get('module', ''),
        'log':     daemon_stat.get('log', ''),
    }

    # Konfig
    gcfg = _einkauf.gmail_konfig()
    konfig = {
        'poll_min':         gcfg.get('poll_min'),
        'gmail_verbunden':  bool(gcfg.get('verbunden')),
        'gmail_user_email': gcfg.get('user_email') or '',
        'hinweis': (
            'Poll-Intervall aendern: Einkauf -> Lieferanten (Gmail-Karte). '
            'Aenderungen werden vom Daemon spaetestens beim naechsten '
            'Zyklus uebernommen, ein Restart ist nicht noetig.'
        ),
    }

    return {'daemon': daemon, 'heartbeat': heart, 'konfig': konfig}
