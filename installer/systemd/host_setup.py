"""
Install/Uninstall der Dorfkern-systemd-Units auf dem Host.

Im Gegensatz zu ``units.py`` (rein) und ``manager.py`` (laufzeit-Steuerung)
fasst dieses Modul die Setup-Aktionen zusammen, die einmal beim
Installer-Lauf passieren:

  install_user(install_root)        -> Units nach ~/.config/systemd/user
  install_system(install_root)      -> Units nach /etc/systemd/system
  uninstall_user()                  -> stoppen, disablen, loeschen (user)
  uninstall_system()                -> stoppen, disablen, loeschen (system)

Alle Funktionen schreiben Fortschritt ueber das ``print_fn``-Callback
(Default: print). Sie geben True bei Erfolg zurueck und False, wenn ein
Teilschritt fehlschlaegt — der Aufrufer entscheidet ueber Abbruch vs.
Weitermachen.

Hinweise:
  - System-Mode-Aktionen brauchen root (useradd, mkdir /etc, chown,
    systemctl). Wenn nicht root, wird via ``sudo -n`` gewrappt — d.h.
    der aufrufende User muss passwortlos sudo-Rechte haben oder vorher
    ein ``sudo -v`` gemacht haben. Sonst schlaegt die Aktion mit klarer
    Fehlermeldung fehl.
  - User-Mode-Aktionen brauchen kein root, AUSSER fuer
    ``loginctl enable-linger`` — auch hier ``sudo -n``.
"""
import getpass
import os
import subprocess
from typing import Callable, List, Optional

from . import units


# Standard-Zielpfade.
SYSTEM_UNIT_DIR = '/etc/systemd/system'
USER_UNIT_DIR   = os.path.expanduser('~/.config/systemd/user')

# Verzeichnisse, die fuer System-Mode angelegt werden (Owner = Service-User).
SYSTEM_DIRS = ('/var/log/dorfkern', '/var/backups/dorfkern')


PrintFn = Callable[[str], None]


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
        # Erst ein temporaeres Verzeichnis als User befuellen, dann mit sudo
        # nach target_dir kopieren. Stabiler als 'sudo tee'-Pipeline.
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

    # User-Mode: direkt schreiben
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


def _remove_units(target_dir: str, *, sudo: bool,
                  print_fn: PrintFn) -> None:
    """Loescht alle dorfkern-*.service und dorfkern.target in target_dir."""
    files = [units.unit_name(a) for a in units.all_app_names()]
    files.append('dorfkern.target')
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
                 selected_apps: Optional[List[str]] = None,
                 enable_lingering: bool = True,
                 start_after_enable: bool = True,
                 print_fn: PrintFn = print) -> bool:
    """Installiert die Units als ``systemctl --user``-Dienste.

    Args:
        install_root: Repo-Wurzel auf diesem Host (das, was als
            ``WorkingDirectory`` in die Units geht).
        selected_apps: Apps, die im ``Wants=`` des Targets stehen sollen
            (None = alle). Wirkt sich nur darauf aus, was beim
            Target-Start automatisch hochkommt — die Service-Units werden
            immer fuer alle Apps installiert.
        enable_lingering: Wenn True, ``sudo loginctl enable-linger`` ausrufen,
            damit die Dienste auch ohne aktive Session weiterlaufen.
        start_after_enable: Wenn True, am Ende ``systemctl --user start
            dorfkern.target`` triggern (auf Enable folgt bei systemd-User
            nicht automatisch der erste Start).

    Returns True bei Erfolg.
    """
    print_fn("  → Units rendern und ablegen …")
    rendered = units.render_all(mode='user', install_root=install_root,
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

    print_fn("  → systemctl --user enable dorfkern.target …")
    r = _run(['systemctl', '--user', 'enable', 'dorfkern.target'])
    if r.returncode != 0:
        print_fn(f"  ✗  enable: {_err(r)}")
        return False
    print_fn("  ✓  dorfkern.target enabled")

    if start_after_enable:
        print_fn("  → systemctl --user start dorfkern.target …")
        r = _run(['systemctl', '--user', 'start', 'dorfkern.target'],
                 timeout=180)
        if r.returncode != 0:
            print_fn(f"  ✗  start: {_err(r)}")
            return False
        print_fn("  ✓  dorfkern.target gestartet")

    return True


def regenerate_user(install_root: str, *,
                    print_fn: PrintFn = print) -> bool:
    """Schreibt User-Service-Units neu und macht systemctl --user daemon-reload.

    Update-Pfad: nach einem ``git pull``, wenn der User-Mode aktiv ist,
    moegen sich Templates in ``units.py`` geaendert haben (ExecStart,
    Restart-Policy, Env-Vars). Dann muessen die Dateien neu geschrieben
    werden, damit beim naechsten Start die neue Definition gilt.

    Das ``dorfkern.target`` wird absichtlich NICHT angefasst — die
    urspruengliche App-Auswahl aus dem Install bleibt erhalten.
    """
    print_fn("  → User-Service-Units rendern …")
    rendered = units.render_all(mode='user', install_root=install_root,
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


def uninstall_user(*, print_fn: PrintFn = print) -> bool:
    """Stoppt + disabled + loescht User-Units. Lingering bleibt unangetastet
    (kann auch fuer andere User-Services genutzt sein)."""
    print_fn("  → systemctl --user stop/disable dorfkern.target …")
    _run(['systemctl', '--user', 'stop',    'dorfkern.target'], timeout=120)
    _run(['systemctl', '--user', 'disable', 'dorfkern.target'])

    print_fn("  → Unit-Files loeschen …")
    _remove_units(USER_UNIT_DIR, sudo=False, print_fn=print_fn)

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


def _ensure_system_user(user: str, group: str, install_root: str,
                       *, print_fn: PrintFn) -> bool:
    """Legt System-User+Gruppe an, falls noch nicht vorhanden."""
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
    print_fn(f"  ✓  {user}:{group} angelegt")
    return True


def _ensure_system_dirs(user: str, group: str,
                       *, print_fn: PrintFn) -> bool:
    """Legt /var/log/dorfkern und /var/backups/dorfkern mit korrektem Owner an."""
    for d in SYSTEM_DIRS:
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
                   user: str = units.DEFAULT_USER,
                   group: str = units.DEFAULT_GROUP,
                   selected_apps: Optional[List[str]] = None,
                   start_after_enable: bool = True,
                   print_fn: PrintFn = print) -> bool:
    """Installiert die Units als systemweite Dienste unter Service-User.

    Voraussetzungen werden vom Installer abgefragt (root, install_root
    = /opt/dorfkern). Wir pruefen hier nur defensiv die offensichtlichen
    Voraussetzungen + raisen klar.
    """
    if os.geteuid() != 0:
        # Wir versuchen es trotzdem ueber sudo, aber warnen frueh.
        print_fn("  ⚠  Nicht als root gestartet — verwende sudo -n. "
                 "Falls kein passwortloses sudo, bricht das gleich ab.")

    if not _ensure_system_user(user, group, install_root, print_fn=print_fn):
        return False
    if not _ensure_system_dirs(user, group, print_fn=print_fn):
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
    rendered = units.render_all(mode='system', install_root=install_root,
                                 user=user, group=group,
                                 apps=selected_apps)
    if not _write_units(SYSTEM_UNIT_DIR, rendered, sudo=True, print_fn=print_fn):
        return False

    print_fn("  → systemctl daemon-reload …")
    r = _run(_maybe_sudo(['systemctl', 'daemon-reload']))
    if r.returncode != 0:
        print_fn(f"  ✗  daemon-reload: {_err(r)}")
        return False

    action = 'enable --now' if start_after_enable else 'enable'
    print_fn(f"  → systemctl {action} dorfkern.target …")
    cmd = ['systemctl', 'enable']
    if start_after_enable:
        cmd.append('--now')
    cmd.append('dorfkern.target')
    r = _run(_maybe_sudo(cmd), timeout=180)
    if r.returncode != 0:
        print_fn(f"  ✗  enable: {_err(r)}")
        return False
    msg = 'enabled + gestartet' if start_after_enable else 'enabled'
    print_fn(f"  ✓  dorfkern.target {msg}")
    return True


def regenerate_system(install_root: str, *,
                      user: str = units.DEFAULT_USER,
                      group: str = units.DEFAULT_GROUP,
                      print_fn: PrintFn = print) -> bool:
    """Schreibt System-Service-Units neu und macht systemctl daemon-reload.

    Analog zu :func:`regenerate_user`, aber im System-Mode (Units leben
    unter /etc/systemd/system, Schreibvorgang via sudo).
    Das ``dorfkern.target`` bleibt unangetastet (App-Auswahl erhalten).
    """
    print_fn("  → System-Service-Units rendern …")
    rendered = units.render_all(mode='system', install_root=install_root,
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


def uninstall_system(*, print_fn: PrintFn = print) -> bool:
    """Stoppt + disabled + loescht System-Units. User-Account bleibt."""
    print_fn("  → systemctl stop/disable dorfkern.target …")
    _run(_maybe_sudo(['systemctl', 'stop',    'dorfkern.target']), timeout=120)
    _run(_maybe_sudo(['systemctl', 'disable', 'dorfkern.target']))

    print_fn("  → Unit-Files loeschen …")
    _remove_units(SYSTEM_UNIT_DIR, sudo=True, print_fn=print_fn)

    print_fn("  → systemctl daemon-reload …")
    _run(_maybe_sudo(['systemctl', 'daemon-reload']))
    return True
