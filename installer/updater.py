#!/usr/bin/env python3
"""
CAO-XT Update-Mechanismus

Prüft auf neue Versionen via Git und führt Updates durch.

Verwendung:
    python3 -m installer.updater --check     # Nur prüfen
    python3 -m installer.updater --update    # Update durchführen
    python3 -m installer.updater             # Interaktiv

Referenz: HAB-356
"""
import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_VERSION_FILE = os.path.join(_REPO_ROOT, 'VERSION.json')
_LOG_FILE = os.path.join(os.sep, 'tmp', 'caoxt-update.log')

# ── Farben ────────────────────────────────────────────────────
RED    = '\033[0;31m'
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE   = '\033[0;34m'
NC     = '\033[0m'


def ok(msg: str)   -> None: print(f"  {GREEN}✓{NC}  {msg}")
def warn(msg: str) -> None: print(f"  {YELLOW}⚠{NC}  {msg}")
def fail(msg: str) -> None: print(f"  {RED}✗{NC}  {msg}")
def info(msg: str) -> None: print(f"  {BLUE}→{NC}  {msg}")


def _log(msg: str) -> None:
    """Schreibt in Logdatei und stdout."""
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def _run(cmd: list[str], cwd: str = _REPO_ROOT, check: bool = True,
         capture: bool = False) -> subprocess.CompletedProcess:
    """Führt einen Befehl aus."""
    if capture:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=120)
    return subprocess.run(cmd, cwd=cwd, check=check, timeout=120)


def _git(*args) -> subprocess.CompletedProcess:
    return _run(['git'] + list(args), capture=True)


def load_local_version() -> Optional[dict]:
    """Liest lokale VERSION.json."""
    try:
        with open(_VERSION_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_remote_version(branch: str = 'master') -> Optional[dict]:
    """Liest VERSION.json aus dem Remote-Branch (nach git fetch)."""
    r = _git('show', f'origin/{branch}:VERSION.json')
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _semver_tuple(v: str) -> tuple[int, ...]:
    """Wandelt 'MAJOR.MINOR.PATCH' in ein vergleichbares Tupel."""
    try:
        return tuple(int(x) for x in v.split('.'))
    except ValueError:
        return (0, 0, 0)


def _current_branch() -> str:
    """Gibt den aktuellen Git-Branch zurück (Fallback: 'master')."""
    r = _git('rev-parse', '--abbrev-ref', 'HEAD')
    b = r.stdout.strip() if r.returncode == 0 else ''
    return b if b and b != 'HEAD' else 'master'


def check_for_updates(branch: str = '') -> dict:
    """
    Prüft, ob ein Update verfügbar ist.

    Returns:
        dict mit Schlüsseln:
            - available (bool)
            - local_version (str)
            - remote_version (str)
            - commits (list[str])   – neue Commits
            - impact (dict)         – Impact-Flags der Remote-Version
            - error (str|None)
    """
    result = {
        'available': False,
        'local_version': 'unbekannt',
        'remote_version': 'unbekannt',
        'commits': [],
        'impact': {},
        'error': None,
    }

    # Aktuellen Branch ermitteln wenn nicht explizit angegeben
    if not branch:
        branch = _current_branch()

    # Lokale Version
    local = load_local_version()
    if local:
        result['local_version'] = local.get('version', 'unbekannt')

    # Git-Fetch (nur wenn online)
    fetch = _git('fetch', 'origin', branch)
    if fetch.returncode != 0:
        result['error'] = f"git fetch fehlgeschlagen: {fetch.stderr.strip()}"
        return result

    # Remote-Version
    remote = load_remote_version(branch)
    if not remote:
        result['error'] = "VERSION.json auf Remote nicht lesbar"
        return result
    result['remote_version'] = remote.get('version', 'unbekannt')
    result['impact'] = remote.get('impact', {})

    # Versionsvergleich
    local_v  = _semver_tuple(result['local_version'])
    remote_v = _semver_tuple(result['remote_version'])
    result['available'] = remote_v > local_v

    # Neue Commits auflisten
    if result['available']:
        log_r = _git('log', '--oneline', f'HEAD..origin/{branch}')
        if log_r.returncode == 0:
            result['commits'] = [l for l in log_r.stdout.splitlines() if l.strip()]

    return result


def perform_update(branch: str = 'master') -> bool:
    """
    Führt ein Update durch.

    Ablauf:
      1. Apps stoppen
      2. git pull
      3. pip install (wenn requirements_changed)
      4. DB-Migrationen (wenn db_migration_required)
      5. Apps starten
      6. Health-Check

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    _log("─── CAO-XT Update gestartet ───────────────────────────────")

    # Impact-Flags der Remote-Version holen
    remote = load_remote_version(branch)
    impact = remote.get('impact', {}) if remote else {}
    db_migration = impact.get('db_migration_required', False)
    req_changed  = impact.get('requirements_changed', False)

    # Head-Commit vor Update merken (für Rollback)
    head_before = _git('rev-parse', 'HEAD')
    rollback_ref = head_before.stdout.strip() if head_before.returncode == 0 else None

    _log("Schritt 1/6: Apps stoppen …")
    try:
        _run([sys.executable, '-m', 'installer.app_manager', 'stop_all'],
             check=False)
    except Exception as e:
        _log(f"  Warnung: Apps konnten nicht gestoppt werden: {e}")

    _log("Schritt 2/6: git pull …")
    pull = _run(['git', 'pull', 'origin', branch], cwd=_REPO_ROOT,
                capture=True)
    if pull.returncode != 0:
        _log(f"  FEHLER: git pull fehlgeschlagen\n{pull.stderr}")
        _rollback(rollback_ref)
        return False
    _log(f"  {pull.stdout.strip()}")

    _log("Schritt 3/6: Abhängigkeiten …")
    if req_changed:
        venv_pip = os.path.join(_REPO_ROOT, '.venv', 'bin', 'pip3')
        if not os.path.exists(venv_pip):
            venv_pip = 'pip3'
        req_result = _run([venv_pip, 'install', '-q', '-r',
                          os.path.join(_REPO_ROOT, 'installer', 'requirements.txt')],
                         capture=True)
        if req_result.returncode != 0:
            _log(f"  FEHLER: pip install fehlgeschlagen\n{req_result.stderr}")
            _rollback(rollback_ref)
            return False
        # App-Requirements
        for app_dir in ['kasse-app', 'kiosk-app', 'orga-app', 'admin-app']:
            req = os.path.join(_REPO_ROOT, app_dir, 'app', 'requirements.txt')
            if os.path.exists(req):
                _run([venv_pip, 'install', '-q', '-r', req], capture=True)
        _log("  Abhängigkeiten aktualisiert.")
    else:
        _log("  Keine neuen Abhängigkeiten (requirements_changed = false).")

    _log("Schritt 4/6: DB-Migrationen …")
    if db_migration:
        _log("  DB-Migration erforderlich – starte Migrationen …")
        try:
            _run([sys.executable, '-c',
                 'import sys; sys.path.insert(0, "."); '
                 'from installer.db_init import run_migrations; run_migrations()'],
                capture=True)
            _log("  DB-Migrationen abgeschlossen.")
        except Exception as e:
            _log(f"  FEHLER bei DB-Migration: {e}")
            _rollback(rollback_ref)
            return False
    else:
        _log("  Keine DB-Migrationen erforderlich.")

    _log("Schritt 5/6: Apps starten …")
    try:
        _run([sys.executable, '-m', 'installer.app_manager', 'start_all'],
             check=False)
    except Exception as e:
        _log(f"  Warnung: Apps konnten nicht gestartet werden: {e}")

    _log("Schritt 6/6: Health-Check …")
    time.sleep(5)
    ok_count = _health_check()
    _log(f"  {ok_count} Apps antworten.")

    # Neue Version lesen
    new_local = load_local_version()
    new_v = new_local.get('version', '?') if new_local else '?'

    _log("")
    _log(f"Update abgeschlossen. Installierte Version: {new_v}")
    _log("─────────────────────────────────────────────────────────────")
    return True


def _rollback(ref: Optional[str]) -> None:
    """Rollt auf den angegebenen Commit zurück."""
    if not ref:
        _log("  Rollback: kein Referenz-Commit bekannt – übersprungen.")
        return
    _log(f"  Rollback auf {ref[:8]} …")
    _run(['git', 'reset', '--hard', ref], cwd=_REPO_ROOT, capture=True)
    _log("  Rollback abgeschlossen. Apps neu starten …")
    try:
        _run([sys.executable, '-m', 'installer.app_manager', 'start_all'],
             check=False)
    except Exception:
        pass


def _health_check() -> int:
    """Prüft, ob die konfigurierten Apps erreichbar sind. Gibt Anzahl OK zurück."""
    import socket
    ports = [
        int(os.environ.get('ADMIN_PORT', '5004')),
        int(os.environ.get('KASSE_PORT', '5002')),
        int(os.environ.get('KIOSK_PORT', '5001')),
        int(os.environ.get('ORGA_PORT', '5003')),
    ]
    ok_count = 0
    for port in ports:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                ok_count += 1
        except OSError:
            pass
    return ok_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description='CAO-XT Update-Mechanismus',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  python3 -m installer.updater --check    # Nur prüfen\n"
            "  python3 -m installer.updater --update   # Direkt updaten\n"
        )
    )
    parser.add_argument('--check',  action='store_true', help='Nur auf Updates prüfen')
    parser.add_argument('--update', action='store_true', help='Update sofort durchführen')
    parser.add_argument('--branch', default='',   help='Remote-Branch (Standard: aktueller Branch)')
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     CAO-XT Update-Mechanismus                           ║")
    print("║     Habacher Dorfladen                                  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Immer zuerst prüfen
    info("Prüfe auf Updates …")
    status = check_for_updates(args.branch)

    if status.get('error'):
        warn(f"Update-Prüfung: {status['error']}")
        return 1

    local_v  = status['local_version']
    remote_v = status['remote_version']
    impact   = status['impact']

    if not status['available']:
        ok(f"System ist aktuell (Version {local_v})")
        return 0

    # Update vorhanden
    print()
    print(f"  Installierte Version : {local_v}")
    print(f"  Verfügbare Version   : {remote_v}")
    print()

    if impact.get('breaking_change'):
        warn("ACHTUNG: Breaking Change! Manuelle Überprüfung empfohlen.")
    if impact.get('db_migration_required'):
        warn("Datenbank-Migration erforderlich.")
    if impact.get('restart_required'):
        info("Neustart aller Apps erforderlich.")
    if impact.get('requirements_changed'):
        info("Neue Python-Abhängigkeiten werden installiert.")

    if status['commits']:
        print()
        print("  Neue Commits:")
        for c in status['commits'][:20]:
            print(f"    {c}")
        if len(status['commits']) > 20:
            print(f"    … und {len(status['commits']) - 20} weitere")

    # Nur prüfen?
    if args.check:
        return 0

    # Interaktiv fragen, wenn kein --update
    if not args.update:
        print()
        try:
            antwort = input("  Update jetzt durchführen? [j/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if antwort not in ('j', 'ja', 'y', 'yes'):
            info("Update abgebrochen.")
            return 0

    print()
    erfolg = perform_update(args.branch)
    return 0 if erfolg else 1


if __name__ == '__main__':
    sys.exit(main())
