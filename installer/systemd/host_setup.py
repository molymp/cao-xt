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


# /etc/sudoers.d/dorfkern-shutdown — passwortfreies Shutdown/Reboot +
# Wartungs-Toggle fuer den dorfkern-Service-User. Der "Feierabend"-Knopf
# in der Admin-App ruft 'sudo -n /sbin/shutdown -h now', das Wartungs-
# Widget ruft 'sudo -n /usr/local/bin/dorfkern-maintenance-mode'. Wird
# ueber alle Instanzen genutzt (nicht instanz-suffigiert), da der User
# immer 'dorfkern' ist.
_SUDOERS_SHUTDOWN_PATH = '/etc/sudoers.d/dorfkern-shutdown'
_SUDOERS_SHUTDOWN_CONTENT = (
    "# Auto-generiert von installer/systemd/host_setup.py\n"
    "# Erlaubt dem dorfkern-Service-User, den Rechner herunterzufahren,\n"
    "# neu zu starten oder den Wartungs-Modus zu toggeln — ohne Passwort,\n"
    "# aber strikt nur diese Befehle.\n"
    "dorfkern ALL=(root) NOPASSWD: /sbin/shutdown -h now, "
    "/sbin/shutdown -r now, /sbin/poweroff, /sbin/reboot, "
    "/usr/local/bin/dorfkern-maintenance-mode, "
    "/usr/local/bin/dorfkern-maintenance-mode --kiosk, "
    "/usr/local/bin/dorfkern-maintenance-mode --maintenance, "
    "/usr/local/bin/dorfkern-maintenance-mode --greeter, "
    "/usr/local/bin/dorfkern-maintenance-mode --status\n"
    "# Plus: kasse-User darf das Skript ohne Passwort rufen — fuer das\n"
    "# Desktop-Icon 'Zurueck zum Kiosk' im Wartungs-Desktop.\n"
    "kasse ALL=(root) NOPASSWD: /usr/local/bin/dorfkern-maintenance-mode --kiosk\n"
)


def _ensure_shutdown_sudoers(*, print_fn: PrintFn) -> bool:
    """Legt /etc/sudoers.d/dorfkern-shutdown an (idempotent).

    Wenn die Datei schon den richtigen Inhalt hat: nichts tun.
    Sonst neu schreiben via 'sudo install' (atomar + Mode 0440, das ist
    der pflichtige Mode fuer sudoers-Snippets — sudo lehnt andere ab).
    """
    if (os.path.isfile(_SUDOERS_SHUTDOWN_PATH)
        and os.access(_SUDOERS_SHUTDOWN_PATH, os.R_OK)):
        try:
            with open(_SUDOERS_SHUTDOWN_PATH, 'r', encoding='utf-8') as f:
                if f.read() == _SUDOERS_SHUTDOWN_CONTENT:
                    print_fn(f"  ✓  {_SUDOERS_SHUTDOWN_PATH} aktuell")
                    return True
        except OSError:
            pass

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sudoers',
                                     delete=False, encoding='utf-8') as f:
        f.write(_SUDOERS_SHUTDOWN_CONTENT)
        tmp_path = f.name
    try:
        r = _run(_maybe_sudo(
            ['install', '-m', '0440', '-o', 'root', '-g', 'root',
             tmp_path, _SUDOERS_SHUTDOWN_PATH]))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if r.returncode != 0:
        print_fn(f"  ✗  sudoers-Snippet nicht installiert: {_err(r)}")
        return False
    print_fn(f"  ✓  {_SUDOERS_SHUTDOWN_PATH} (Mode 0440)")
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

    # Default-User ist IMMER 'dorfkern' — auch bei Multi-Instanz.
    # Die Trennung zwischen Instanzen laeuft ueber Pfade/Unit-Namen/
    # Ports/DB-Credentials, nicht ueber FS-Berechtigung. So bleibt
    # der Operator-Aufwand klein (ein User pflegen, ein sudoers-
    # Snippet, gemeinsame Backup-Rotation).
    if not user:
        user = units.DEFAULT_USER
    if not group:
        group = units.DEFAULT_GROUP if user == units.DEFAULT_USER else user

    if not _ensure_system_user(user, install_root, print_fn=print_fn):
        return False
    if not _ensure_system_dirs(user, group, instance_name, print_fn=print_fn):
        return False
    # Sudoers fuer den Feierabend-Shutdown-Knopf — nicht-blockend, falls
    # die Installation auf einer Box ohne sudo laeuft (sehr ungewoehnlich
    # im System-Mode, aber theoretisch moeglich).
    if not _ensure_shutdown_sudoers(print_fn=print_fn):
        print_fn("  ⚠  Shutdown-Sudoers fehlgeschlagen — "
                 "der Feierabend-Knopf wird ohne 'sudo'-Pass nicht funktionieren.")

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
        user = units.DEFAULT_USER
    if not group:
        group = units.DEFAULT_GROUP if user == units.DEFAULT_USER else user

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


# ─── Kiosk-Terminal-Setup ─────────────────────────────────────────────
#
# Boot → LightDM (5-Sek-Autologin-Countdown) → Chromium-Vollbild auf eine
# Dorfkern-App. Wer in den 5 Sekunden ESC oder Maus benutzt, bekommt
# den normalen Login-Bildschirm und kann mit beliebigem User in einen
# regulaeren Desktop (Openbox/XFCE/…) — fuer Wartung.
#
# Voraussetzung: 'dorfkern' ist Login-faehiger User (chsh /bin/bash).
# Die Pakete (lightdm, xorg, chromium, openbox) installiert dieser
# Helper ueber apt. Andere Distros sind erstmal nicht unterstuetzt;
# wer fedora/arch nutzt, muss das manuell nachziehen.

_KIOSK_LIGHTDM_DIR     = '/etc/lightdm/lightdm.conf.d'
_KIOSK_LIGHTDM_CONF      = f'{_KIOSK_LIGHTDM_DIR}/50-dorfkern-kiosk.conf'
_KIOSK_SESSION_DESKTOP   = '/usr/share/xsessions/dorfkern-kiosk.desktop'
_KIOSK_SESSION_SCRIPT    = '/usr/local/bin/dorfkern-kiosk-session'
_KIOSK_MAINTENANCE_SCRIPT = '/usr/local/bin/dorfkern-maintenance-mode'

_KIOSK_APT_PKGS_PRIMARY  = ['lightdm', 'xorg', 'chromium', 'openbox']
# Auf aelteren/Debian-Stretch-Boxen heisst das Paket 'chromium-browser'
# statt 'chromium'. Fallback wenn primary fehlschlaegt.
_KIOSK_APT_PKGS_FALLBACK = ['lightdm', 'xorg', 'chromium-browser', 'openbox']

_KIOSK_LIGHTDM_TEMPLATE = """\
# Auto-generiert von installer/systemd/host_setup.py
# 5-Sek-Autologin-Timeout: ohne Tastendruck bootet die Box direkt in die
# Kiosk-Session. Wer in dem Fenster klickt/ESC drueckt, bekommt den
# normalen Login-Bildschirm fuer Wartung.
[Seat:*]
autologin-user=dorfkern
autologin-session=dorfkern-kiosk
autologin-user-timeout=5
greeter-show-manual-login=true
"""

_KIOSK_SESSION_DESKTOP_TEMPLATE = """\
[Desktop Entry]
Name=Dorfkern Kiosk
Comment=Chromium im Vollbildmodus auf {url}
Exec={script}
TryExec={script}
Type=Application
"""

_KIOSK_SESSION_SCRIPT_TEMPLATE = """\
#!/bin/bash
# Auto-generiert von installer/systemd/host_setup.py
# Dorfkern-Kiosk-Session: nur Chromium im Kiosk-Mode, sonst nichts.
# Wird von LightDM als X-Session gestartet (siehe dorfkern-kiosk.desktop).
xset s off       # Bildschirmschoner aus
xset -dpms       # DPMS / Stromsparen aus
xset s noblank   # kein Blanking

# Eigenes Chromium-Profil fuer den Kiosk-Mode (separat vom normalen
# ~/.config/chromium). Verhindert, dass Chromium das gespeicherte
# Fenster-Placement aus Desktop-Sitzungen uebernimmt und mit schwarzen
# Raendern statt Vollbild startet. Persistent in $HOME des Login-Users.
CHROMIUM_DIR="$HOME/.config/dorfkern-chromium-kiosk"
mkdir -p "$CHROMIUM_DIR"

exec chromium --kiosk \\
              --user-data-dir="$CHROMIUM_DIR" \\
              --start-fullscreen \\
              --window-position=0,0 \\
              --noerrdialogs \\
              --disable-infobars \\
              --disable-features=TranslateUI \\
              --check-for-update-interval=31536000 \\
              --no-first-run \\
              --password-store=basic \\
              {url}
"""


def is_kiosk_installed() -> bool:
    """True wenn die Kiosk-Session-Files bereits installiert sind.

    Geprueft wird das .desktop-File, weil das immer geschrieben wird —
    die LightDM-Autologin-Config kann bewusst weggelassen worden sein
    (siehe install_kiosk: existierende Autologin-Konfig wird respektiert).
    """
    return os.path.isfile(_KIOSK_SESSION_DESKTOP)


def _install_file_sudo(path: str, content: str, *,
                       mode: str = '0644',
                       owner: str = 'root',
                       group: str = 'root',
                       print_fn: PrintFn) -> bool:
    """Schreibt eine Datei mit gegebenem Mode via 'sudo install'.

    Idempotent: vergleicht vorhandenen Inhalt, schreibt nur wenn anders.
    Legt das Parent-Verzeichnis bei Bedarf via 'sudo mkdir -p' an.
    """
    if os.path.isfile(path) and os.access(path, os.R_OK):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if f.read() == content:
                    print_fn(f"  ✓  {path} aktuell")
                    return True
        except OSError:
            pass

    parent = os.path.dirname(path)
    r0 = _run(_maybe_sudo(['mkdir', '-p', parent]))
    if r0.returncode != 0:
        print_fn(f"  ✗  mkdir {parent}: {_err(r0)}")
        return False

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', delete=False,
                                     encoding='utf-8') as f:
        f.write(content)
        tmp = f.name
    try:
        r = _run(_maybe_sudo(['install', '-m', mode,
                              '-o', owner, '-g', group, tmp, path]))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if r.returncode != 0:
        print_fn(f"  ✗  install {path}: {_err(r)}")
        return False
    print_fn(f"  ✓  {path} (Mode {mode})")
    return True


def _get_user_shell(user: str) -> Optional[str]:
    """Aktuelle Login-Shell eines Users, oder None wenn nicht existent."""
    try:
        import pwd
        return pwd.getpwnam(user).pw_shell
    except KeyError:
        return None


def _is_nologin_shell(shell: Optional[str]) -> bool:
    """Heuristik: Shell verbietet Login (nologin, false, ...).

    pwd liefert den absoluten Pfad; wir matchen am Basename, weil das
    von Distro zu Distro variiert (/usr/sbin/nologin vs. /sbin/nologin
    vs. /usr/bin/false).
    """
    if not shell:
        return True
    base = os.path.basename(shell)
    return base in ('nologin', 'false', 'true')


def _existing_autologin() -> Optional[str]:
    """Sucht nach bereits konfiguriertem LightDM-Autologin auf der Box.

    Returns den User-Namen wenn gefunden (z.B. 'marc'), sonst None.
    Sucht in /etc/lightdm/lightdm.conf UND in allen Dateien unter
    /etc/lightdm/lightdm.conf.d/ AUSSER unserer eigenen — sodass ein
    erneuter Installer-Lauf nicht den eigenen Autologin als "fremd"
    interpretiert.
    """
    import re
    candidates = []
    main = '/etc/lightdm/lightdm.conf'
    if os.path.isfile(main):
        candidates.append(main)
    if os.path.isdir(_KIOSK_LIGHTDM_DIR):
        for fn in sorted(os.listdir(_KIOSK_LIGHTDM_DIR)):
            full = os.path.join(_KIOSK_LIGHTDM_DIR, fn)
            if full == _KIOSK_LIGHTDM_CONF:
                continue   # unsere eigene Config ist hier irrelevant
            if os.path.isfile(full):
                candidates.append(full)

    pat = re.compile(r'^\s*autologin-user\s*=\s*(\S+)\s*$', re.MULTILINE)
    for path in candidates:
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError:
            continue
        m = pat.search(content)
        if m and m.group(1):
            return m.group(1)
    return None


def _active_display_manager() -> Optional[str]:
    """Liefert den Namen des aktuell enabled Display-Managers (gdm/sddm/
    lightdm/...) oder None wenn keiner aktiv ist.

    Pruefung: was zeigt /etc/systemd/system/display-manager.service hin?
    (Das ist der konventionelle Mechanismus, mit dem update-alternatives
    bzw. Distros den Default-DM festlegen.)
    """
    link = '/etc/systemd/system/display-manager.service'
    if not os.path.islink(link):
        return None
    try:
        target = os.readlink(link)
    except OSError:
        return None
    base = os.path.basename(target)
    # 'gdm.service', 'sddm.service', 'lightdm.service' -> 'gdm'/'sddm'/'lightdm'
    if base.endswith('.service'):
        return base[:-len('.service')]
    return base


def install_kiosk(*, base_port: int = units.DEFAULT_BASE_PORT,
                  app: str = 'kiosk',
                  print_fn: PrintFn = print) -> bool:
    """Konfiguriert die Box als Kiosk-Terminal — additiv.

    Macht IMMER:
      - apt install lightdm xorg chromium openbox  (idempotent — wer
        die Pakete schon hat, kriegt nichts neues)
      - dorfkern-kiosk-session-Wrapper-Script + .desktop-Entry, sodass
        die Session im LightDM-Greeter waehlbar ist

    Macht NUR WENN sinnvoll:
      - chsh /bin/bash dorfkern: nur wenn dorfkern-Shell aktuell nologin
        (sonst war's vom Operator bewusst gesetzt — nicht ueberschreiben)
      - LightDM-Autologin-Config: nur wenn KEINE andere Autologin-Konfig
        existiert (sonst hat der Box-Besitzer bewusst einen Admin-User
        konfiguriert — nicht ueberschreiben). Wer auf Kiosk umstellen
        will, passt die existierende Config manuell an.
      - systemctl enable lightdm: nur wenn KEIN anderer DM (gdm/sddm)
        aktiv ist.

    So bleibt eine bestehende Admin-Setup-Konfiguration (z.B. dauerhaft
    eingeloggter Box-Besitzer mit GNOME-Desktop) komplett unberuehrt;
    der Kiosk wird "additiv" als zusaetzliche Session-Option angeboten.
    """
    url = f'http://localhost:{units.app_port(app, base_port)}'

    # ── 1) Pakete via apt ────────────────────────────────────
    print_fn("  → apt install lightdm xorg chromium openbox …")
    r = _run(_maybe_sudo(['apt-get', 'install', '-y'] + _KIOSK_APT_PKGS_PRIMARY),
             timeout=600)
    if r.returncode != 0:
        print_fn("  → Fallback: chromium-browser statt chromium …")
        r = _run(_maybe_sudo(['apt-get', 'install', '-y']
                             + _KIOSK_APT_PKGS_FALLBACK),
                 timeout=600)
    if r.returncode != 0:
        print_fn(f"  ✗  apt install: {_err(r)}")
        print_fn("     Andere Distro? Pakete bitte manuell installieren:")
        print_fn(f"     {' '.join(_KIOSK_APT_PKGS_PRIMARY)}")
        return False
    print_fn("  ✓  Pakete installiert")

    # ── 2) Session-Wrapper-Script + Desktop-Entry (immer additiv) ─
    if not _install_file_sudo(_KIOSK_SESSION_SCRIPT,
                               _KIOSK_SESSION_SCRIPT_TEMPLATE.format(url=url),
                               mode='0755', print_fn=print_fn):
        return False
    if not _install_file_sudo(_KIOSK_SESSION_DESKTOP,
                               _KIOSK_SESSION_DESKTOP_TEMPLATE.format(
                                   url=url, script=_KIOSK_SESSION_SCRIPT),
                               mode='0644', print_fn=print_fn):
        return False

    # ── 2b) Maintenance-Toggle-Skript ──────────────────────────
    # Wechselt LightDM zwischen Auto-Kiosk und Greeter (manueller
    # Login fuer Wartung), ohne Reboot. Aufrufbar via SSH oder
    # ueber einen Button in der Admin-App.
    maintenance_src = os.path.join(os.path.dirname(__file__),
                                     'kiosk_maintenance.sh')
    if os.path.isfile(maintenance_src):
        try:
            with open(maintenance_src, 'r', encoding='utf-8') as f:
                maintenance_content = f.read()
        except OSError as exc:
            print_fn(f"  ⚠  kiosk_maintenance.sh nicht lesbar: {exc}")
        else:
            if not _install_file_sudo(_KIOSK_MAINTENANCE_SCRIPT,
                                       maintenance_content,
                                       mode='0755', print_fn=print_fn):
                return False

    # ── 3) dorfkern Login-Shell nur wenn nologin ────────────────
    shell = _get_user_shell('dorfkern')
    if shell is None:
        print_fn("  ⚠  User 'dorfkern' existiert nicht — wurde er per "
                 "install_system angelegt?")
    elif _is_nologin_shell(shell):
        print_fn(f"  → dorfkern-Shell ({shell}) auf /bin/bash umstellen …")
        r = _run(_maybe_sudo(['chsh', '-s', '/bin/bash', 'dorfkern']))
        if r.returncode != 0:
            print_fn(f"  ⚠  chsh: {_err(r)} — Login wird ggf. nicht funktionieren")
        else:
            print_fn("  ✓  dorfkern hat jetzt Login-Shell /bin/bash")
    else:
        print_fn(f"  ✓  dorfkern hat bereits Login-Shell ({shell}) — unveraendert")

    # ── 4) LightDM-Autologin nur wenn nicht schon ein anderer User
    #       konfiguriert ist ─────────────────────────────────────
    existing_user = _existing_autologin()
    if existing_user:
        print_fn(f"  ↷  LightDM-Autologin ist bereits auf User "
                 f"'{existing_user}' konfiguriert — nicht ueberschrieben.")
        print_fn("     Falls du auf Kiosk umstellen willst:")
        print_fn(f"       Datei in {_KIOSK_LIGHTDM_DIR}/ anpassen:")
        print_fn("         autologin-user=dorfkern")
        print_fn("         autologin-session=dorfkern-kiosk")
        print_fn("     Oder die Session 'Dorfkern Kiosk' manuell im "
                 "Login-Bildschirm waehlen.")
    else:
        if not _install_file_sudo(_KIOSK_LIGHTDM_CONF,
                                   _KIOSK_LIGHTDM_TEMPLATE,
                                   mode='0644', print_fn=print_fn):
            return False

    # ── 5) lightdm enablen nur wenn kein anderer DM aktiv ──────
    active_dm = _active_display_manager()
    if active_dm and active_dm != 'lightdm':
        print_fn(f"  ↷  {active_dm} ist als Display-Manager aktiv — "
                 "lightdm wird NICHT umgeschaltet.")
        print_fn("     Wenn du wirklich auf lightdm umsteigen willst:")
        print_fn(f"       sudo systemctl disable {active_dm}")
        print_fn("       sudo systemctl enable lightdm")
    else:
        print_fn("  → systemctl enable lightdm …")
        r = _run(_maybe_sudo(['systemctl', 'enable', 'lightdm']))
        if r.returncode != 0:
            print_fn(f"  ⚠  systemctl enable lightdm: {_err(r)}")
        else:
            print_fn("  ✓  lightdm wird beim naechsten Boot gestartet")

    print_fn("")
    print_fn(f"  Kiosk-URL: {url}")
    print_fn("  Die Dorfkern-Kiosk-Session ist im LightDM-Greeter waehlbar.")
    if existing_user is None and (not active_dm or active_dm == 'lightdm'):
        print_fn("  Beim naechsten Reboot booted die Box automatisch in den")
        print_fn("  Kiosk (5-Sek-Countdown, dann Chromium-Vollbild).")
    else:
        print_fn("  Manuelle Auswahl im Login-Bildschirm noetig "
                 "(siehe Hinweise oben).")
    return True


def uninstall_kiosk(*, print_fn: PrintFn = print) -> bool:
    """Entfernt LightDM-Config + Dorfkern-Session-Files.

    Belaesst:
      - apt-Pakete (lightdm, xorg, chromium, openbox) — koennten anderswo
        gebraucht werden
      - dorfkern-Login-Shell — User koennte sich anderweitig einloggen
        muessen
    """
    for path in (_KIOSK_LIGHTDM_CONF, f'{_KIOSK_LIGHTDM_CONF}.off',
                 _KIOSK_SESSION_DESKTOP, _KIOSK_SESSION_SCRIPT,
                 _KIOSK_MAINTENANCE_SCRIPT):
        if not os.path.exists(path):
            continue
        r = _run(_maybe_sudo(['rm', '-f', path]))
        if r.returncode == 0:
            print_fn(f"  ✓  geloescht: {path}")
        else:
            print_fn(f"  ✗  rm {path}: {_err(r)}")
    print_fn("  Hinweis: lightdm bleibt enabled; bei Bedarf manuell")
    print_fn("    sudo systemctl disable lightdm")
    return True
