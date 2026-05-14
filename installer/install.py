#!/usr/bin/env python3
"""
Dorfkern Installationsroutine – Interaktives Setup

Phasen:
  0. Installations-Typ waehlen (Ad-hoc / User-Dienst / System-Dienst)
  1. DB-Verbindung testen → caoxt.ini schreiben
  2. DB initialisieren (CAO oder leer)
  3. Apps auswaehlen
  4. Apps installieren + starten (Implementation haengt von Phase 0 ab)
  5. Abschlussbericht

Aufruf: python3 installer/install.py [--non-interactive]
Im non-interactive Modus liest Phase 0 die Variable XT_INSTALL_TYPE
(``ad_hoc`` (Default), ``service_user`` oder ``service_system``).
"""
import argparse
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer.app_manager import (
    start_all, print_status, APPS, START_ORDER,
)
from installer.db_init import (
    test_connection, detect_db_type,
    init_cao_db, init_empty_db, write_ini,
)
from installer.systemd import host_setup, manager as systemd_manager

_INI_PATH = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

_BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║     Dorfkern Installationsroutine                       ║
║     (vormals CAO-XT)                                    ║
╚══════════════════════════════════════════════════════════╝
"""

_APP_LABELS = {
    'admin':        'Admin-App          (Port 5004)',
    'orga':         'Orga-App           (Port 5003)',
    'kasse':        'Kassen-App         (Port 5002)',
    'kiosk':        'Kiosk-App          (Port 5001)',
    'haccp-poller': 'HACCP-Poller       (TFA-Temperatursensoren, Daemon)',
}

# Installations-Typen. Werte gehen 1:1 in XT_INSTALL_TYPE.
INSTALL_TYPES = ('ad_hoc', 'service_user', 'service_system')


def _ask(prompt: str, default: str = '') -> str:
    """Liest eine Eingabe. Bei leerem Input wird default zurueckgegeben."""
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "[J/n]" if default else "[j/N]"
    try:
        val = input(f"  {prompt} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if not val:
        return default
    return val in ('j', 'ja', 'y', 'yes')


def _section(title: str) -> None:
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


# ─── Phase 0: Installationstyp ────────────────────────────────────────

_TYPE_LABEL = {
    'ad_hoc':         'Entwicklung (ad-hoc)',
    'service_user':   'Dienst pro Benutzer',
    'service_system': 'Dienst systemweit',
}


def phase0_install_type(non_interactive: bool = False) -> str:
    """Phase 0: Installationstyp festlegen."""
    _section("Phase 0: Installations-Typ")

    if non_interactive:
        env = os.environ.get('XT_INSTALL_TYPE', 'ad_hoc').strip().lower()
        if env not in INSTALL_TYPES:
            print(f"  ⚠  XT_INSTALL_TYPE={env!r} ist unbekannt — falle auf 'ad_hoc' zurueck.")
            env = 'ad_hoc'
        print(f"  Installationstyp: {env}  ({_TYPE_LABEL[env]})")
        _validate_install_type(env, exit_on_error=True)
        return env

    print("  Wie soll Dorfkern auf diesem Rechner laufen?")
    print()
    print("    1) Entwicklung (ad-hoc)")
    print("       Apps starten als Popen-Kinder dieses Skripts. Sterben mit")
    print("       der Login-Session, kein systemd, kein root. Schnell.")
    print()
    print("    2) Dienst pro Benutzer")
    print("       systemd-User-Units in ~/.config/systemd/user/. Apps laufen")
    print("       als dieser User; mit Lingering boot-persistent. Sinnvoll")
    print("       fuer Entwicklungsmaschinen, die die Apps dauerhaft brauchen.")
    print()
    print("    3) Dienst systemweit")
    print("       systemd-System-Units in /etc/systemd/system/. Apps laufen")
    print("       unter dem System-User 'dorfkern'. Klassische PROD-Installation;")
    print("       setzt voraus, dass dieser Installer mit sudo gestartet wurde.")
    print()
    choice = _ask("Auswahl (1/2/3)", "1")
    install_type = {
        '1': 'ad_hoc',
        '2': 'service_user',
        '3': 'service_system',
    }.get(choice)
    if install_type is None:
        print(f"  ✗ Ungueltige Auswahl: {choice!r}")
        sys.exit(1)
    print(f"  ✓ {_TYPE_LABEL[install_type]}")
    _validate_install_type(install_type, exit_on_error=True)
    return install_type


def _validate_install_type(install_type: str, *, exit_on_error: bool) -> bool:
    """Prueft Voraussetzungen fuer den Typ. Bei Fehler optional exit().

    Returns True wenn alles OK, sonst False (nur relevant wenn exit_on_error=False).
    """
    if install_type == 'service_system':
        if os.geteuid() != 0:
            print()
            print("  ✗ 'Dienst systemweit' setzt root voraus.")
            print("    Bitte neu starten:  sudo ./install.sh")
            if exit_on_error:
                sys.exit(1)
            return False
        # Repo sollte unter /opt/dorfkern liegen — sonst warnen.
        # (Hartes Verschieben machen wir nicht; das soll der User selbst.)
        if _REPO_ROOT != '/opt/dorfkern':
            print()
            print(f"  ⚠  Das Repo liegt unter {_REPO_ROOT!r}, nicht unter /opt/dorfkern.")
            print("     Fuer die System-Installation ist /opt/dorfkern der erwartete")
            print("     Pfad. Du kannst trotzdem fortfahren — die Units werden mit")
            print("     dem aktuellen Pfad gerendert. Spaeteres Verschieben braucht")
            print("     dann ein erneutes ./install.sh.")
            if not _ask_yes_no("Mit aktuellem Pfad fortfahren?", True):
                if exit_on_error:
                    sys.exit(1)
                return False
    return True


# ─── Phase 1: DB ──────────────────────────────────────────────────────

def phase1_db_config(non_interactive: bool = False) -> tuple[str, int, str, str, str]:
    """Phase 1: DB-Verbindung konfigurieren und testen."""
    _section("Phase 1: Datenbank-Konfiguration")

    if non_interactive:
        from common.config import load_db_config
        cfg = load_db_config()
        host, port = cfg['host'], cfg['port']
        name, user, password = cfg['name'], cfg['user'], cfg['password']
        print(f"  Verwende bestehende Konfiguration: {user}@{host}:{port}/{name}")
    else:
        print("  Bitte gib die Verbindungsdaten zur MariaDB/MySQL-Datenbank ein:")
        print()
        host     = _ask("Hostname / IP", "localhost")
        port_str = _ask("Port",          "3306")
        try:
            port = int(port_str)
        except ValueError:
            print("  ✗ Ungueltiger Port – verwende 3306")
            port = 3306
        name     = _ask("Datenbankname")
        user     = _ask("Benutzername")
        import getpass
        try:
            password = getpass.getpass("  Passwort: ")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    print()
    print("  Verbindung wird getestet …")
    ok, err = test_connection(host, port, name, user, password)
    if not ok:
        print(f"  ✗ Verbindung fehlgeschlagen: {err}")
        if non_interactive:
            sys.exit(1)
        if not _ask_yes_no("Trotzdem fortfahren?", False):
            sys.exit(1)
    else:
        print("  ✓ Verbindung erfolgreich")

    return host, port, name, user, password


def phase2_db_init(host: str, port: int, name: str,
                   user: str, password: str,
                   print_fn=print) -> bool:
    """Phase 2: DB initialisieren."""
    _section("Phase 2: Datenbank initialisieren")

    db_type = detect_db_type(host, port, name, user, password)

    if db_type == 'cao':
        return init_cao_db(host, port, name, user, password, print_fn=print_fn)
    elif db_type == 'empty':
        return init_empty_db(host, port, name, user, password, print_fn=print_fn)
    else:
        print_fn("  ✗ DB-Typ nicht erkannt – Verbindung konnte nicht hergestellt werden")
        return False


def _tfa_key_vorhanden() -> bool:
    """True, wenn TFA_API_KEY in config/Env gesetzt ist (-> Poller sinnvoll)."""
    if os.environ.get('TFA_API_KEY'):
        return True
    try:
        sys.path.insert(0, os.path.join(_REPO_ROOT, 'orga-app', 'app'))
        import config as wc  # noqa: WPS433
        return bool(getattr(wc, 'TFA_API_KEY', ''))
    except Exception:
        return False


def phase3_app_selection(non_interactive: bool = False) -> list[str]:
    """Phase 3: App-Auswahl."""
    _section("Phase 3: App-Auswahl")

    if non_interactive:
        auswahl = [a for a in START_ORDER
                   if a != 'haccp-poller' or _tfa_key_vorhanden()]
        return auswahl

    print("  Welche Apps sollen gestartet werden?")
    print("  (Admin-App wird immer gestartet)")
    print()

    selected = ['admin']
    print(f"  ✓ admin           – Admin-App (Pflicht)")

    for app in ['orga', 'kasse', 'kiosk']:
        label = _APP_LABELS[app]
        if _ask_yes_no(f"  {label} starten?", True):
            selected.append(app)

    if _tfa_key_vorhanden():
        label = _APP_LABELS['haccp-poller']
        if _ask_yes_no(f"  {label} starten?", True):
            idx = selected.index('orga') + 1 if 'orga' in selected \
                  else len(selected)
            selected.insert(idx, 'haccp-poller')
    else:
        print("  –  HACCP-Poller uebersprungen (TFA_API_KEY nicht gesetzt)")
        print("     Spaeter mit  ./dorfkern-ctl start haccp-poller  starten.")

    return selected


# ─── Phase 4: Installation + Start ────────────────────────────────────

def phase4_install_and_start(selected_apps: list[str],
                              install_type: str) -> bool:
    """Phase 4: Apps tatsaechlich starten (oder als Dienste installieren).

    Returns True, wenn alle Apps (vermutlich) laufen.
    """
    _section(f"Phase 4: {_TYPE_LABEL[install_type]} einrichten + starten")
    print()

    if install_type == 'ad_hoc':
        results = start_all(selected_apps)
        return all(results.get(a, False) for a in selected_apps)

    if install_type == 'service_user':
        ok = host_setup.install_user(
            install_root=_REPO_ROOT,
            selected_apps=selected_apps,
            enable_lingering=True,
            start_after_enable=True,
        )
        systemd_manager.invalidate_cache()
        return ok

    if install_type == 'service_system':
        ok = host_setup.install_system(
            install_root=_REPO_ROOT,
            selected_apps=selected_apps,
            start_after_enable=True,
        )
        systemd_manager.invalidate_cache()
        return ok

    print(f"  ✗ Unbekannter Installationstyp: {install_type!r}")
    return False


# ─── Phase 5: Abschlussbericht ────────────────────────────────────────

def phase5_report(selected_apps: list[str], install_type: str, ok: bool) -> None:
    """Phase 5: Status + Adressen + Logs ausgeben."""
    _section("Abschlussbericht")
    print_status()

    if ok:
        print("  ✓ Installation abgeschlossen")
    else:
        print("  ⚠  Installation mit Problemen — siehe Logs.")

    print()
    print(f"  Modus: {_TYPE_LABEL[install_type]}")
    print()
    print("  Adressen:")
    for app in selected_apps:
        cfg = APPS[app]
        if cfg.get('type', 'web') == 'daemon':
            print(f"    {app:<14}  (Daemon, kein HTTP-Port)")
        else:
            print(f"    {app:<14}  http://localhost:{cfg['port']}")

    print()
    print("  Logs:")
    if install_type == 'ad_hoc':
        for app in selected_apps:
            cfg = APPS[app]
            print(f"    {app:<14}  {cfg['log']}")
    else:
        flag = ' --user' if install_type == 'service_user' else ''
        for app in selected_apps:
            print(f"    {app:<14}  journalctl{flag} -u dorfkern-{app}")

    print()
    print("  Steuerung:")
    print(f"    ./dorfkern-ctl status")
    print(f"    ./dorfkern-ctl restart <app>")
    print()


def phase3b_terminal_apps(terminal_typ: str) -> list[str]:
    """Phase 3 (Terminal-Rolle): nur EINE App auswaehlen.

    KIOSK → kiosk-app, KASSE → kasse-app, ORGA → orga-app. Admin-App
    laeuft nur auf dem Admin-Host.
    """
    mapping = {'KIOSK': 'kiosk', 'KASSE': 'kasse', 'ORGA': 'orga'}
    app = mapping.get(terminal_typ.upper())
    if app is None:
        print(f"  ✗ Unbekannter Terminal-Typ: {terminal_typ}")
        sys.exit(1)
    print(f"  ✓ Terminal-Rolle: {terminal_typ} → startet {app}-App")
    return [app]


# ─── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Dorfkern Installationsroutine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--non-interactive', action='store_true',
        help='Nicht-interaktiver Modus (nutzt Umgebungsvariablen / bestehende caoxt.ini). '
             'Installations-Typ ueber XT_INSTALL_TYPE.'
    )
    parser.add_argument(
        '--role', choices=['admin', 'terminal'], default='admin',
        help='admin: Vollinstallation (Default). terminal: nur eine '
             'Terminal-App (Kiosk/Kasse/Orga); setzt --non-interactive voraus.'
    )
    parser.add_argument(
        '--terminal-typ', default='',
        help='Bei --role terminal: KIOSK | KASSE | ORGA.'
    )
    args = parser.parse_args()

    print(_BANNER)

    # ── Terminal-Rolle: Schnell-Pfad fuer Mass-Rollout ─────────
    if args.role == 'terminal':
        if not args.non_interactive:
            print("  ✗ --role terminal erfordert --non-interactive")
            sys.exit(1)
        if not args.terminal_typ:
            print("  ✗ --role terminal erfordert --terminal-typ")
            sys.exit(1)
        install_type  = phase0_install_type(True)
        host, port, name, user, password = phase1_db_config(True)
        # KEINE DB-Init (das ist Sache des Admin-Hosts).
        selected_apps = phase3b_terminal_apps(args.terminal_typ)
        _section("Konfiguration speichern")
        write_ini(
            _INI_PATH,
            host=host, port=port, name=name,
            user=user, password=password,
            active_apps=selected_apps,
        )
        print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")
        ok = phase4_install_and_start(selected_apps, install_type)
        phase5_report(selected_apps, install_type, ok)
        return

    # ── Admin-Rolle (Vollinstallation, Default) ──────────────
    install_type = phase0_install_type(args.non_interactive)
    host, port, name, user, password = phase1_db_config(args.non_interactive)
    db_ok = phase2_db_init(host, port, name, user, password)
    if not db_ok and not args.non_interactive:
        if not _ask_yes_no("DB-Init fehlgeschlagen. Trotzdem fortfahren?", False):
            sys.exit(1)
    selected_apps = phase3_app_selection(args.non_interactive)

    _section("Konfiguration speichern")
    write_ini(
        _INI_PATH,
        host=host, port=port, name=name,
        user=user, password=password,
        active_apps=selected_apps,
    )
    print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")

    ok = phase4_install_and_start(selected_apps, install_type)
    phase5_report(selected_apps, install_type, ok)


if __name__ == '__main__':
    main()
