"""
Laufzeit-Dispatch der App-Steuerung an systemctl.

Wird von ``installer/app_manager.py`` aufgerufen. Erkennt automatisch,
ob die ``dorfkern.target``-Unit als System-Service (root, /etc/systemd/system)
oder als User-Service (--user, ~/.config/systemd/user) installiert ist —
und benutzt im entsprechenden Modus die richtigen systemctl-Flags.

Ist gar keine Target-Unit da, liefert ``systemd_mode()`` None und der
Aufrufer faellt auf den Popen-Pfad (Dev-Ad-hoc) zurueck.

Wenn (versehentlich) BEIDE Modi installiert sind: User-Mode hat
Vorrang, weil das die natuerliche Erwartung in einer Login-Session ist.
Eine Warnung wandert ins Log.
"""
import logging
import os
import subprocess
import time
from functools import lru_cache
from typing import Dict, List, Optional

from . import units


log = logging.getLogger(__name__)

_SYSTEMCTL_TIMEOUT = 60   # einzelner systemctl-Aufruf
_WAIT_ACTIVE_SECS  = 60   # Default-Wartezeit bis "active"


def _systemctl_available() -> bool:
    """True wenn ``systemctl`` ueberhaupt im PATH ist."""
    try:
        subprocess.run(['systemctl', '--version'],
                       capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_unit(mode: str) -> bool:
    """True wenn dorfkern.target im gegebenen systemctl-Modus existiert."""
    cmd = ['systemctl']
    if mode == 'user':
        cmd.append('--user')
    cmd += ['list-unit-files', '--no-legend', '--no-pager', 'dorfkern.target']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and 'dorfkern.target' in r.stdout


@lru_cache(maxsize=1)
def systemd_mode() -> Optional[str]:
    """Liefert den erkannten Mode: 'user', 'system' oder None.

    Cache-Lifetime = Prozess-Lifetime. Wer nach einem ``daemon-reload``
    weiterarbeitet, muss ``invalidate_cache()`` rufen.
    """
    if not _systemctl_available():
        return None
    user_present   = _has_unit('user')
    system_present = _has_unit('system')
    if user_present and system_present:
        log.warning("Dorfkern: sowohl User- als auch System-Units installiert "
                    "— nutze User-Mode. Bitte einen der beiden deinstallieren.")
        return 'user'
    if user_present:
        return 'user'
    if system_present:
        return 'system'
    return None


def is_systemd_managed() -> bool:
    """True wenn irgendein Mode (user oder system) erkannt wurde.

    Erhalten fuer Aufrufer, denen der Mode egal ist (z.B. app_manager).
    """
    return systemd_mode() is not None


def invalidate_cache() -> None:
    """Cache von ``systemd_mode()`` (und damit ``is_systemd_managed``) leeren."""
    systemd_mode.cache_clear()


def _systemctl(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Ruft ``systemctl`` im erkannten Modus auf.

    - User-Mode: ``systemctl --user ...`` ohne sudo.
    - System-Mode als root: direkt.
    - System-Mode als non-root: via ``sudo -n``, damit das in
      passwortfreien sudoers-Snippets funktioniert.
    """
    mode = systemd_mode()
    cmd = ['systemctl']
    if mode == 'user':
        cmd.append('--user')
        cmd.extend(args)
    else:
        cmd.extend(args)
        if os.geteuid() != 0:
            cmd = ['sudo', '-n'] + cmd
    kwargs: Dict[str, object] = {'timeout': _SYSTEMCTL_TIMEOUT}
    if capture:
        kwargs.update({'capture_output': True, 'text': True})
    return subprocess.run(cmd, **kwargs)


def _wait_active(unit: str, timeout: int = _WAIT_ACTIVE_SECS) -> bool:
    """Wartet bis Unit ``active`` ist oder Timeout abgelaufen ist.

    Bricht frueh ab, sobald die Unit ``failed`` meldet.
    """
    for _ in range(timeout):
        active = _systemctl('is-active', '--quiet', unit)
        if active.returncode == 0:
            return True
        failed = _systemctl('is-failed', '--quiet', unit)
        if failed.returncode == 0:
            return False
        time.sleep(1)
    return False


def _err(r: subprocess.CompletedProcess) -> str:
    """Lesbare Fehlermeldung aus stderr/stdout einer systemctl-Antwort."""
    return ((r.stderr or '') + (r.stdout or '')).strip() or f'exit {r.returncode}'


def _journalctl_hint(unit: str) -> str:
    """Hinweistext fuer journalctl-Aufruf, modus-spezifisch."""
    flag = ' --user' if systemd_mode() == 'user' else ''
    return f'journalctl{flag} -u {unit}'


def start_app(name: str, *, print_fn=print) -> bool:
    """Startet eine einzelne App. True bei Erfolg."""
    unit = units.unit_name(name)
    r = _systemctl('start', unit)
    if r.returncode != 0:
        print_fn(f"  ✗  {name}: systemctl start fehlgeschlagen: {_err(r)}")
        return False
    if _wait_active(unit):
        print_fn(f"  ✓  {name} gestartet (systemd-{systemd_mode()})")
        return True
    print_fn(f"  ✗  {name}: Unit wurde nicht aktiv – "
             f"siehe `{_journalctl_hint(unit)}`")
    return False


def stop_app(name: str, *, print_fn=print) -> None:
    """Stoppt eine einzelne App."""
    unit = units.unit_name(name)
    r = _systemctl('stop', unit)
    if r.returncode == 0:
        print_fn(f"  ✓  {name} gestoppt (systemd-{systemd_mode()})")
    else:
        print_fn(f"  ✗  {name}: systemctl stop fehlgeschlagen: {_err(r)}")


def restart_app(name: str, *, print_fn=print) -> bool:
    """Restart einer einzelnen App."""
    unit = units.unit_name(name)
    r = _systemctl('restart', unit)
    if r.returncode != 0:
        print_fn(f"  ✗  {name}: systemctl restart fehlgeschlagen: {_err(r)}")
        return False
    if _wait_active(unit):
        print_fn(f"  ✓  {name} neu gestartet (systemd-{systemd_mode()})")
        return True
    print_fn(f"  ✗  {name}: Unit wurde nicht aktiv – "
             f"siehe `{_journalctl_hint(unit)}`")
    return False


def status_app(name: str, *, port: Optional[int],
               is_daemon: bool) -> Dict[str, object]:
    """Status-Dict in derselben Form wie ``app_manager.status_app``."""
    unit = units.unit_name(name)
    active = ''
    main_pid = 0
    show = _systemctl('show', '-p', 'ActiveState,MainPID,LoadState', unit)
    if show.returncode == 0:
        for line in show.stdout.splitlines():
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k == 'MainPID':
                try:
                    main_pid = int(v)
                except ValueError:
                    main_pid = 0
            elif k == 'ActiveState':
                active = v.strip()
    running = active == 'active'
    return {
        'name':    name,
        'type':    'daemon' if is_daemon else 'web',
        'port':    port,
        'running': running,
        'pid':     main_pid if running and main_pid > 0 else None,
        'log':     _journalctl_hint(unit),
    }


def start_all(apps: Optional[List[str]] = None, *,
              print_fn=print) -> Dict[str, bool]:
    """Startet via ``dorfkern.target`` (bei None) oder einzelne Apps."""
    if apps is None:
        r = _systemctl('start', 'dorfkern.target')
        if r.returncode != 0:
            print_fn(f"  ✗  systemctl start dorfkern.target: {_err(r)}")
            return {a: False for a in units.all_app_names()}
        print_fn(f"  ✓  dorfkern.target gestartet (systemd-{systemd_mode()})")
        return {a: True for a in units.all_app_names()}
    return {a: start_app(a, print_fn=print_fn) for a in apps}


def stop_all(apps: Optional[List[str]] = None, *, print_fn=print) -> None:
    """Stoppt via ``dorfkern.target`` oder einzelne Apps."""
    if apps is None:
        r = _systemctl('stop', 'dorfkern.target')
        if r.returncode == 0:
            print_fn(f"  ✓  dorfkern.target gestoppt (systemd-{systemd_mode()})")
        else:
            print_fn(f"  ✗  systemctl stop dorfkern.target: {_err(r)}")
        return
    for a in apps:
        stop_app(a, print_fn=print_fn)
