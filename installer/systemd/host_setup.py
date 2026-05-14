"""
Install/Uninstall der Dorfkern-systemd-Units auf dem Host.

Im Gegensatz zu ``units.py`` (rein) und ``manager.py`` (laufzeit-Steuerung)
fasst dieses Modul die Setup-Aktionen zusammen, die einmal beim
Installer-Lauf passieren:

  install_user(install_root, instance_name=...)        -> ~/.config/systemd/user
  install_system(install_root, instance_name=...)      -> /etc/systemd/system
  regenerate_user/system(install_root, instance_name=...) -> nur Service-Units
                                                              neu schreiben + reload
  uninstall_user/system(instance_name=...)              -> stoppen + loeschen

Alle Funktionen schreiben Fortschritt ueber das ``print_fn``-Callback
(Default: print). Sie geben True bei Erfolg zurueck und False, wenn ein
Teilschritt fehlschlaegt — der Aufrufer entscheidet ueber Abbruch vs.
Weitermachen.

Hinweise:
  - Alle System-Mode-Aktionen brauchen root. Wenn nicht root, wird via
    ``sudo -n`` gewrappt — d.h. der aufrufende User muss passwortlos
    sudo-Rechte haben. Sonst schlaegt die Aktion mit klarer Fehlermeldung
    fehl.
  - User-Mode-Aktionen brauchen kein root, AUSSER fuer
    ``loginctl enable-linger`` — auch hier ``sudo -n``.
  - Mit nicht-leerem ``instance_name`` bekommen User, Pfade und Units
    einen Suffix (z.B. dorfkern-prod-admin.service, /opt/dorfkern-prod,
    /var/log/dorfkern-prod, System-User dorfkern-prod). Default ohne
    Suffix laesst alles wie bisher.
"""
import getpass
import os
import subprocess
from typing import Callable, List, Optional

from . import units


# Standard-Zielpfade.
SYSTEM_UNIT_DIR = '/etc/systemd/system'
USER_UNIT_DIR   = os.path.expanduser('~/.config/systemd/user')


PrintFn = Callable[[str], None]


def system_dirs(instance_name: str = '') -> List[str]:
    """Liste der /var-Verzeichnisse, die fuer System-Mode angelegt werden.

    Pro Instanz separat, damit sich DEV und PROD-Backups/Logs nicht
    vermischen.
    """
    prefix = units.systemd_prefix(instance_name)
    return [f'/var/log/{prefix}', f'/var/backups/{prefix}']


# Behaelt das alte Tupel-Symbol als Default-Wert (leerer Instanz) bei,
# falls jemand das aus aelterem Code importiert.
SYSTEM_DIRS = tuple(system_dirs(''))


# ─── Hilfsfunktionen ──────────────────────────────────────────────────

def _run(cmd: List[str], *, capture: bool = True,
         timeout: int = 60) -> subprocess.CompletedProcess:
    """Subprocess-Wrapper, der Capture/Timeout vorgibt."""
    kwargs = {'timeout': timeout}
    if capture:
        kwargs.update({'capture_output': True, 'text': True})
    return subprocess.run(cmd, **kwargs)


def _maybe_sudo(cmd: List[str]) -> List[str]:
    """Prependet ``sudo -n``, wenn der aufrufende User nicht root ist.

    ``-n`` heisst: niemals interaktiv nach Passwort fragen. Auf einer
    Box ohne passwortfreies sudo schlaegt das mit klarer Meldung fehl,
    statt im Installer ploetzlich auf einen Passwort-Prompt zu warten,
    den der User auf einem Headless-System gar nicht sieht.
    """
    if os.geteuid() == 0:
        return cmd
    return ['sudo', '-n'] + cmd


def _err(r: subprocess.CompletedProcess) -> str:
    return ((r.stderr or '') + (r.stdout or '')).strip() or f'exit {r.returncode}'


def _write_units(target_dir: str, rendered: dict,
                 *, sudo: bool, print_fn: PrintFn) -> bool:
    """Schreibt alle Units in ``target_dir``.

    Im ``sudo``-Modus geht das ueber ``sudo install -m 0644 …`` pro Datei
    (Workaround dafuer, dass wir keinen Root-Open-Handle haben).
    """
    if sudo:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for fname, content in rendered.items():
                src = os.path.join(tmp, fname)
                with open(src, 'w', encoding='utf-8') as f:
                    f.write(content)
                dst = os.path.join(target_dir, fname)
                r = _run(_maybe_sudo(
                    ['install', '-m', '0644', '-o', 'root', '-g', 'root',
                     src, dst]))
                if r.returncode != 0:
                    print_fn(f"  ✗  Konnte {dst} nicht schreiben: {_err(r)}")
                    return False
                print_fn(f"  ✓  {dst}")
        return True

    os.makedirs(target_dir, exist_ok=True)
    for fname, content in rendered.items():
        path = os.path.join(target_dir, fname)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except OSError as exc:
            print_fn(f"  ✗  Konnte {path} nicht schreiben: {exc}")
            return False
        print_fn(f"  ✓  {path}")
    return True


def _remove_units(target_dir: str, instance_name: str, *,
                  sudo: bool, print_fn: PrintFn) -> None:
    """Loescht alle <prefix>-*.service und <prefix>.target in target_dir."""
    files = [units.unit_name(a, instance_name) for a in units.all_app_names()]
    files.append(units.target_name(instance_name))
    paths = [os.path.join(target_dir, f) for f in files]
    paths = [p for p in paths if os.path.lexists(p)]
    if not paths:
        return
    if sudo:
        r = _run(_maybe_sudo(['rm', '-f'] + paths))
        if r.returncode != 0:
            print_fn(f"  ✗  rm: {_err(r)}")
            return
    else:
        for p in paths:
            try:
                os.unlink(p)
            except OSError as exc:
                print_fn(f"  ✗  rm {p}: {exc}")
    for p in paths:
        print_fn(f"  ✓  geloescht: {p}")


# ─── User-Mode ────────────────────────────────────────────────────────

def install_user(install_root: str, *,
                 instance_name: str = '',
                 base_port: int = units.DEFAULT_BASE_PORT,
                 selected_apps: Optional[List[str]] = None,
                 enable_lingering: bool = True,
                 start_after_enable: bool = True,
                 print_fn: PrintFn = print) -> bool:
    """Installiert die Units als ``systemctl --user``-Dienste.

    Args:
        install_root: Repo-Wurzel auf diesem Host (-> ``WorkingDirectory``).
        instance_name: Suffix fuer Unit-/Target-Namen (leer = Default).
        base_port: Port-Base fuer Web-Apps (Default 5000).
        selected_apps: Apps im ``Wants=`` des Targets (None = alle).
        enable_lingering: ``sudo loginctl enable-linger`` ausrufen, damit
            die Dienste auch ohne aktive Session weiterlaufen.
        start_after_enable: am Ende ``systemctl --user start <target>``
            triggern.
    """
    target = units.target_name(instance_name)
    print_fn("  → Units rendern und ablegen …")
    rendered = units.render_all(mode='user',
                                 instance_name=instance_name,
                                 base_port=base_port,
                                 install_root=install_root,
                                 apps=selected_apps)
    if not _write_units(USER_UNIT_DIR, rendered, sudo=False, print_fn=print_fn):
        return False

    if enable_lingering:
        user_name = getpass.getuser()
        print_fn(f"  → Lingering fuer {user_name} aktivieren (via sudo) …")
        r = _run(_maybe_sudo(['loginctl', 'enable-linger', user_name]))
        if r.returncode != 0:
            print_fn(f"  ⚠  loginctl enable-linger fehlgeschlagen: {_err(r)}")
            print_fn("     Die Apps laufen, aber sterben beim Logout. Manuell"
                     " nachholen: sudo loginctl enable-linger " + user_name)
        else:
            print_fn("  ✓  Lingering aktiviert")

    print_fn("  → systemctl --user daemon-reload …")
    r = _run(['systemctl', '--user', 'daemon-reload'])
    if r.returncode != 0:
        print_fn(f"  ✗  daemon-reload: {_err(r)}")
        return False

    print_fn(f"  → systemctl --user enable {target} …")
    r = _run(['systemctl', '--user', 'enable', target])
    if r.returncode != 0:
        print_fn(f"  ✗  enable: {_err(r)}")
        return False
    print_fn(f"  ✓  {target} enabled")

    if start_after_enable:
        print_fn(f"  → systemctl --user start {target} …")
        r = _run(['systemctl', '--user', 'start', target], timeout=180)
        if r.returncode != 0:
            print_fn(f"  ✗  start: {_err(r)}")
            return False
        print_fn(f"  ✓  {target} gestartet")

    return True


def regenerate_user(install_root: str, *,
                    instance_name: str = '',
                    base_port: int = units.DEFAULT_BASE_PORT,
                    print_fn: PrintFn = print) -> bool:
    """Schreibt User-Service-Units neu und macht systemctl --user daemon-reload.

    Update-Pfad: nach einem ``git pull``, wenn der User-Mode aktiv ist,
    moegen sich Templates in ``units.py`` geaendert haben. Dann muessen
    die Dateien neu geschrieben werden, damit beim naechsten Start die
    neue Definition gilt.

    Das Target wird absichtlich NICHT angefasst — die urspruengliche
    App-Auswahl aus dem Install bleibt erhalten.
    """
    print_fn("  → User-Service-Units rendern …")
    rendered = units.render_all(mode='user',
                                 instance_name=instance_name,
                                 base_port=base_port,
                                 install_root=install_root,
                                 include_target=False)
    if not _write_units(USER_UNIT_DIR, rendered, sudo=False,
                        print_fn=print_fn):
        return False
    print_fn("  → systemctl --user daemon-reload …")
    r = _run(['systemctl', '--user', 'daemon-reload'])
    if r.returncode != 0:
        print_fn(f"  ✗  daemon-reload: {_err(r)}")
        return False
    return True


def uninstall_user(*, instance_name: str = '',
                   print_fn: PrintFn = print) -> bool:
    """Stoppt + disabled + loescht User-Units der gegebenen Instanz."""
    target = units.target_name(instance_name)
    print_fn(f"  → systemctl --user stop/disable {target} …")
    _run(['systemctl', '--user', 'stop',    target], timeout=120)
    _run(['systemctl', '--user', 'disable', target])

    print_fn("  → Unit-Files loeschen …")
    _remove_units(USER_UNIT_DIR, instance_name, sudo=False, print_fn=print_fn)

    print_fn("  → systemctl --user daemon-reload …")
    _run(['systemctl', '--user', 'daemon-reload'])
    return True


# ─── System-Mode ──────────────────────────────────────────────────────

def _user_exists(name: str) -> bool:
    try:
        import pwd
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def _ensure_system_user(user: str, install_root: str,
                       *, print_fn: PrintFn) -> bool:
    """Legt System-User+Gruppe an, falls noch nicht vorhanden.

    Gruppenname = Username (``--user-group``).
    """
    if _user_exists(user):
        print_fn(f"  ✓  Service-User {user!r} existiert bereits")
        return True
    print_fn(f"  → useradd {user} (System-User, kein Login) …")
    cmd = ['useradd', '--system',
           '--home-dir', install_root,
           '--shell', '/usr/sbin/nologin',
           '--user-group', user]
    r = _run(_maybe_sudo(cmd))
    if r.returncode != 0:
        print_fn(f"  ✗  useradd: {_err(r)}")
        return False
    print_fn(f"  ✓  {user} angelegt (eigene Gruppe ebenfalls {user})")
    return True


def _ensure_system_dirs(user: str, group: str, instance_name: str,
                       *, print_fn: PrintFn) -> bool:
    """Legt /var/log/<prefix> und /var/backups/<prefix> mit korrektem Owner an."""
    for d in system_dirs(instance_name):
        if os.path.isdir(d):
            print_fn(f"  ✓  {d} existiert")
            continue
        r = _run(_maybe_sudo(['install', '-d', '-m', '0750',
                              '-o', user, '-g', group, d]))
        if r.returncode != 0:
            print_fn(f"  ✗  mkdir {d}: {_err(r)}")
            return False
        print_fn(f"  ✓  {d} angelegt (Owner {user}:{group})")
    return True


def install_system(install_root: str, *,
                   instance_name: str = '',
                   base_port: int = units.DEFAULT_BASE_PORT,
                   user: str = '',
                   group: str = '',
                   selected_apps: Optional[List[str]] = None,
                   start_after_enable: bool = True,
                   print_fn: PrintFn = print) -> bool:
    """Installiert die Units als systemweite Dienste unter Service-User.

    user/group sind defaultmaessig vom Instanz-Namen abgeleitet
    (dorfkern bzw. dorfkern-<instance>), koennen aber ueberschrieben werden.
    """
    if os.geteuid() != 0:
        print_fn("  ⚠  Nicht als root gestartet — verwende sudo -n. "
                 "Falls kein passwortloses sudo, bricht das gleich ab.")

    if not user:
        user = units.systemd_prefix(instance_name)
    if not group:
        group = user

    if not _ensure_system_user(user, install_root, print_fn=print_fn):
        return False
    if not _ensure_system_dirs(user, group, instance_name, print_fn=print_fn):
        return False

    # Ownership von install_root sicherstellen — Code muss vom Service-
    # User lesbar/ausfuehrbar sein. Idempotent.
    if os.path.isdir(install_root):
        print_fn(f"  → chown -R {user}:{group} {install_root} …")
        r = _run(_maybe_sudo(['chown', '-R', f'{user}:{group}', install_root]))
        if r.returncode != 0:
            print_fn(f"  ✗  chown: {_err(r)}")
            return False
    else:
        print_fn(f"  ✗  install_root {install_root} existiert nicht. "
                 "Bitte Repo dorthin verschieben/klonen.")
        return False

    print_fn("  → Units rendern und ablegen …")
    rendered = units.render_all(mode='system',
                                 instance_name=instance_name,
                                 base_port=base_port,
                                 install_root=install_root,
                                 user=user, group=group,
                                 apps=selected_apps)
    if not _write_units(SYSTEM_UNIT_DIR, rendered, sudo=True, print_fn=print_fn):
        return False

    print_fn("  → systemctl daemon-reload …")
    r = _run(_maybe_sudo(['systemctl', 'daemon-reload']))
    if r.returncode != 0:
        print_fn(f"  ✗  daemon-reload: {_err(r)}")
        return False

    target = units.target_name(instance_name)
    action = 'enable --now' if start_after_enable else 'enable'
    print_fn(f"  → systemctl {action} {target} …")
    cmd = ['systemctl', 'enable']
    if start_after_enable:
        cmd.append('--now')
    cmd.append(target)
    r = _run(_maybe_sudo(cmd), timeout=180)
    if r.returncode != 0:
        print_fn(f"  ✗  enable: {_err(r)}")
        return False
    msg = 'enabled + gestartet' if start_after_enable else 'enabled'
    print_fn(f"  ✓  {target} {msg}")
    return True


def regenerate_system(install_root: str, *,
                      instance_name: str = '',
                      base_port: int = units.DEFAULT_BASE_PORT,
                      user: str = '',
                      group: str = '',
                      print_fn: PrintFn = print) -> bool:
    """Schreibt System-Service-Units neu und macht systemctl daemon-reload.

    Analog zu :func:`regenerate_user`, aber im System-Mode (Units leben
    unter /etc/systemd/system, Schreibvorgang via sudo). Das Target
    bleibt unangetastet (App-Auswahl erhalten).
    """
    if not user:
        user = units.systemd_prefix(instance_name)
    if not group:
        group = user

    print_fn("  → System-Service-Units rendern …")
    rendered = units.render_all(mode='system',
                                 instance_name=instance_name,
                                 base_port=base_port,
                                 install_root=install_root,
                                 user=user, group=group,
                                 include_target=False)
    if not _write_units(SYSTEM_UNIT_DIR, rendered, sudo=True,
                        print_fn=print_fn):
        return False
    print_fn("  → systemctl daemon-reload …")
    r = _run(_maybe_sudo(['systemctl', 'daemon-reload']))
    if r.returncode != 0:
        print_fn(f"  ✗  daemon-reload: {_err(r)}")
        return False
    return True


def uninstall_system(*, instance_name: str = '',
                     print_fn: PrintFn = print) -> bool:
    """Stoppt + disabled + loescht System-Units der gegebenen Instanz.

    User + /var-Verzeichnisse bleiben — die koennen noch Backups/Logs
    enthalten und sollen vom Operator manuell aufgeraeumt werden.
    """
    target = units.target_name(instance_name)
    print_fn(f"  → systemctl stop/disable {target} …")
    _run(_maybe_sudo(['systemctl', 'stop',    target]), timeout=120)
    _run(_maybe_sudo(['systemctl', 'disable', target]))

    print_fn("  → Unit-Files loeschen …")
    _remove_units(SYSTEM_UNIT_DIR, instance_name, sudo=True, print_fn=print_fn)

    print_fn("  → systemctl daemon-reload …")
    _run(_maybe_sudo(['systemctl', 'daemon-reload']))
    return True
