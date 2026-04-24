"""
Admin-App: System → HACCP-Poller.

Read-only-Status des ``haccp-poller``-Daemons:
- Heartbeat aus ``XT_HACCP_POLLER_STATUS`` (LAST_RUN_AT, LAST_SUCCESS_AT,
  TFA_OK, LAST_ERROR, ZYKLUS_COUNT, NEU_ENTDECKT, HOSTNAME, WATCHDOG)
- Konfiguration aus Env-Vars (``TFA_API_KEY``, ``TFA_BASE_URL``,
  ``HACCP_POLL_INTERVALL_S``) – nur gesetzt/ungesetzt (API-Key wird
  maskiert; niemand braucht den Key in Klartext zurueck).
- Daemon-Lauf-Status aus installer/app_manager (PID + alive-Check).
- Ableitung: wann war der letzte Erfolgslauf, wie lange ist das her.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from db import get_db

_HIER = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HIER, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer import app_manager  # noqa: E402
from common import konfig as _konfig  # noqa: E402

log = logging.getLogger(__name__)


# Schluessel in DORFKERN_KONFIG (Kategorie HACCP)
KEY_API_KEY      = 'haccp.tfa_api_key'
KEY_BASE_URL     = 'haccp.tfa_base_url'
KEY_INTERVALL_S  = 'haccp.poll_intervall_s'

# Defaults, wenn weder DB noch Env gesetzt
DEFAULT_BASE_URL    = 'https://go.tfa.me'
DEFAULT_INTERVALL_S = 120


def effektive_konfig() -> dict[str, Any]:
    """Liefert die effektiven Konfigwerte mit Quelle.

    Priorisierungs-Reihenfolge pro Schluessel::

        1. DORFKERN_KONFIG (via common.konfig.get)
        2. Env-Variable (TFA_API_KEY, TFA_BASE_URL, HACCP_POLL_INTERVALL_S)
        3. Default

    Rueckgabe::

        {
          'tfa_api_key':     {'wert': str|None, 'quelle': 'db'|'env'|'default'},
          'tfa_base_url':    {'wert': str,      'quelle': ...},
          'poll_intervall_s':{'wert': int,      'quelle': ...},
        }
    """
    def aufl(key_db: str, env_name: str, default: Any, typ_cast):
        db_wert = _konfig.get(key_db, default=None)
        if db_wert is not None and db_wert != '':
            return {'wert': typ_cast(db_wert), 'quelle': 'db'}
        env_wert = os.environ.get(env_name, '')
        if env_wert:
            return {'wert': typ_cast(env_wert), 'quelle': 'env'}
        return {'wert': default, 'quelle': 'default'}

    return {
        'tfa_api_key':      aufl(KEY_API_KEY,     'TFA_API_KEY',
                                 None,                 lambda v: str(v)),
        'tfa_base_url':     aufl(KEY_BASE_URL,    'TFA_BASE_URL',
                                 DEFAULT_BASE_URL,     lambda v: str(v)),
        'poll_intervall_s': aufl(KEY_INTERVALL_S, 'HACCP_POLL_INTERVALL_S',
                                 DEFAULT_INTERVALL_S,  lambda v: int(v)),
    }


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _iso(dt: Any) -> str:
    if dt is None:
        return ''
    if hasattr(dt, 'isoformat'):
        return dt.isoformat(sep=' ', timespec='seconds')
    return str(dt)


def _sekunden_seit(dt: Any) -> int | None:
    if dt is None:
        return None
    if not hasattr(dt, 'timestamp'):
        return None
    try:
        # HACCP-Poller schreibt LAST_RUN_AT als naive UTC, hier auch naive UTC.
        jetzt = datetime.now(timezone.utc).replace(tzinfo=None)
        return int((jetzt - dt).total_seconds())
    except Exception:
        return None


def _maskiere_key(key: str) -> str:
    """'abcdef123456' -> 'abcd****3456'. Leer bleibt leer."""
    if not key:
        return ''
    if len(key) <= 8:
        return '*' * len(key)
    return f'{key[:4]}{"*" * (len(key) - 8)}{key[-4:]}'


def status() -> dict[str, Any]:
    """Liefert den kompletten Zustand fuer die Admin-Seite.

    Rueckgabe::

        {
          'daemon': {
            'running': bool, 'pid': int|None,
            'module': str,   'log': str,
          },
          'heartbeat': {
            'vorhanden':       bool,
            'last_run_at':     str,
            'last_success_at': str,
            'tfa_ok':          bool,
            'last_error':      str,
            'zyklus_count':    int | None,
            'neu_entdeckt':    int | None,
            'hostname':        str,
            'sekunden_seit_run':     int | None,
            'sekunden_seit_success': int | None,
            'watchdog_alarm_at':     str,
          },
          'konfig': {
            'tfa_base_url':      str,
            'tfa_api_key':       str,   # maskiert oder ''
            'tfa_api_key_set':   bool,
            'poll_intervall_s':  int,
            'hinweis':           str,   # Nutzer-Hilfe
          }
        }
    """
    # Heartbeat
    heart: dict[str, Any] = {
        'vorhanden':       False,
        'last_run_at':     '',
        'last_success_at': '',
        'tfa_ok':          False,
        'last_error':      '',
        'zyklus_count':    None,
        'neu_entdeckt':    None,
        'hostname':        '',
        'sekunden_seit_run':     None,
        'sekunden_seit_success': None,
        'watchdog_alarm_at':     '',
    }
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT * FROM XT_HACCP_POLLER_STATUS WHERE REC_ID = 1"
            )
            row = cur.fetchone()
        if row:
            heart.update({
                'vorhanden':              True,
                'last_run_at':            _iso(row.get('LAST_RUN_AT')),
                'last_success_at':        _iso(row.get('LAST_SUCCESS_AT')),
                'tfa_ok':                 bool(row.get('TFA_OK')),
                'last_error':             (row.get('LAST_ERROR') or '').strip(),
                'zyklus_count':           _int_oder_none(row.get('ZYKLUS_COUNT')),
                'neu_entdeckt':           _int_oder_none(row.get('NEU_ENTDECKT')),
                'hostname':               (row.get('HOSTNAME') or '').strip(),
                'sekunden_seit_run':      _sekunden_seit(row.get('LAST_RUN_AT')),
                'sekunden_seit_success':  _sekunden_seit(row.get('LAST_SUCCESS_AT')),
                'watchdog_alarm_at':      _iso(row.get('WATCHDOG_ALARM_AT')),
            })
    except Exception as e:
        log.warning('HACCP-Heartbeat nicht lesbar: %s', e)
        heart['last_error'] = f'Tabelle nicht lesbar: {e}'

    # Daemon-Zustand
    try:
        daemon_stat = app_manager.status_app('haccp-poller')
    except Exception as e:
        log.warning('app_manager.status_app fehlgeschlagen: %s', e)
        daemon_stat = {'running': False, 'pid': None, 'log': ''}

    daemon = {
        'running': bool(daemon_stat.get('running')),
        'pid':     daemon_stat.get('pid'),
        'module':  app_manager.APPS.get('haccp-poller', {}).get('module', ''),
        'log':     daemon_stat.get('log', ''),
    }

    # Konfig – primaer aus DB (DORFKERN_KONFIG), fallback Env, dann Default.
    eff = effektive_konfig()
    tfa_key = eff['tfa_api_key']['wert'] or ''
    konfig = {
        'tfa_base_url':     eff['tfa_base_url']['wert'],
        'tfa_api_key':      _maskiere_key(tfa_key),
        'tfa_api_key_set':  bool(tfa_key),
        'poll_intervall_s': eff['poll_intervall_s']['wert'],
        'quellen':          {
            'tfa_base_url':     eff['tfa_base_url']['quelle'],
            'tfa_api_key':      eff['tfa_api_key']['quelle'],
            'poll_intervall_s': eff['poll_intervall_s']['quelle'],
        },
        'hinweis':          (
            'Aenderungen greifen erst nach Neustart des '
            'haccp-poller-Daemons (System -> App-Steuerung).'
        ),
    }

    return {'daemon': daemon, 'heartbeat': heart, 'konfig': konfig}


def speichern(*, tfa_api_key: str | None = None,
              tfa_base_url: str | None = None,
              poll_intervall_s: int | None = None,
              ma_id: int | None = None) -> dict[str, Any]:
    """Speichert die drei Konfig-Werte in DORFKERN_KONFIG.

    Werte, die ``None`` sind, werden nicht angefasst. Leerer String loescht
    den Eintrag effektiv (wert='' -> Fallback auf Env/Default beim Lesen).
    """
    geaendert = []
    try:
        if tfa_api_key is not None:
            _konfig.set(
                KEY_API_KEY, tfa_api_key, typ='SECRET', kategorie='HACCP',
                beschreibung='TFA-Go API-Key fuer HACCP-Poller',
                ma_id=ma_id,
            )
            geaendert.append('tfa_api_key')
        if tfa_base_url is not None:
            _konfig.set(
                KEY_BASE_URL, tfa_base_url, typ='STRING', kategorie='HACCP',
                beschreibung=('TFA-Go API-Basis-URL (meist '
                              'https://go.tfa.me)'),
                ma_id=ma_id,
            )
            geaendert.append('tfa_base_url')
        if poll_intervall_s is not None:
            _konfig.set(
                KEY_INTERVALL_S, int(poll_intervall_s), typ='INT',
                kategorie='HACCP',
                beschreibung='Poll-Intervall in Sekunden (Empfehlung 60-300)',
                ma_id=ma_id,
            )
            geaendert.append('poll_intervall_s')
    except Exception as e:
        log.exception('HACCP-Konfig speichern fehlgeschlagen')
        return {'ok': False, 'msg': str(e)}
    return {'ok': True, 'geaendert': geaendert}
