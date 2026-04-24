"""
Admin-App: System -> Dorfkern-Rechte (Rolle x Permission-Objekt-Matrix).

Granulares Rechte-Management fuer die Dorfkern-Apps. Aufbauend auf
``common.permission``:
- ``DORFKERN_PERMISSION_OBJEKT``: Katalog der schuetzbaren Objekte
- ``DORFKERN_ROLLE_PERMISSION``: Rolle -> Objekt -> RECHT-Zuordnung

Die Rollen kommen dynamisch aus ``CAO.BENUTZERRECHTE`` (Gruppen-Definition
per MODUL_ID=0, SUBMODUL_ID=0, USER_ID=-1). ``Administratoren`` sind
implizit auf allen Objekten berechtigt und werden in der Matrix als
read-only angezeigt.
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

# Gueltige Recht-Werte in der UI. '' = kein Eintrag in DORFKERN_ROLLE_PERMISSION
# (= kein Zugriff). 'BEIDES' ist Default fuer UNTERSCHEIDUNG='KEINE'-Objekte.
_VALID_RECHTE_UI = ('', 'LESEN', 'PFLEGEN', 'BEIDES')


def _rollen_laden() -> list[str]:
    """Liest alle Rollen aus CAO BENUTZERRECHTE.

    Gruppendefinitionen haben USER_ID=-1 und MODUL_ID=0/SUBMODUL_ID=0 –
    genau die Zeilen, die cao_admin.exe beim Anlegen einer Gruppe
    schreibt.
    """
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT DISTINCT MODUL_NAME AS rolle
                  FROM BENUTZERRECHTE
                 WHERE USER_ID = -1
                   AND MODUL_ID = 0
                   AND SUBMODUL_ID = 0
                   AND MODUL_NAME IS NOT NULL
                   AND MODUL_NAME != ''
                 ORDER BY MODUL_NAME
            """)
            rows = cur.fetchall() or []
    except Exception as exc:
        log.warning('Rollen-Lookup fehlgeschlagen: %s', exc)
        return []
    return [str(r.get('rolle')).strip()
            for r in rows if r.get('rolle')]


def matrix() -> dict[str, Any]:
    """Liefert die komplette Rechte-Matrix fuer die Admin-UI.

    Rueckgabe::

        {
          'rollen': [
            {'name': 'Administratoren', 'admin': True},   # immer als erstes
            {'name': 'Geschäftsführung', 'admin': False},
            ...
          ],
          'objekte': [
            {
              'key': 'kiosk.backwaren',
              'app': 'KIOSK',
              'bezeichnung': '...',
              'beschreibung': '...',
              'unterscheidung': 'KEINE'|'LESE_PFLEGE',
            },
            ...
          ],
          # Lookup fuer Zellen: rechte[rolle][objekt_key] = 'BEIDES'|'LESEN'|...
          # Fehlende Zellen = kein Eintrag (= kein Zugriff).
          'rechte': {
            'Ladenleitung': {'kasse.storno': 'BEIDES', ...},
            ...
          },
          'recht_optionen': {
            'KEINE':        ['', 'BEIDES'],
            'LESE_PFLEGE':  ['', 'LESEN', 'PFLEGEN', 'BEIDES'],
          },
        }
    """
    # Objekte: gruppiert nach APP, in der Reihenfolge aus _SEED_OBJEKTE
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG,
                       UNTERSCHEIDUNG
                  FROM DORFKERN_PERMISSION_OBJEKT
                 ORDER BY APP, OBJEKT_KEY
            """)
            objekt_rows = cur.fetchall() or []
    except Exception as exc:
        log.warning('Objekt-Lookup fehlgeschlagen: %s', exc)
        objekt_rows = []

    objekte = [
        {
            'key':            str(r.get('OBJEKT_KEY') or '').strip(),
            'app':            str(r.get('APP') or '').upper(),
            'bezeichnung':    str(r.get('BEZEICHNUNG') or '').strip(),
            'beschreibung':   (r.get('BESCHREIBUNG') or '').strip() or '',
            'unterscheidung': str(r.get('UNTERSCHEIDUNG') or 'KEINE').upper(),
        }
        for r in objekt_rows
    ]

    # Rollen: Administratoren immer als erstes, Rest alphabetisch
    cao_rollen = _rollen_laden()
    admin_name = _perm.ROLLE_ADMIN
    if admin_name in cao_rollen:
        cao_rollen.remove(admin_name)
    rollen = [{'name': admin_name, 'admin': True}] + [
        {'name': r, 'admin': False} for r in cao_rollen
    ]

    # Aktuelle Zuordnungen
    rechte: dict[str, dict[str, str]] = {}
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT ROLLE, OBJEKT_KEY, RECHT
                  FROM DORFKERN_ROLLE_PERMISSION
            """)
            for r in cur.fetchall() or []:
                rolle = str(r.get('ROLLE') or '').strip()
                key   = str(r.get('OBJEKT_KEY') or '').strip()
                recht = str(r.get('RECHT') or '').upper()
                if rolle and key:
                    rechte.setdefault(rolle, {})[key] = recht
    except Exception as exc:
        log.warning('Rolle-Permission-Lookup fehlgeschlagen: %s', exc)

    return {
        'rollen':  rollen,
        'objekte': objekte,
        'rechte':  rechte,
        'recht_optionen': {
            'KEINE':       ['', 'BEIDES'],
            'LESE_PFLEGE': ['', 'LESEN', 'PFLEGEN', 'BEIDES'],
        },
    }


def zelle_setzen(rolle: str, objekt_key: str, recht: str) -> dict[str, Any]:
    """Aendert eine einzelne Matrix-Zelle.

    Args:
        rolle:      Name der CAO-Rolle (muss in BENUTZERRECHTE existieren).
        objekt_key: OBJEKT_KEY aus DORFKERN_PERMISSION_OBJEKT.
        recht:      '' | 'LESEN' | 'PFLEGEN' | 'BEIDES'.
                    ''  -> Eintrag loeschen (=> kein Zugriff).
                    Rest -> UPSERT mit dem gewaehlten Recht.

    Die Admin-Rolle kann nicht ueber dieses API veraendert werden
    (redundant: sie hat implizit alles).
    """
    rolle = (rolle or '').strip()
    objekt_key = (objekt_key or '').strip()
    recht = (recht or '').strip().upper()

    if not rolle:
        return {'ok': False, 'msg': 'Rolle fehlt.'}
    if rolle == _perm.ROLLE_ADMIN:
        return {'ok': False,
                'msg': f'Rolle {rolle!r} ist implizit auf allen Objekten '
                       f'berechtigt; keine Matrix-Eintraege erforderlich.'}
    if not objekt_key:
        return {'ok': False, 'msg': 'Objekt-Key fehlt.'}
    if recht not in _VALID_RECHTE_UI:
        return {'ok': False,
                'msg': f'Ungueltiges Recht {recht!r}. '
                       f'Erlaubt: {", ".join(_VALID_RECHTE_UI) or "(leer)"}'}

    # Validieren, dass Objekt existiert und Recht zur Unterscheidung passt
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT UNTERSCHEIDUNG FROM DORFKERN_PERMISSION_OBJEKT "
                "WHERE OBJEKT_KEY = %s",
                (objekt_key,))
            row = cur.fetchone()
    except Exception as exc:
        return {'ok': False, 'msg': f'DB-Fehler: {exc}'}
    if not row:
        return {'ok': False, 'msg': f'Unbekanntes Objekt: {objekt_key}'}

    unterscheidung = str(row.get('UNTERSCHEIDUNG') or 'KEINE').upper()
    if unterscheidung == 'KEINE' and recht in ('LESEN', 'PFLEGEN'):
        return {'ok': False,
                'msg': (f'Objekt {objekt_key!r} unterscheidet nicht '
                        f'zwischen Lesen/Pflegen. '
                        f'Setze BEIDES oder leer.')}

    try:
        if recht == '':
            _perm.loesche_rolle_permission(rolle, objekt_key)
        else:
            _perm.set_rolle_permission(rolle, objekt_key, recht)
    except Exception as exc:
        return {'ok': False, 'msg': f'Speichern fehlgeschlagen: {exc}'}
    return {'ok': True}
