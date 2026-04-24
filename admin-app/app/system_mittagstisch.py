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

import json
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

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import konfig as _konfig  # noqa: E402

log = logging.getLogger(__name__)


# Schluessel in DORFKERN_KONFIG (Kategorie MITTAGSTISCH)
KEY_SPREADSHEET   = 'mittagstisch.spreadsheet_id'
KEY_CREDENTIALS   = 'mittagstisch.credentials_json'


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


def _db_spreadsheet_id() -> str:
    wert = _konfig.get(KEY_SPREADSHEET, default=None)
    return str(wert).strip() if wert else ''


def _db_credentials_dict() -> dict | None:
    """Liest das Credentials-JSON aus DORFKERN_KONFIG.

    Wir speichern es als SECRET (Klartext-TEXT in der DB), aber parsen hier
    zu einem dict, damit die UI einfache Sanity-Checks anzeigen kann
    (Typ = service_account, welche Mail-Adresse, welches Projekt).
    Rueckgabe ``None`` wenn nicht gesetzt oder kein valides JSON.
    """
    roh = _konfig.get(KEY_CREDENTIALS, default=None)
    if not roh:
        return None
    try:
        return json.loads(roh)
    except (TypeError, ValueError):
        return None


def status() -> dict[str, Any]:
    """Liefert die komplette Mittagstisch-Info fuer die Admin-Seite.

    Primaer-Quelle ist DORFKERN_KONFIG, wenn dort Werte gesetzt sind.
    Sonst faellt die Anzeige auf die bisherige kiosk-app/config_local
    zurueck. So sind Alt-Installationen weiter sichtbar und die UI
    zeigt, woher die Werte kommen (``quelle`` pro Feld).

    Rueckgabe::

        {
          'config_local_pfad':    str,
          'config_local_exists':  bool,
          'spreadsheet_id':       str,
          'spreadsheet_id_quelle': 'db'|'config_local'|'leer',
          'spreadsheet_url':      str,
          'credentials':          { pfad_roh, pfad_absolut, existiert,
                                    groesse, mtime, alter_tage,
                                    quelle: 'db'|'file'|'leer',
                                    json_sanity: None|{typ, email, project_id},
                                    json_set:  bool },
          'kiosk_url':            str,
          'kiosk_mittagstisch_url': str,
        }
    """
    cfg = _lies_config_local()
    # Spreadsheet-ID: DB gewinnt, dann config_local
    sid_db = _db_spreadsheet_id()
    sid_cl = cfg['spreadsheet_id']
    if sid_db:
        sid, sid_quelle = sid_db, 'db'
    elif sid_cl:
        sid, sid_quelle = sid_cl, 'config_local'
    else:
        sid, sid_quelle = '', 'leer'

    # Credentials: DB-JSON gewinnt; sonst Datei aus config_local
    cred_dict = _db_credentials_dict()
    json_sanity = None
    if cred_dict:
        json_sanity = {
            'typ':        (cred_dict.get('type') or '').strip(),
            'email':      (cred_dict.get('client_email') or '').strip(),
            'project_id': (cred_dict.get('project_id') or '').strip(),
        }
    cred = _credentials_datei_info(cfg['credentials_file'])
    if cred_dict is not None:
        cred['quelle'] = 'db'
        cred['json_sanity'] = json_sanity
        cred['json_set'] = True
    elif cred['existiert']:
        cred['quelle'] = 'file'
        cred['json_sanity'] = None
        cred['json_set'] = False
    else:
        cred['quelle'] = 'leer'
        cred['json_sanity'] = None
        cred['json_set'] = False

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
        'spreadsheet_id_quelle': sid_quelle,
        'spreadsheet_url':      spreadsheet_url,
        'credentials':          cred,
        'kiosk_url':            kiosk_url_basis,
        'kiosk_mittagstisch_url': kiosk_mittagstisch_url,
    }


def speichern(*, spreadsheet_id: str | None = None,
              credentials_json: str | None = None,
              ma_id: int | None = None) -> dict[str, Any]:
    """Speichert Mittagstisch-Werte in DORFKERN_KONFIG.

    ``credentials_json`` wird als SECRET abgelegt. Falls der Client einen
    leeren String schickt, bleibt der vorherige Wert erhalten (wir
    ueberschreiben nur bei tatsaechlicher Eingabe – Service-Account-JSONs
    nuke-en kostet Zeit neu zu beschaffen).
    """
    geaendert = []
    try:
        if spreadsheet_id is not None:
            sid = str(spreadsheet_id).strip()
            _konfig.set(
                KEY_SPREADSHEET, sid, typ='STRING', kategorie='MITTAGSTISCH',
                beschreibung='Google-Sheets-ID mit dem Wochenplan',
                ma_id=ma_id,
            )
            geaendert.append('spreadsheet_id')
        if credentials_json is not None:
            raw = str(credentials_json).strip()
            if raw:
                # Vor dem Speichern parsen – sonst landet Unsinn in der DB
                try:
                    parsed = json.loads(raw)
                except (TypeError, ValueError) as e:
                    return {'ok': False,
                            'msg': f'Credentials-JSON ungueltig: {e}'}
                if parsed.get('type') != 'service_account':
                    return {'ok': False,
                            'msg': ('JSON ist kein Service-Account '
                                    '(type != "service_account").')}
                _konfig.set(
                    KEY_CREDENTIALS, raw, typ='SECRET',
                    kategorie='MITTAGSTISCH',
                    beschreibung='Google Service-Account Credentials (JSON)',
                    ma_id=ma_id,
                )
                geaendert.append('credentials_json')
            # leerer String -> nichts tun, alter Wert bleibt
    except Exception as e:
        log.exception('Mittagstisch-Konfig speichern fehlgeschlagen')
        return {'ok': False, 'msg': str(e)}
    return {'ok': True, 'geaendert': geaendert}


def credentials_loeschen(ma_id: int | None = None) -> dict[str, Any]:
    """Loescht explizit die Credentials aus der DB (leert den Wert).

    Wird von einem eigenen 'Credentials entfernen'-Button im UI getriggert,
    damit 'Leer lassen um nicht zu aendern' im Haupt-Formular nicht
    ueberladen wird.
    """
    try:
        _konfig.set(
            KEY_CREDENTIALS, '', typ='SECRET', kategorie='MITTAGSTISCH',
            beschreibung='Google Service-Account Credentials (JSON)',
            ma_id=ma_id,
        )
        return {'ok': True}
    except Exception as e:
        log.exception('Mittagstisch-Credentials loeschen fehlgeschlagen')
        return {'ok': False, 'msg': str(e)}
