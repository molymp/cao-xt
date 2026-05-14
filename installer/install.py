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


def phase0_install_type(non_interactive: bool = False) -> dict:
    """Phase 0: Installationstyp + Instanz-Name + Port-Base festlegen.

    Returns dict mit:
        install_type:    'ad_hoc' | 'service_user' | 'service_system'
        instance_name:   str (leer = Default-Praefix 'dorfkern')
        base_port:       int (Default 5000 -> Apps 5001-5004)
    """
    _section("Phase 0: Installations-Typ")

    if non_interactive:
        env = os.environ.get('XT_INSTALL_TYPE', 'ad_hoc').strip().lower()
        if env not in INSTALL_TYPES:
            print(f"  ⚠  XT_INSTALL_TYPE={env!r} ist unbekannt — falle auf 'ad_hoc' zurueck.")
            env = 'ad_hoc'
        instance_name = os.environ.get('XT_INSTANCE_NAME', '').strip()
        try:
            base_port = int(os.environ.get('XT_BASE_PORT', '5000'))
        except ValueError:
            base_port = 5000
        print(f"  Installationstyp: {env}  ({_TYPE_LABEL[env]})")
        if instance_name:
            print(f"  Instanz-Name:     {instance_name!r} "
                  f"(Praefix: dorfkern-{instance_name})")
        print(f"  Port-Base:        {base_port}  "
              f"(admin={base_port+4}, orga={base_port+3}, "
              f"kasse={base_port+2}, kiosk={base_port+1})")
        result = {'install_type': env,
                  'instance_name': instance_name,
                  'base_port': base_port}
        _validate_install_type(result, exit_on_error=True)
        return result

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
    print("       immer unter dem System-User 'dorfkern' (auch bei Multi-")
    print("       Instanz). Klassische PROD-Installation; setzt voraus, dass")
    print("       dieser Installer mit sudo gestartet wurde.")
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

    # Instanz-Name + Port-Base fragen (nur sinnvoll fuer Service-Modi,
    # aber auch fuer Ad-hoc gibt's keinen Schaden, falls jemand mehrere
    # parallele Klone laufen lassen will).
    print()
    print("  Optional: Instanz-Name + Port-Base.")
    print("  Mehrere Dorfkern-Installationen koennen parallel auf einem Host")
    print("  laufen, indem sie unterschiedliche Namen + Ports bekommen.")
    print("  Leer lassen = Default ('dorfkern'-Praefix, Ports 5001-5004).")
    print()
    instance_name = _ask("Instanz-Name (z.B. 'prod' oder 'dev', leer = Default)", "")
    instance_name = instance_name.strip().lower()
    if instance_name and not instance_name.replace('-', '').replace('_', '').isalnum():
        print(f"  ✗ Ungueltiger Instanz-Name: {instance_name!r} "
              "(nur Buchstaben/Zahlen/-_).")
        sys.exit(1)

    base_port_str = _ask("Port-Base (admin = +4, kiosk = +1)", "5000")
    try:
        base_port = int(base_port_str)
    except ValueError:
        print(f"  ✗ Port-Base muss eine Zahl sein: {base_port_str!r}")
        sys.exit(1)
    if not (1024 <= base_port <= 65500):
        print(f"  ✗ Port-Base ausserhalb 1024..65500: {base_port}")
        sys.exit(1)

    print(f"  ✓ Praefix: {('dorfkern-' + instance_name) if instance_name else 'dorfkern'}, "
          f"Ports {base_port+1}..{base_port+4}")

    result = {'install_type': install_type,
              'instance_name': instance_name,
              'base_port': base_port}
    _validate_install_type(result, exit_on_error=True)
    return result


def _opt_dorfkern_target(instance_name: str) -> str:
    """Erwarteter Install-Root fuer System-Mode bei gegebener Instanz."""
    prefix = f'dorfkern-{instance_name}' if instance_name else 'dorfkern'
    return f'/opt/{prefix}'


def _validate_install_type(cfg: dict, *, exit_on_error: bool) -> bool:
    """Prueft Voraussetzungen fuer den gewaehlten Typ.

    Args:
        cfg: Dict aus phase0_install_type() — install_type, instance_name,
            base_port.
    """
    install_type  = cfg['install_type']
    instance_name = cfg['instance_name']

    if install_type == 'service_system':
        if os.geteuid() != 0:
            print()
            print("  ✗ 'Dienst systemweit' setzt root voraus.")
            print("    Bitte neu starten:  sudo ./install.sh")
            if exit_on_error:
                sys.exit(1)
            return False
        # Repo sollte unter /opt/dorfkern[-<instance>] liegen. Wenn nicht:
        # anbieten zu verschieben (shutil.move = rename auf gleichem
        # Filesystem, sonst copy+remove).
        target = _opt_dorfkern_target(instance_name)
        if _REPO_ROOT != target:
            print()
            print(f"  Das Repo liegt unter {_REPO_ROOT!r}, nicht unter "
                  f"{target!r}.")
            print(f"  Fuer die System-Installation (Instanz "
                  f"{instance_name!r}) ist {target} der erwartete Pfad.")
            print()
            if _ask_yes_no(f"Repo nach {target} verschieben?", True):
                _move_to_opt_dorfkern_and_exit(target)
                # Kommt nie hierher zurueck — exit oben.
            print()
            print(f"  ⚠  Weiter mit {_REPO_ROOT}. Units zeigen auf diesen Pfad;")
            print("     wenn du das Repo spaeter doch verschieben willst, einmal")
            print("     'sudo ./install.sh' aus dem neuen Pfad nachholen.")
            if not _ask_yes_no("Mit aktuellem Pfad fortfahren?", True):
                if exit_on_error:
                    sys.exit(1)
                return False
    return True


def _move_to_opt_dorfkern_and_exit(target: str) -> None:
    """Verschiebt _REPO_ROOT nach ``target`` und exit-0 mit Re-Start-Hinweis.

    Strategie:
      - /opt/dorfkern darf nicht existieren oder muss leer sein (sonst Abbruch
        ohne Datenverlust).
      - shutil.move ist atomar auf demselben Filesystem, sonst macht es
        intern copy+remove.
      - Im Ziel das .venv wegwerfen — die alten Shebangs zeigen auf den
        Quellpfad und waeren nach dem Move kaputt; install.sh erstellt es
        beim Neustart sauber neu.
      - Cwd vor dem Move auf / wechseln, sonst hat der Python-Prozess ein
        toten Working Directory ueber.
      - Nicht selbst re-execen: der User soll klar sehen, was passiert,
        und einen frischen Befehl von der neuen Stelle aus tippen.
    """
    import shutil

    if os.path.exists(target):
        try:
            content = os.listdir(target)
        except OSError as exc:
            print(f"  ✗ Kann {target} nicht lesen: {exc}")
            sys.exit(1)
        if content:
            print(f"  ✗ {target} existiert und ist nicht leer:")
            for item in content[:10]:
                print(f"      {item}")
            print("  Bitte manuell aufraeumen (oder anderes Ziel waehlen),")
            print("  dann diesen Installer erneut starten.")
            sys.exit(1)
        try:
            os.rmdir(target)
        except OSError as exc:
            print(f"  ✗ Leeres {target} nicht entfernbar: {exc}")
            sys.exit(1)

    print()
    print(f"  → Verschiebe {_REPO_ROOT} → {target} …")
    os.chdir('/')  # alten cwd freigeben, sonst stirbt er beim mv
    try:
        shutil.move(_REPO_ROOT, target)
    except OSError as exc:
        print(f"  ✗ Move fehlgeschlagen: {exc}")
        sys.exit(1)
    print(f"  ✓ verschoben")

    # Altes venv (mit kaputten Shebangs) wegwerfen
    altes_venv = os.path.join(target, '.venv')
    if os.path.isdir(altes_venv):
        shutil.rmtree(altes_venv, ignore_errors=True)
        print(f"  ✓ {altes_venv} entfernt (wird beim Neustart neu angelegt)")

    print()
    print("  ──────────────────────────────────────────────")
    print(f"  Installer beendet — Repo ist jetzt unter {target}.")
    print("  Bitte neu starten:")
    print()
    print(f"      sudo {target}/install.sh")
    print("  ──────────────────────────────────────────────")
    print()
    sys.exit(0)


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
                              type_cfg: dict) -> bool:
    """Phase 4: Apps tatsaechlich starten (oder als Dienste installieren).

    Args:
        type_cfg: Dict aus phase0_install_type() — install_type,
            instance_name, base_port.
    Returns True, wenn alle Apps (vermutlich) laufen.
    """
    install_type  = type_cfg['install_type']
    instance_name = type_cfg['instance_name']
    base_port     = type_cfg['base_port']

    _section(f"Phase 4: {_TYPE_LABEL[install_type]} einrichten + starten")
    print()

    if install_type == 'ad_hoc':
        # base_port + instance wirken bereits ueber caoxt.ini-Reload bei
        # naechstem app_manager-Import — fuer die laufende Session sind
        # die Werte schon in APPS gesetzt (aus dem Reimport unten).
        _reload_app_manager()
        from installer.app_manager import start_all as _start_all
        results = _start_all(selected_apps)
        return all(results.get(a, False) for a in selected_apps)

    if install_type == 'service_user':
        ok = host_setup.install_user(
            install_root=_REPO_ROOT,
            instance_name=instance_name,
            base_port=base_port,
            selected_apps=selected_apps,
            enable_lingering=True,
            start_after_enable=True,
        )
        systemd_manager.invalidate_cache()
        return ok

    if install_type == 'service_system':
        ok = host_setup.install_system(
            install_root=_REPO_ROOT,
            instance_name=instance_name,
            base_port=base_port,
            selected_apps=selected_apps,
            start_after_enable=True,
        )
        systemd_manager.invalidate_cache()
        return ok

    print(f"  ✗ Unbekannter Installationstyp: {install_type!r}")
    return False


def _reload_app_manager() -> None:
    """Erzwingt einen Reimport von installer.app_manager.

    Wird in Phase 4 vor dem Ad-hoc-Start gerufen: die caoxt.ini wurde
    soeben mit neuen instance_name/base_port-Werten beschrieben, der
    erste Import von app_manager hatte aber noch die alten Werte
    gelesen. Reload sorgt dafuer, dass APPS-Ports + PID_FILE-Pfad
    stimmen.
    """
    import importlib
    import installer.app_manager as _am
    importlib.reload(_am)


# ─── Phase 5: Kiosk-Terminal (optional, nur service_system) ───────────

def phase5_kiosk_setup(type_cfg: dict, non_interactive: bool = False) -> None:
    """Phase 5: Box als Kiosk-Terminal konfigurieren (LightDM-Autologin
    in Vollbild-Chromium auf die Kiosk-App).

    Sinnvoll nur bei ``service_system`` (sonst hat 'dorfkern' keine
    Login-Faehigkeit). Bei service_user/ad_hoc wird die Phase still
    uebersprungen.

    Im non-interactive Modus aktiviert ``XT_KIOSK=1`` das Setup.
    """
    if type_cfg['install_type'] != 'service_system':
        return  # bei User/Ad-hoc-Mode macht das keinen Sinn

    _section("Phase 5: Kiosk-Terminal (optional)")

    schon_da = host_setup.is_kiosk_installed()
    if schon_da:
        print("  ✓  Kiosk-Setup bereits konfiguriert "
              f"({host_setup._KIOSK_LIGHTDM_CONF}).")
        if non_interactive:
            return
        if not _ask_yes_no("Neu generieren (z.B. nach Port-/App-Aenderung)?", False):
            return
    else:
        if non_interactive:
            flag = os.environ.get('XT_KIOSK', '').strip().lower()
            if flag not in ('1', 'true', 'yes', 'ja'):
                print("  ↷  Uebersprungen (XT_KIOSK nicht gesetzt).")
                return
        else:
            kiosk_port = type_cfg['base_port'] + 1
            print("  Soll diese Box als Kiosk-Terminal booten?")
            print(f"  Bei freier Box: 5-Sek-Autologin-Countdown im LightDM →")
            print(f"  Chromium-Vollbild auf http://localhost:{kiosk_port}. Wer")
            print(f"  in den 5 Sek eine Taste/Klick macht, kommt in den regulaeren")
            print(f"  Login-Bildschirm fuer Wartung.")
            print()
            print("  Setup ist ADDITIV — bestehende Admin-Konfiguration wird")
            print("  respektiert:")
            print("    - LightDM-Autologin nur, wenn nicht bereits ein anderer")
            print("      User dort konfiguriert ist")
            print("    - chsh dorfkern nur, wenn er noch nologin-Shell hat")
            print("    - systemctl enable lightdm nur, wenn kein anderer DM aktiv")
            print()
            print("  Immer ausgefuehrt:")
            print("    - apt install lightdm/xorg/chromium/openbox")
            print("    - dorfkern-kiosk-Session als Wahl im Login-Greeter")
            print()
            if not _ask_yes_no("Kiosk-Setup einrichten?", False):
                return

    # kiosk_user kommt aus XT_KIOSK_USER (env) bzw. SUDO_USER bzw.
    # erstem regulaeren UID-1000+-User; install_kiosk macht die
    # Heuristik selbst, wir reichen nur durch falls Env-Var gesetzt.
    ok = host_setup.install_kiosk(
        base_port=type_cfg['base_port'],
        app='kiosk',
        kiosk_user=os.environ.get('XT_KIOSK_USER', ''),
    )
    if not ok:
        print("  ✗ Kiosk-Setup fehlgeschlagen — siehe Meldungen oben.")


# ─── Phase 6: Abschlussbericht ────────────────────────────────────────

def phase6_report(selected_apps: list[str], type_cfg: dict, ok: bool) -> None:
    """Phase 6: Status + Adressen + Logs ausgeben."""
    install_type  = type_cfg['install_type']
    instance_name = type_cfg['instance_name']
    base_port     = type_cfg['base_port']
    prefix = f'dorfkern-{instance_name}' if instance_name else 'dorfkern'

    _section("Abschlussbericht")
    print_status()

    if ok:
        print("  ✓ Installation abgeschlossen")
    else:
        print("  ⚠  Installation mit Problemen — siehe Logs.")

    print()
    inst_hint = f" (Instanz {instance_name!r})" if instance_name else ''
    print(f"  Modus: {_TYPE_LABEL[install_type]}{inst_hint}")
    print(f"  Ports: admin={base_port+4} orga={base_port+3} "
          f"kasse={base_port+2} kiosk={base_port+1}")
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
            print(f"    {app:<14}  journalctl{flag} -u {prefix}-{app}")

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
        type_cfg = phase0_install_type(True)
        host, port, name, user, password = phase1_db_config(True)
        # KEINE DB-Init (das ist Sache des Admin-Hosts).
        selected_apps = phase3b_terminal_apps(args.terminal_typ)
        _section("Konfiguration speichern")
        write_ini(
            _INI_PATH,
            host=host, port=port, name=name,
            user=user, password=password,
            active_apps=selected_apps,
            instance_name=type_cfg['instance_name'],
            base_port=type_cfg['base_port'],
        )
        print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")
        ok = phase4_install_and_start(selected_apps, type_cfg)
        phase5_kiosk_setup(type_cfg, non_interactive=True)
        phase6_report(selected_apps, type_cfg, ok)
        return

    # ── Admin-Rolle (Vollinstallation, Default) ──────────────
    type_cfg = phase0_install_type(args.non_interactive)
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
        instance_name=type_cfg['instance_name'],
        base_port=type_cfg['base_port'],
    )
    print(f"  ✓ caoxt.ini gespeichert: {_INI_PATH}")

    ok = phase4_install_and_start(selected_apps, type_cfg)
    phase5_kiosk_setup(type_cfg, non_interactive=args.non_interactive)
    phase6_report(selected_apps, type_cfg, ok)


if __name__ == '__main__':
    main()
