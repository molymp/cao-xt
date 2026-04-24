"""
Admin-App: System -> Mitarbeiter.

Read-only Liste der CAO-Mitarbeiter mit:
- Login-Name, Anzeige-Name, MA-ID
- Aktiv-Flag (GUELTIG_BIS-Logik aus cao_rechte)
- CAO-Rolle (aus BENUTZERRECHTE-Gruppenname)
- Zaehler 'n von m' je Dorfkern-App pro Mitarbeiter
  (wieviele Permission-Objekte sind durch seine Rolle berechtigt)

Die Mitarbeiter-Stammdaten selbst werden in cao_admin.exe gepflegt
(Administratoren-Tab) – wir zeigen sie hier nur im Kontext
des Dorfkern-Rechtemanagements an.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from db import get_db

_HIER = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HIER, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common import permission as _perm  # noqa: E402

log = logging.getLogger(__name__)

_APPS = ('KIOSK', 'KASSE', 'ORGA', 'ADMIN')


def _rollen_rechte() -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """Liest alle Rolle-Permissions und Objekt-Katalog.

    Rueckgabe:
        rollen_rechte: {rolle: {objekt_key: 'BEIDES'|'LESEN'|'PFLEGEN'}}
        objekte_pro_app: {'KIOSK': [key, ...], 'KASSE': [...], ...}
    """
    rollen_rechte: dict[str, dict[str, str]] = {}
    objekte_pro_app: dict[str, list[str]] = {a: [] for a in _APPS}
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT OBJEKT_KEY, APP
                  FROM DORFKERN_PERMISSION_OBJEKT
                 ORDER BY APP, OBJEKT_KEY
            """)
            for r in cur.fetchall() or []:
                app = str(r.get('APP') or '').upper()
                key = str(r.get('OBJEKT_KEY') or '').strip()
                if app in objekte_pro_app and key:
                    objekte_pro_app[app].append(key)
            cur.execute("""
                SELECT ROLLE, OBJEKT_KEY, RECHT
                  FROM DORFKERN_ROLLE_PERMISSION
            """)
            for r in cur.fetchall() or []:
                rolle = str(r.get('ROLLE') or '').strip()
                key   = str(r.get('OBJEKT_KEY') or '').strip()
                recht = str(r.get('RECHT') or '').upper()
                if rolle and key:
                    rollen_rechte.setdefault(rolle, {})[key] = recht
    except Exception as exc:
        log.warning('Permission-Lookup fehlgeschlagen: %s', exc)
    return rollen_rechte, objekte_pro_app


def liste() -> list[dict[str, Any]]:
    """Alle aktiven und inaktiven Mitarbeiter mit Rolle + Rechte-Zaehler.

    Rueckgabe pro Eintrag::

        {
          'ma_id':         int,
          'login_name':    str,
          'anzeige_name':  str,
          'aktiv':         bool,        # GUELTIG_BIS leer/zukuenftig
          'rolle':         str,         # aus BENUTZERRECHTE-Gruppe
          'gruppen_id':    int,
          'ist_admin':     bool,        # rolle == 'Administratoren'
          'rechte_pro_app': {
            'KIOSK': {'erlaubt': int, 'gesamt': int, 'detail': [key, ...]},
            'KASSE': {...}, 'ORGA':  {...}, 'ADMIN': {...},
          },
        }
    """
    # Mitarbeiter + Gruppenzuordnung holen (via cao_rechte, um die
    # Logik fuer AKTIV/GUELTIG_BIS nicht zu duplizieren).
    try:
        import cao_rechte as _cr
        rows = _cr.mitarbeiter_mit_gruppen() or []
    except Exception as exc:
        log.warning('mitarbeiter_mit_gruppen: %s', exc)
        rows = []

    rollen_rechte, objekte_pro_app = _rollen_rechte()
    admin_rolle = _perm.ROLLE_ADMIN

    ergebnis = []
    for r in rows:
        rolle = (r.get('GRUPPEN_NAME') or '').strip()
        ist_admin = rolle == admin_rolle
        # Effektive Rechte: Administratoren haben alles;
        # sonst nur, was in DORFKERN_ROLLE_PERMISSION eingetragen ist.
        rolle_keys = set(rollen_rechte.get(rolle, {}).keys())
        rechte_pro_app: dict[str, Any] = {}
        for app in _APPS:
            gesamt = objekte_pro_app[app]
            if ist_admin:
                erlaubt_keys = list(gesamt)
            else:
                erlaubt_keys = [k for k in gesamt if k in rolle_keys]
            rechte_pro_app[app] = {
                'erlaubt':  len(erlaubt_keys),
                'gesamt':   len(gesamt),
                'detail':   erlaubt_keys,
            }
        ergebnis.append({
            'ma_id':         int(r.get('MA_ID') or 0),
            'login_name':    (r.get('LOGIN_NAME') or '').strip(),
            'anzeige_name':  (r.get('ANZEIGE_NAME') or '').strip(),
            'aktiv':         bool(r.get('AKTIV')),
            'rolle':         rolle or '—',
            'gruppen_id':    int(r.get('GRUPPEN_ID') or 0),
            'ist_admin':     ist_admin,
            'rechte_pro_app': rechte_pro_app,
        })
    # Aktive zuerst, dann alphabetisch nach Anzeigename
    ergebnis.sort(key=lambda e: (
        not e['aktiv'],
        (e['anzeige_name'] or e['login_name'] or '').lower(),
    ))
    return ergebnis
