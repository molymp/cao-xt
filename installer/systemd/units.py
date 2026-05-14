"""
Generierung der systemd-Unit-Files fuer Dorfkern.

Pro App ein Service-Unit (4 Web-Apps + 2 Daemons), plus
``dorfkern.target`` als gemeinsamer Aufhaenger. Zwei Modi:

  system  – Units gehoeren root, leben unter /etc/systemd/system/,
            laufen als dediziertem System-User (``dorfkern``). Klassische
            PROD-Installation; ``systemctl enable --now dorfkern.target``.

  user    – Units leben unter ~/.config/systemd/user/, laufen als der
            Login-User, der sie installiert. Boot-persistent, sobald
            ``loginctl enable-linger <user>`` einmalig gesetzt ist.
            Geeignet auch fuer Entwickler-Maschinen, die die Apps als
            Dienst statt ad-hoc laufen lassen wollen.

Die Funktionen hier liefern reine Strings — geschrieben wird nichts.
File-I/O + Rechte sind Sache des Aufrufers (``installer/systemd/host_setup.py``
oder die CLI unten).

CLI:
  python3 -m installer.systemd.units --print
  python3 -m installer.systemd.units --mode user --print
  python3 -m installer.systemd.units --write /etc/systemd/system
"""
import argparse
import getpass
import os
import sys
from typing import Dict, List, Optional


# Defaults fuer die system-Mode-Installation.
DEFAULT_INSTALL_ROOT = '/opt/dorfkern'
DEFAULT_USER         = 'dorfkern'
DEFAULT_GROUP        = 'dorfkern'

# App-Definitionen — Single Source of Truth fuer die systemd-Units.
# Aenderungen hier (Port, Modul) erfordern auf dem Host ein
# ``systemctl daemon-reload`` + neu erzeugte Units.
#
# Achtung: muss zu installer/app_manager.py:APPS passen. Wird dort
# bewusst dupliziert, damit dieses Modul ohne mysql.connector & Co.
# importierbar bleibt (z.B. fuer das blosse Rendern der Files).
_WEB_APPS: Dict[str, Dict[str, object]] = {
    'admin': {'port': 5004, 'app_dir': 'admin-app/app',
              'desc': 'Admin-App (Port 5004)'},
    'orga':  {'port': 5003, 'app_dir': 'orga-app/app',
              'desc': 'Orga-App (Port 5003)'},
    'kasse': {'port': 5002, 'app_dir': 'kasse-app/app',
              'desc': 'Kassen-App (Port 5002)'},
    'kiosk': {'port': 5001, 'app_dir': 'kiosk-app/app',
              'desc': 'Kiosk-App (Port 5001)'},
}

_DAEMONS: Dict[str, Dict[str, object]] = {
    'haccp-poller':   {'module': 'modules.haccp.poller',
                       'desc': 'HACCP-Poller (TFA-Sensoren)'},
    'einkauf-poller': {'module': 'installer.einkauf_poller',
                       'desc': 'Einkauf-Poller (Gmail)'},
}

# Start-Reihenfolge: admin (Stammdaten), orga (HACCP-Tabellen),
# Poller, dann Kasse/Kiosk. Identisch zu app_manager.START_ORDER.
START_ORDER: List[str] = ['admin', 'orga', 'haccp-poller',
                          'einkauf-poller', 'kasse', 'kiosk']


# ──────────────────────────────────────────────────────────────
# Templates
# ──────────────────────────────────────────────────────────────
#
# Felder mit {owner_block} / {after_block} / {target_install_target}
# werden je nach Modus gefuellt — siehe _render_owner_block etc.

_WEB_TEMPLATE = """\
[Unit]
Description=Dorfkern {desc}
{after_block}
PartOf=dorfkern.target

[Service]
Type=simple
{owner_block}WorkingDirectory={install_root}/{app_dir}
ExecStart={install_root}/.venv/bin/python3 app.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5s
TimeoutStartSec=60

# Logs gehen nach journald — Abruf via:
#   journalctl{journal_user_flag} -u dorfkern-{name} -f
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dorfkern-{name}
"""

_DAEMON_TEMPLATE = """\
[Unit]
Description=Dorfkern {desc}
{after_block}
PartOf=dorfkern.target

[Service]
Type=simple
{owner_block}WorkingDirectory={install_root}
ExecStart={install_root}/.venv/bin/python3 -m {module}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=10s

StandardOutput=journal
StandardError=journal
SyslogIdentifier=dorfkern-{name}
"""

_TARGET_TEMPLATE = """\
[Unit]
Description=Dorfkern (alle Apps)
Wants={wants}
{target_after_block}

[Install]
WantedBy={target_install_target}
"""


_MODES = ('system', 'user')


def _render_owner_block(mode: str, user: str, group: str) -> str:
    """User=/Group=-Zeilen fuer System-Mode; leer fuer User-Mode.

    User-Units uebernehmen automatisch die UID des aufrufenden Users.
    """
    if mode == 'user':
        return ''
    return f'User={user}\nGroup={group}\n'


def _render_after_block(mode: str) -> str:
    """After=/Wants= fuer Service-Unit-Header.

    System-Mode haengt am MariaDB-System-Dienst. User-Mode kennt
    keine systemweiten Dienste; wir warten nur auf das Erreichen
    der default.target.
    """
    if mode == 'user':
        return 'After=default.target'
    return ('After=network-online.target mariadb.service\n'
            'Wants=network-online.target')


def _render_target_after_block(mode: str) -> str:
    """After= fuer das dorfkern.target-File."""
    if mode == 'user':
        return 'After=default.target'
    return 'After=network-online.target mariadb.service'


def _render_target_install_target(mode: str) -> str:
    """WantedBy= fuer das dorfkern.target [Install]-Section."""
    return 'default.target' if mode == 'user' else 'multi-user.target'


def _journal_user_flag(mode: str) -> str:
    return ' --user' if mode == 'user' else ''


def unit_name(app: str) -> str:
    """Service-Unit-Name fuer eine App ('admin' -> 'dorfkern-admin.service')."""
    return f'dorfkern-{app}.service'


def all_app_names() -> List[str]:
    """Alle App-Namen in Start-Reihenfolge."""
    return list(START_ORDER)


def is_known(name: str) -> bool:
    return name in _WEB_APPS or name in _DAEMONS


def render_unit(name: str, *,
                mode: str = 'system',
                install_root: str = DEFAULT_INSTALL_ROOT,
                user: str = DEFAULT_USER,
                group: str = DEFAULT_GROUP) -> str:
    """Rendert das Unit-File einer einzelnen App.

    Args:
        name: App-Name aus ``START_ORDER``.
        mode: 'system' (Default) oder 'user'. Bestimmt, ob ``User=`` /
            ``Group=`` und system-Dienste-Abhaengigkeiten gerendert werden.
        install_root: Repo-Wurzel im Zielsystem.
        user, group: nur in mode='system' relevant.
    """
    if mode not in _MODES:
        raise ValueError(f'Unbekannter mode: {mode!r}, erwartet einen von {_MODES}')

    owner_block = _render_owner_block(mode, user, group)
    after_block = _render_after_block(mode)
    journal_flag = _journal_user_flag(mode)

    if name in _WEB_APPS:
        cfg = _WEB_APPS[name]
        return _WEB_TEMPLATE.format(
            name=name,
            desc=cfg['desc'],
            app_dir=cfg['app_dir'],
            install_root=install_root,
            owner_block=owner_block,
            after_block=after_block,
            journal_user_flag=journal_flag,
        )
    if name in _DAEMONS:
        cfg = _DAEMONS[name]
        return _DAEMON_TEMPLATE.format(
            name=name,
            desc=cfg['desc'],
            module=cfg['module'],
            install_root=install_root,
            owner_block=owner_block,
            after_block=after_block,
        )
    raise KeyError(f'Unbekannte App: {name}')


def render_target(*, mode: str = 'system',
                  apps: Optional[List[str]] = None) -> str:
    """Rendert das ``dorfkern.target``-File fuer den gegebenen Modus.

    Args:
        apps: Nur diese Apps werden im ``Wants=`` aufgefuehrt. None heisst
            "alle". So spiegelt das Target die App-Auswahl aus Phase 3
            wider — nicht-gewollte Apps starten nicht automatisch mit.
    """
    if mode not in _MODES:
        raise ValueError(f'Unbekannter mode: {mode!r}, erwartet einen von {_MODES}')
    selected = apps if apps else START_ORDER
    wants = ' '.join(unit_name(a) for a in selected if a in START_ORDER)
    return _TARGET_TEMPLATE.format(
        wants=wants,
        target_after_block=_render_target_after_block(mode),
        target_install_target=_render_target_install_target(mode),
    )


def render_all(*, mode: str = 'system',
               install_root: str = DEFAULT_INSTALL_ROOT,
               user: str = DEFAULT_USER,
               group: str = DEFAULT_GROUP,
               apps: Optional[List[str]] = None,
               include_target: bool = True) -> Dict[str, str]:
    """Rendert alle Service-Units + (optional) Target. Key ist der Dateiname.

    Service-Units werden IMMER fuer alle bekannten Apps gerendert
    (idle solange sie keiner started). Das ``apps``-Argument steuert
    nur, was im ``dorfkern.target`` als ``Wants=`` steht — also was beim
    Target-Start automatisch hochkommt.

    Args:
        include_target: Wenn False, wird die ``dorfkern.target``-Datei
            NICHT gerendert. Das ist fuer Updates praktisch: dort soll
            die urspruengliche User-Auswahl der Apps erhalten bleiben,
            waehrend die Service-Unit-Files (ExecStart, Restart-Policy,
            …) trotzdem aktualisiert werden.

    Im User-Mode werden ``user``/``group`` ignoriert.
    """
    units: Dict[str, str] = {}
    for name in START_ORDER:
        units[unit_name(name)] = render_unit(
            name, mode=mode,
            install_root=install_root, user=user, group=group,
        )
    if include_target:
        units['dorfkern.target'] = render_target(mode=mode, apps=apps)
    return units


def _default_install_root(mode: str) -> str:
    """Sinnvoller Install-Root-Default fuer den Modus.

    System-Mode: ``/opt/dorfkern`` (FHS-konform). User-Mode: das aktuelle
    Repo, das den Aufruf gerade tut — der User hat es ja dort liegen.
    """
    if mode == 'user':
        # installer/systemd/units.py -> Repo-Root liegt zwei Ebenen drueber.
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', '..'))
    return DEFAULT_INSTALL_ROOT


def _cli() -> int:
    p = argparse.ArgumentParser(
        description='Dorfkern systemd-Units generieren',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Beispiele:\n'
            '  python3 -m installer.systemd.units --print\n'
            '  python3 -m installer.systemd.units --mode user --print\n'
            '  sudo python3 -m installer.systemd.units --write /etc/systemd/system\n'
            '  python3 -m installer.systemd.units --mode user '
            '--write ~/.config/systemd/user\n'
        ),
    )
    p.add_argument('--mode', choices=_MODES, default='system',
                   help='system (Default) | user')
    p.add_argument('--print', dest='print_only', action='store_true',
                   help='Alle Units nach stdout ausgeben (Default falls --write fehlt)')
    p.add_argument('--write', metavar='DIR',
                   help='Units in DIR schreiben (Verzeichnis muss existieren)')
    p.add_argument('--install-root', default='',
                   help='Installations-Root (Default je nach Modus: '
                        f'{DEFAULT_INSTALL_ROOT} oder Repo-Wurzel)')
    p.add_argument('--user',  default=DEFAULT_USER,
                   help=f'Service-User (nur system; Default: {DEFAULT_USER})')
    p.add_argument('--group', default=DEFAULT_GROUP,
                   help=f'Service-Group (nur system; Default: {DEFAULT_GROUP})')
    args = p.parse_args()

    install_root = args.install_root or _default_install_root(args.mode)
    units = render_all(mode=args.mode, install_root=install_root,
                       user=args.user, group=args.group)

    if args.write:
        target_dir = os.path.expanduser(args.write)
        if not os.path.isdir(target_dir):
            p.error(f'Verzeichnis nicht gefunden: {target_dir}')
        for fname, content in units.items():
            path = os.path.join(target_dir, fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'  geschrieben: {path}')
        print()
        print('  Naechste Schritte:')
        if args.mode == 'user':
            user_name = getpass.getuser()
            print('    sudo loginctl enable-linger ' + user_name)
            print('    systemctl --user daemon-reload')
            print('    systemctl --user enable --now dorfkern.target')
        else:
            print('    sudo systemctl daemon-reload')
            print('    sudo systemctl enable --now dorfkern.target')
        return 0

    # Default: print
    for fname, content in units.items():
        sep = '─' * max(0, 60 - len(fname))
        print(f'# ── {fname} {sep}')
        print(content)
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
