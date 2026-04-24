"""
Admin-App: Stammdaten → Mittagstisch.

Read-only-Status der Mittagstisch-Konfiguration. Der Mittagstisch
selbst lebt in der Kiosk-App und synchronisiert mit einem Google
Sheet via Service-Account-Credentials. Die Admin-Seite zeigt:

- Welche Konfigurationswerte in ``kiosk-app/app/config_local.py``
  gesetzt sind (``MITTAGSTISCH_SPREADSHEET_ID``,
  ``MITTAGSTISCH_CREDENTIALS_FILE``).
- Ob die Credentials-JSON-Datei existiert, wie gross und wie alt.
- URL zum Kiosk-Endpoint ``/mittagstisch`` (sofern Kiosk-URL-Env
  gesetzt ist), damit der Admin mit einem Klick die fertige
  Anzeige oeffnen kann.

Bewusst NICHT enthalten:
- Direkter gspread-Zugriff vom Admin. Das Feature lebt im Kiosk,
  wir duplizieren die Credentials nicht in einer zweiten Laufzeit.
- Schreiben der Config. Config_local ist Dev-Overlay, nicht in Git.
  Aenderung per SSH / Editor auf dem Zielgeraet.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from typing import Any

_HIER = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HIER, '..', '..'))
_KIOSK_CONFIG_LOCAL = os.path.join(
    _REPO_ROOT, 'kiosk-app', 'app', 'config_local.py')
_KIOSK_APP_DIR = os.path.join(_REPO_ROOT, 'kiosk-app', 'app')

log = logging.getLogger(__name__)


_RE_SPREADSHEET = re.compile(
    r"""^\s*MITTAGSTISCH_SPREADSHEET_ID\s*=\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_RE_CREDENTIALS = re.compile(
    r"""^\s*MITTAGSTISCH_CREDENTIALS_FILE\s*=\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _lies_config_local() -> dict[str, str]:
    """Liest die zwei Mittagstisch-Werte aus kiosk-app/app/config_local.py.

    Nutzt einen Regex statt das Modul zu importieren, weil config_local
    auch DB-Passworte enthaelt und wir nicht mehr in den Speicher ziehen
    muessen als noetig. Zurueck kommen nur die zwei relevanten Felder.
    """
    out = {'spreadsheet_id': '', 'credentials_file': ''}
    if not os.path.isfile(_KIOSK_CONFIG_LOCAL):
        return out
    try:
        with open(_KIOSK_CONFIG_LOCAL, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        log.warning('config_local nicht lesbar: %s', e)
        return out
    m1 = _RE_SPREADSHEET.search(text)
    m2 = _RE_CREDENTIALS.search(text)
    if m1:
        out['spreadsheet_id'] = m1.group(1).strip()
    if m2:
        out['credentials_file'] = m2.group(1).strip()
    return out


def _credentials_datei_info(pfad: str) -> dict[str, Any]:
    """Resolve + stat: existiert? Groesse, mtime. Ohne Inhalt zu laden."""
    if not pfad:
        return {'pfad_roh': '', 'pfad_absolut': '',
                'existiert': False, 'groesse': 0, 'mtime': '',
                'alter_tage': None}
    absolut = pfad
    if not os.path.isabs(absolut):
        absolut = os.path.normpath(os.path.join(_KIOSK_APP_DIR, pfad))
    existiert = os.path.isfile(absolut)
    groesse = 0
    mtime = ''
    alter_tage: int | None = None
    if existiert:
        try:
            st = os.stat(absolut)
            groesse = st.st_size
            dt = datetime.fromtimestamp(st.st_mtime)
            mtime = dt.isoformat(sep=' ', timespec='seconds')
            alter_tage = (datetime.now() - dt).days
        except Exception as e:
            log.warning('stat(%s) fehlgeschlagen: %s', absolut, e)
    return {
        'pfad_roh':     pfad,
        'pfad_absolut': absolut,
        'existiert':    existiert,
        'groesse':      groesse,
        'mtime':        mtime,
        'alter_tage':   alter_tage,
    }


def status() -> dict[str, Any]:
    """Liefert die komplette Mittagstisch-Info fuer die Admin-Seite.

    Rueckgabe::

        {
          'config_local_pfad':    str,
          'config_local_exists':  bool,
          'spreadsheet_id':       str,
          'spreadsheet_url':      str,    # https://docs.google.com/... | ''
          'credentials':          { pfad_roh, pfad_absolut, existiert,
                                    groesse, mtime, alter_tage },
          'kiosk_url':            str,    # aus config.KIOSK_URL/KIOSK_PORT
          'kiosk_mittagstisch_url': str,  # .../mittagstisch
        }
    """
    cfg = _lies_config_local()
    sid = cfg['spreadsheet_id']
    cred = _credentials_datei_info(cfg['credentials_file'])

    spreadsheet_url = (
        f'https://docs.google.com/spreadsheets/d/{sid}/edit' if sid else ''
    )

    # Kiosk-URL aus Admin-Config (env KIOSK_URL oder Port-Default).
    try:
        import config as _admin_cfg
        kiosk_url_basis = (
            _admin_cfg.KIOSK_URL or f'http://localhost:{_admin_cfg.KIOSK_PORT}'
        )
    except Exception:
        kiosk_url_basis = 'http://localhost:5001'
    kiosk_mittagstisch_url = kiosk_url_basis.rstrip('/') + '/mittagstisch'

    return {
        'config_local_pfad':    _KIOSK_CONFIG_LOCAL,
        'config_local_exists':  os.path.isfile(_KIOSK_CONFIG_LOCAL),
        'spreadsheet_id':       sid,
        'spreadsheet_url':      spreadsheet_url,
        'credentials':          cred,
        'kiosk_url':            kiosk_url_basis,
        'kiosk_mittagstisch_url': kiosk_mittagstisch_url,
    }
