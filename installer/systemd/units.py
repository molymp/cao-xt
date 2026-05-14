"""
Generierung der systemd-Unit-Files fuer Dorfkern.

Pro App ein Service-Unit (4 Web-Apps + 2 Daemons), plus
``<prefix>.target`` als gemeinsamer Aufhaenger. Drei Achsen, die
sich orthogonal kombinieren lassen:

  mode          'system'  – /etc/systemd/system, eigener System-User
                'user'    – ~/.config/systemd/user, Login-User

  instance_name ''        – Default: Praefix 'dorfkern', Pfade ohne Suffix
                'prod'    – Praefix 'dorfkern-prod', /opt/dorfkern-prod, ...
                'dev'     – Praefix 'dorfkern-dev', /opt/dorfkern-dev, ...

  base_port     5000      – Default: admin=5004, orga=5003, kasse=5002, kiosk=5001
                5100      – admin=5104, orga=5103, kasse=5102, kiosk=5101

So koennen DEV und PROD parallel auf derselben Box laufen, jeder mit
eigenem System-User, eigenen Pfaden, eigenen Ports und eigenen Units.

Die Funktionen hier liefern reine Strings — geschrieben wird nichts.
File-I/O + Rechte sind Sache des Aufrufers (``installer/systemd/host_setup.py``
oder die CLI unten).

CLI:
  python3 -m installer.systemd.units --print
  python3 -m installer.systemd.units --mode user --print
  python3 -m installer.systemd.units --instance prod --base-port 5100 --print
  python3 -m installer.systemd.units --write /etc/systemd/system
"""
import argparse
import getpass
import os
import sys
from typing import Dict, List, Optional


# Defaults fuer die system-Mode-Installation (leerer Instanz-Name).
DEFAULT_INSTALL_ROOT = '/opt/dorfkern'
DEFAULT_USER         = 'dorfkern'
DEFAULT_GROUP        = 'dorfkern'
DEFAULT_BASE_PORT    = 5000

# Port-Offsets der Web-Apps. Liegen nahe an den historischen Ports
# (5001-5004 = base 5000). Bewusst hier dupliziert mit common.config —
# das common-Modul ist die Single Source of Truth fuer Runtime-Code,
# units.py muss aber ohne common-Import lauffaehig bleiben (CI-Render-
# Tests, ggf. Bootstrap-Pfade).
APP_PORT_OFFSETS: Dict[str, int] = {
    'admin': 4,
    'orga':  3,
    'kasse': 2,
    'kiosk': 1,
}

# App-Definitionen. Ports werden zur Laufzeit aus base_port berechnet,
# stehen darum hier nicht mehr fix drin.
_WEB_APPS: Dict[str, Dict[str, str]] = {
    'admin': {'app_dir': 'admin-app/app', 'label': 'Admin-App'},
    'orga':  {'app_dir': 'orga-app/app',  'label': 'Orga-App'},
    'kasse': {'app_dir': 'kasse-app/app', 'label': 'Kassen-App'},
    'kiosk': {'app_dir': 'kiosk-app/app', 'label': 'Kiosk-App'},
}

_DAEMONS: Dict[str, Dict[str, str]] = {
    'haccp-poller':   {'module': 'modules.haccp.poller',
                       'label': 'HACCP-Poller (TFA-Sensoren)'},
    'einkauf-poller': {'module': 'installer.einkauf_poller',
                       'label': 'Einkauf-Poller (Gmail)'},
}

# Start-Reihenfolge: admin (Stammdaten), orga (HACCP-Tabellen),
# Poller, dann Kasse/Kiosk. Identisch zu app_manager.START_ORDER.
START_ORDER: List[str] = ['admin', 'orga', 'haccp-poller',
                          'einkauf-poller', 'kasse', 'kiosk']


# ──────────────────────────────────────────────────────────────
# Templates
# ──────────────────────────────────────────────────────────────

_WEB_TEMPLATE = """\
[Unit]
Description=Dorfkern {desc}
{after_block}
PartOf={target_unit}

[Service]
Type=simple
{owner_block}WorkingDirectory={install_root}/{app_dir}
ExecStart={install_root}/.venv/bin/python3 app.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5s
TimeoutStartSec=60

# Logs gehen nach journald — Abruf via:
#   journalctl{journal_user_flag} -u {full_name} -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier={full_name}
"""

_DAEMON_TEMPLATE = """\
[Unit]
Description=Dorfkern {desc}
{after_block}
PartOf={target_unit}

[Service]
Type=simple
{owner_block}WorkingDirectory={install_root}
ExecStart={install_root}/.venv/bin/python3 -m {module}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10s

StandardOutput=journal
StandardError=journal
SyslogIdentifier={full_name}
"""

_TARGET_TEMPLATE = """\
[Unit]
Description=Dorfkern {instance_label}(alle Apps)
Wants={wants}
{target_after_block}

[Install]
WantedBy={target_install_target}
"""


_MODES = ('system', 'user')


# ──────────────────────────────────────────────────────────────
# Namens-Helper (instanz-aware)
# ──────────────────────────────────────────────────────────────

def systemd_prefix(instance_name: str = '') -> str:
    """'dorfkern' (leer) oder 'dorfkern-<instance>' (mit Name).

    Spiegelt common.config.systemd_prefix, damit units.py ohne
    Cross-Modul-Import auskommt.
    """
    name = (instance_name or '').strip()
    return f'dorfkern-{name}' if name else 'dorfkern'


def unit_name(app: str, instance_name: str = '') -> str:
    """Service-Unit-Name fuer eine App.

    Default-Instanz: 'admin' -> 'dorfkern-admin.service'.
    Mit Instanz 'prod': 'admin' -> 'dorfkern-prod-admin.service'.
    """
    return f'{systemd_prefix(instance_name)}-{app}.service'


def target_name(instance_name: str = '') -> str:
    """Target-Unit-Name. Default 'dorfkern.target', sonst 'dorfkern-<inst>.target'."""
    return f'{systemd_prefix(instance_name)}.target'


def all_app_names() -> List[str]:
    """Alle App-Namen in Start-Reihenfolge."""
    return list(START_ORDER)


def is_known(name: str) -> bool:
    return name in _WEB_APPS or name in _DAEMONS


def app_port(app: str, base_port: int = DEFAULT_BASE_PORT) -> int:
    """Berechnet den TCP-Port einer Web-App fuer eine gegebene Port-Base."""
    try:
        return base_port + APP_PORT_OFFSETS[app]
    except KeyError as exc:
        raise KeyError(f'Unbekannte App: {app!r}') from exc


# ──────────────────────────────────────────────────────────────
# Render-Helper (Mode-spezifisch)
# ──────────────────────────────────────────────────────────────

def _render_owner_block(mode: str, user: str, group: str) -> str:
    """User=/Group=-Zeilen fuer System-Mode; leer fuer User-Mode."""
    if mode == 'user':
        return ''
    return f'User={user}\nGroup={group}\n'


def _render_after_block(mode: str) -> str:
    """After=/Wants= fuer Service-Unit-Header."""
    if mode == 'user':
        return 'After=default.target'
    return ('After=network-online.target mariadb.service\n'
            'Wants=network-online.target')


def _render_target_after_block(mode: str) -> str:
    if mode == 'user':
        return 'After=default.target'
    return 'After=network-online.target mariadb.service'


def _render_target_install_target(mode: str) -> str:
    return 'default.target' if mode == 'user' else 'multi-user.target'


def _journal_user_flag(mode: str) -> str:
    return ' --user' if mode == 'user' else ''


def _desc(app: str, *, base_port: int, instance_name: str) -> str:
    """Lesbare Beschreibung fuer den [Unit]-Description-Eintrag."""
    suffix = f' [{instance_name}]' if instance_name else ''
    if app in _WEB_APPS:
        port = app_port(app, base_port)
        return f'{_WEB_APPS[app]["label"]} (Port {port}){suffix}'
    if app in _DAEMONS:
        return f'{_DAEMONS[app]["label"]}{suffix}'
    raise KeyError(f'Unbekannte App: {app!r}')


# ──────────────────────────────────────────────────────────────
# Render-Funktionen (oeffentliche API)
# ──────────────────────────────────────────────────────────────

def render_unit(name: str, *,
                mode: str = 'system',
                instance_name: str = '',
                base_port: int = DEFAULT_BASE_PORT,
                install_root: str = DEFAULT_INSTALL_ROOT,
                user: str = DEFAULT_USER,
                group: str = DEFAULT_GROUP) -> str:
    """Rendert das Unit-File einer einzelnen App.

    Args:
        name: App-Name aus ``START_ORDER``.
        mode: 'system' (Default) oder 'user'.
        instance_name: Suffix fuer Unit-/Target-Namen (leer = 'dorfkern').
        base_port: Port-Base, von dem aus die Web-App-Ports berechnet werden.
        install_root: Repo-Wurzel im Zielsystem.
        user, group: nur in mode='system' relevant.
    """
    if mode not in _MODES:
        raise ValueError(f'Unbekannter mode: {mode!r}, erwartet einen von {_MODES}')

    owner_block  = _render_owner_block(mode, user, group)
    after_block  = _render_after_block(mode)
    journal_flag = _journal_user_flag(mode)
    full_name    = f'{systemd_prefix(instance_name)}-{name}'
    target_unit  = target_name(instance_name)
    desc         = _desc(name, base_port=base_port, instance_name=instance_name)

    if name in _WEB_APPS:
        cfg = _WEB_APPS[name]
        return _WEB_TEMPLATE.format(
            desc=desc,
            full_name=full_name,
            app_dir=cfg['app_dir'],
            install_root=install_root,
            owner_block=owner_block,
            after_block=after_block,
            target_unit=target_unit,
            journal_user_flag=journal_flag,
        )
    if name in _DAEMONS:
        cfg = _DAEMONS[name]
        return _DAEMON_TEMPLATE.format(
            desc=desc,
            full_name=full_name,
            module=cfg['module'],
            install_root=install_root,
            owner_block=owner_block,
            after_block=after_block,
            target_unit=target_unit,
        )
    raise KeyError(f'Unbekannte App: {name}')


def render_target(*, mode: str = 'system',
                  instance_name: str = '',
                  apps: Optional[List[str]] = None) -> str:
    """Rendert die ``<prefix>.target``-Datei.

    Args:
        apps: Nur diese Apps werden im ``Wants=`` aufgefuehrt. None heisst
            "alle". So spiegelt das Target die App-Auswahl aus Phase 3.
    """
    if mode not in _MODES:
        raise ValueError(f'Unbekannter mode: {mode!r}, erwartet einen von {_MODES}')
    selected = apps if apps else START_ORDER
    wants = ' '.join(unit_name(a, instance_name) for a in selected
                     if a in START_ORDER)
    instance_label = f"({instance_name}) " if instance_name else ''
    return _TARGET_TEMPLATE.format(
        instance_label=instance_label,
        wants=wants,
        target_after_block=_render_target_after_block(mode),
        target_install_target=_render_target_install_target(mode),
    )


def render_all(*, mode: str = 'system',
               instance_name: str = '',
               base_port: int = DEFAULT_BASE_PORT,
               install_root: str = DEFAULT_INSTALL_ROOT,
               user: str = DEFAULT_USER,
               group: str = DEFAULT_GROUP,
               apps: Optional[List[str]] = None,
               include_target: bool = True) -> Dict[str, str]:
    """Rendert alle Service-Units + (optional) Target. Key ist der Dateiname.

    Service-Units werden IMMER fuer alle bekannten Apps gerendert
    (idle solange sie keiner started). Das ``apps``-Argument steuert
    nur, was im Target als ``Wants=`` steht.

    Args:
        include_target: Wenn False, wird die Target-Datei NICHT gerendert.
            Praktisch fuer Updates — die urspruengliche App-Auswahl im
            Target bleibt erhalten, waehrend Service-Unit-Files (ExecStart,
            Restart-Policy, ...) trotzdem aktualisiert werden.

    Im User-Mode werden ``user``/``group`` ignoriert.
    """
    rendered: Dict[str, str] = {}
    for name in START_ORDER:
        rendered[unit_name(name, instance_name)] = render_unit(
            name, mode=mode,
            instance_name=instance_name, base_port=base_port,
            install_root=install_root, user=user, group=group,
        )
    if include_target:
        rendered[target_name(instance_name)] = render_target(
            mode=mode, instance_name=instance_name, apps=apps,
        )
    return rendered


def _default_install_root(mode: str, instance_name: str = '') -> str:
    """Sinnvoller Install-Root-Default fuer Modus + Instanz.

    System-Mode + leere Instanz: /opt/dorfkern
    System-Mode + 'prod':         /opt/dorfkern-prod
    User-Mode (egal welche Instanz): das aktuelle Repo, das den Aufruf
        gerade tut (units.py liegt unter <repo>/installer/systemd/).
    """
    if mode == 'user':
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..'))
    return f'/opt/{systemd_prefix(instance_name)}'


def _cli() -> int:
    p = argparse.ArgumentParser(
        description='Dorfkern systemd-Units generieren',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Beispiele:\n'
            '  python3 -m installer.systemd.units --print\n'
            '  python3 -m installer.systemd.units --mode user --print\n'
            '  python3 -m installer.systemd.units --instance prod --base-port 5100 --print\n'
            '  sudo python3 -m installer.systemd.units --write /etc/systemd/system\n'
            '  python3 -m installer.systemd.units --mode user '
            '--write ~/.config/systemd/user\n'
        ),
    )
    p.add_argument('--mode', choices=_MODES, default='system',
                   help='system (Default) | user')
    p.add_argument('--instance', dest='instance_name', default='',
                   help='Instanz-Name (leer = Default). Suffix fuer Unit-/Pfad-Namen.')
    p.add_argument('--base-port', type=int, default=DEFAULT_BASE_PORT,
                   help=f'Port-Base (Default: {DEFAULT_BASE_PORT})')
    p.add_argument('--print', dest='print_only', action='store_true',
                   help='Alle Units nach stdout (Default falls --write fehlt)')
    p.add_argument('--write', metavar='DIR',
                   help='Units in DIR schreiben (Verzeichnis muss existieren)')
    p.add_argument('--install-root', default='',
                   help='Installations-Root (Default je nach Modus+Instanz)')
    p.add_argument('--user',  default='',
                   help=f'Service-User (nur system; Default: {DEFAULT_USER})')
    p.add_argument('--group', default='',
                   help=f'Service-Group (nur system; Default: {DEFAULT_GROUP})')
    args = p.parse_args()

    install_root = args.install_root or _default_install_root(args.mode,
                                                                args.instance_name)
    user  = args.user  or DEFAULT_USER
    group = args.group or DEFAULT_GROUP

    rendered = render_all(
        mode=args.mode,
        instance_name=args.instance_name,
        base_port=args.base_port,
        install_root=install_root,
        user=user, group=group,
    )

    if args.write:
        target_dir = os.path.expanduser(args.write)
        if not os.path.isdir(target_dir):
            p.error(f'Verzeichnis nicht gefunden: {target_dir}')
        for fname, content in rendered.items():
            path = os.path.join(target_dir, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'  geschrieben: {path}')
        print()
        target = target_name(args.instance_name)
        print('  Naechste Schritte:')
        if args.mode == 'user':
            user_name = getpass.getuser()
            print(f'    sudo loginctl enable-linger {user_name}')
            print('    systemctl --user daemon-reload')
            print(f'    systemctl --user enable --now {target}')
        else:
            print('    sudo systemctl daemon-reload')
            print(f'    sudo systemctl enable --now {target}')
        return 0

    for fname, content in rendered.items():
        sep = '─' * max(0, 60 - len(fname))
        print(f'# ── {fname} {sep}')
        print(content)
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
