#!/usr/bin/env python3
"""
CAO-XT Installationsroutine – Interaktives Setup

Phasen:
  1. DB-Verbindung testen → caoxt.ini schreiben
  2. DB initialisieren (CAO oder leer)
  3. Umgebung festlegen (produktion / training)
  4. Apps auswählen und starten
  5. Health-Check + Abschlussbericht

Aufruf: python3 installer/install.py [--non-interactive]
"""
import argparse
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from installer.app_manager import start_all, stop_all, status_all, print_status, APPS, START_ORDER
from installer.db_init import (
    test_connection, detect_db_type,
    init_cao_db, init_empty_db, write_ini,
)

_INI_PATH = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

_BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║     CAO-XT Installationsroutine                         ║
║     Habacher Dorfladen                                  ║
╚══════════════════════════════════════════════════════════╝
"""

_APP_LABELS = {
    'admin':   'Admin-App    (Port 5004)',
    'orga':         'Orga-App           (Port 5003)',
    'kasse':        'Kassen-App         (Port 5002)',
    'kiosk':        'Kiosk-App          (Port 5001)',
    'haccp-poller': 'HACCP-Poller       (TFA-Temperatursensoren, Daemon)',
}


def _ask(prompt: str, default: str = '') -> str:
    """Liest eine Eingabe. Bei leerem Input wird default zurückgegeben."""
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


def phase1_db_config(non_interactive: bool = False) -> tuple[str, int, str, str, str]:
    """Phase 1: DB-Verbindung konfigurieren und testen."""
    _section("Phase 1: Datenbank-Konfiguration")

    if non_interactive:
        # Aus Umgebungsvariablen / bestehender INI lesen
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
            print("  ✗ Ungültiger Port – verwende 3306")
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


def phase3_environment(non_interactive: bool = False) -> str:
    """Phase 3: Betriebsumgebung festlegen."""
    _section("Phase 3: Betriebsumgebung")

    environments = {
        '1': 'produktion',
        '2': 'training',
    }

    if non_interactive:
        env = os.environ.get('XT_ENVIRONMENT', 'produktion').lower()
        if env not in ('produktion', 'training'):
            env = 'produktion'
        print(f"  Umgebung: {env}")
        return env

    print("  Wähle die Betriebsumgebung:")
    print("    1) Produktion  – Echtbetrieb mit echten Daten")
    print("    2) Training    – Testsystem, keine echten Buchungen")
    print()
    choice = _ask("Auswahl", "1")
    env = environments.get(choice, 'produktion')
    print(f"  ✓ Umgebung: {env}")
    return env


def _tfa_key_vorhanden() -> bool:
    """True, wenn TFA_API_KEY in config/Env gesetzt ist (-> Poller sinnvoll)."""
    # Env-Var hat Vorrang, dann orga-app/app/config.py
    if os.environ.get('TFA_API_KEY'):
        return True
    try:
        sys.path.insert(0, os.path.join(_REPO_ROOT, 'orga-app', 'app'))
        import config as wc  # noqa: WPS433
        return bool(getattr(wc, 'TFA_API_KEY', ''))
    except Exception:
        return False


def phase4_app_selection(non_interactive: bool = False) -> list[str]:
    """Phase 4: App-Auswahl."""
    _section("Phase 4: App-Auswahl")

    if non_interactive:
        # Im non-interactive Mode: alle Web-Apps, Poller nur wenn TFA-Key da.
        auswahl = [a for a in START_ORDER
                   if a != 'haccp-poller' or _tfa_key_vorhanden()]
        return auswahl

    print("  Welche Apps sollen gestartet werden?")
    print("  (Admin-App wird immer gestartet)")
    print()

    selected = ['admin']  # immer
    print(f"  ✓ admin           – Admin-App (Pflicht)")

    for app in ['orga', 'kasse', 'kiosk']:
        label = _APP_LABELS[app]
        if _ask_yes_no(f"  {label} starten?", True):
            selected.append(app)

    # HACCP-Poller: nur anbieten, wenn TFA-Key konfiguriert ist, sonst
    # wuerde der Daemon beim Start sofort mit 'TFA_API_KEY nicht
    # konfiguriert' abbrechen.
    if _tfa_key_vorhanden():
        label = _APP_LABELS['haccp-poller']
        if _ask_yes_no(f"  {label} starten?", True):
            # nach 'orga' einsortieren (Tabellen existieren dann)
            idx = selected.index('orga') + 1 if 'orga' in selected \
                  else len(selected)
            selected.insert(idx, 'haccp-poller')
    else:
        print("  –  HACCP-Poller übersprungen (TFA_API_KEY nicht gesetzt)")
        print("     Später mit  ./dorfkern-ctl start haccp-poller  starten.")

    return selected


def phase5_start_and_report(selected_apps: list[str]) -> None:
    """Phase 5: Apps starten und Bericht ausgeben."""
    _section("Phase 5: Apps starten")

    print()
    results = start_all(selected_apps)
    print()

    _section("Abschlussbericht")
    print_status()

    all_ok = all(results.get(app, False) for app in selected_apps)

    if all_ok:
        print("  ✓ Installation abgeschlossen")
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
        for app in selected_apps:
            cfg = APPS[app]
            print(f"    {app:<14}  {cfg['log']}")
    else:
        failed = [a for a in selected_apps if not results.get(a, False)]
        print(f"  ⚠  Folgende Apps konnten nicht gestartet werden: {', '.join(failed)}")
        print("     Bitte Logs prüfen.")

    print()


def phase4b_terminal_apps(terminal_typ: str) -> list[str]:
    """Phase 4 (Terminal-Rolle): nur EINE App auswaehlen.

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description='CAO-XT Installationsroutine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--non-interactive', action='store_true',
        help='Nicht-interaktiver Modus (nutzt Umgebungsvariablen / bestehende caoxt.ini)'
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
        host, port, name, user, password = phase1_db_config(True)
        # KEINE DB-Init (das ist Sache des Admin-Hosts).
        environment = phase3_environment(True)
        selected_apps = phase4b_terminal_apps(args.terminal_typ)
        _section("Konfiguration speichern")
        write_ini(
            _INI_PATH,
            host=host, port=port, name=name,
            user=user, password=password,
            environment=environment,
            active_apps=selected_apps,
        )
        print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")
        phase5_start_and_report(selected_apps)
        return

    # ── Admin-Rolle (Vollinstallation, Default) ──────────────
    # Phase 1: DB-Verbindung
    host, port, name, user, password = phase1_db_config(args.non_interactive)

    # Phase 2: DB initialisieren
    db_ok = phase2_db_init(host, port, name, user, password)
    if not db_ok and not args.non_interactive:
        if not _ask_yes_no("DB-Init fehlgeschlagen. Trotzdem fortfahren?", False):
            sys.exit(1)

    # Phase 3: Umgebung
    environment = phase3_environment(args.non_interactive)

    # Phase 4: App-Auswahl
    selected_apps = phase4_app_selection(args.non_interactive)

    # caoxt.ini schreiben
    _section("Konfiguration speichern")
    write_ini(
        _INI_PATH,
        host=host, port=port, name=name,
        user=user, password=password,
        environment=environment,
        active_apps=selected_apps,
    )
    print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")

    # Phase 5: Starten und Bericht
    phase5_start_and_report(selected_apps)


if __name__ == '__main__':
    main()
