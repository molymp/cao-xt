"""
Admin-App: System → App-Steuerung.

Duenner Wrapper um ``installer/app_manager.py``, der die CLI-Aktionen
(start/stop/restart + status) ueber Web-Endpoints verfuegbar macht.
Haelt bewusst keinen eigenen State – alles kommt direkt aus dem
Manager (PID-File + Port-Check + daemon-alive-Check).

Nicht in diesem Modul enthalten:
- Installation / Update (dafuer gibt es /system/updates)
- Logs schreiben (nur lesen; Apps schreiben selbst via subprocess-log)
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

# installer/app_manager liegt im Repo-Root; admin-app sitzt eine Ebene
# darunter. Pfad defensiv ermitteln.
_HIER = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HIER, '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer import app_manager  # noqa: E402

log = logging.getLogger(__name__)


def liste() -> list[dict[str, Any]]:
    """Status aller Apps in der definierten Start-Reihenfolge."""
    ergebnis = []
    for eintrag in app_manager.status_all():
        name = eintrag['name']
        cfg  = app_manager.APPS.get(name, {})
        log_pfad = eintrag.get('log')
        # Log-Info (Groesse + Rotation-Backups) optional, bricht nicht
        log_info = None
        if log_pfad and hasattr(app_manager, 'log_info'):
            try:
                log_info = app_manager.log_info(log_pfad)
            except Exception:
                log_info = None
        ergebnis.append({
            'name':    name,
            'type':    eintrag.get('type', 'web'),
            'port':    eintrag.get('port'),
            'running': bool(eintrag.get('running')),
            'pid':     eintrag.get('pid'),
            'log':     log_pfad,
            'log_info': log_info,
            'beschreibung': _beschreibung(name),
            'app_dir': cfg.get('app_dir'),
            'module':  cfg.get('module'),
        })
    return ergebnis


def _beschreibung(name: str) -> str:
    return {
        'admin':        'Admin-App (Einstellungen, Stammdaten)',
        'orga':         'Orga-App (Personal, HACCP)',
        'kasse':        'Kassen-App (TSE, EC, Bondruck)',
        'kiosk':        'Kiosk-App (Touch-Selbstbedienung)',
        'haccp-poller': 'HACCP-Poller (TFA-API, zyklisch)',
    }.get(name, '')


def start(name: str) -> dict[str, Any]:
    """Startet eine App. Gibt Status + Erfolg zurueck."""
    if name not in app_manager.APPS:
        return {'ok': False, 'msg': f'Unbekannte App: {name}'}
    try:
        ok = app_manager.start_app(name, print_fn=lambda *a, **k: None)
        return {'ok': bool(ok), 'status': app_manager.status_app(name)}
    except Exception as e:
        log.exception('start %s fehlgeschlagen', name)
        return {'ok': False, 'msg': str(e)}


def stop(name: str) -> dict[str, Any]:
    """Stoppt eine App. Gibt Status zurueck."""
    if name not in app_manager.APPS:
        return {'ok': False, 'msg': f'Unbekannte App: {name}'}
    try:
        app_manager.stop_app(name, print_fn=lambda *a, **k: None)
        return {'ok': True, 'status': app_manager.status_app(name)}
    except Exception as e:
        log.exception('stop %s fehlgeschlagen', name)
        return {'ok': False, 'msg': str(e)}


def restart(name: str) -> dict[str, Any]:
    """Restart = stop + start, Eigen-Restart (admin) wird abgelehnt."""
    if name not in app_manager.APPS:
        return {'ok': False, 'msg': f'Unbekannte App: {name}'}
    if name == 'admin':
        # Wuerde sich selbst toeten – nicht sinnvoll ueber die UI.
        return {'ok': False,
                'msg': 'Admin-App kann sich nicht selbst neu starten. '
                       'Bitte via ./dorfkern-ctl restart admin.'}
    try:
        ok = app_manager.restart_app(name, print_fn=lambda *a, **k: None)
        return {'ok': bool(ok), 'status': app_manager.status_app(name)}
    except Exception as e:
        log.exception('restart %s fehlgeschlagen', name)
        return {'ok': False, 'msg': str(e)}


def log_tail(name: str, zeilen: int = 80) -> dict[str, Any]:
    """Liefert die letzten N Zeilen des App-Logs (ohne shell out)."""
    if name not in app_manager.APPS:
        return {'ok': False, 'msg': f'Unbekannte App: {name}'}
    pfad = app_manager.APPS[name].get('log')
    if not pfad or not os.path.isfile(pfad):
        return {'ok': True, 'zeilen': [], 'pfad': pfad}
    zeilen = max(1, min(500, int(zeilen)))
    try:
        # Tail ueber Byte-Offset: skaliert auch bei grossen Logs.
        with open(pfad, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # Schaetze: 200 Byte pro Zeile; lies 4x fuer Puffer.
            schritt = min(size, zeilen * 200 * 4)
            f.seek(size - schritt)
            daten = f.read()
        text = daten.decode('utf-8', errors='replace')
        letzte = text.splitlines()[-zeilen:]
        return {'ok': True, 'zeilen': letzte, 'pfad': pfad, 'groesse': size}
    except Exception as e:
        log.exception('log_tail %s fehlgeschlagen', name)
        return {'ok': False, 'msg': str(e)}
