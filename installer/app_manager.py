"""
CAO-XT App Manager – Start/Stop/Restart/Status für alle vier Apps.

Verwaltet die vier Flask-Apps:
  verwaltung  → Port 5004
  wawi        → Port 5003
  kasse       → Port 5002
  kiosk       → Port 5001

PIDs werden in /tmp/caoxt-pids.json persistiert.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time

# Repo-Root aus diesem Dateiverzeichnis ableiten
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))

PID_FILE = '/tmp/caoxt-pids.json'
LOG_DIR  = '/tmp'

APPS = {
    'verwaltung': {
        'port': 5004,
        'app_dir': os.path.join(_REPO_ROOT, 'verwaltung-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-verwaltung.log'),
    },
    'wawi': {
        'port': 5003,
        'app_dir': os.path.join(_REPO_ROOT, 'wawi-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-wawi.log'),
    },
    'kasse': {
        'port': 5002,
        'app_dir': os.path.join(_REPO_ROOT, 'kasse-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-kasse.log'),
    },
    'kiosk': {
        'port': 5001,
        'app_dir': os.path.join(_REPO_ROOT, 'kiosk-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-kiosk.log'),
    },
}

# Start-Reihenfolge: Verwaltung zuerst (Stammdaten-Basis), Kiosk zuletzt
START_ORDER = ['verwaltung', 'wawi', 'kasse', 'kiosk']


def _load_pids() -> dict:
    """Lädt PID-Datei; gibt leeres Dict zurück wenn nicht vorhanden."""
    try:
        with open(PID_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_pids(pids: dict) -> None:
    """Speichert PID-Dict in Datei."""
    with open(PID_FILE, 'w') as f:
        json.dump(pids, f, indent=2)


def _is_port_listening(port: int, timeout: float = 0.5) -> bool:
    """Prüft ob ein TCP-Port belegt ist."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(('127.0.0.1', port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _kill_port(port: int, timeout: int = 10) -> None:
    """Beendet alle Prozesse die auf dem gegebenen Port lauschen."""
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}', '-sTCP:LISTEN'],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
    except FileNotFoundError:
        # lsof nicht verfügbar → Fallback über /proc (Linux)
        pids = []

    for pid_str in pids:
        try:
            os.kill(int(pid_str), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass

    # Warten bis Port frei
    for _ in range(timeout):
        if not _is_port_listening(port):
            break
        time.sleep(1)


def _pid_alive(pid: int) -> bool:
    """Prüft ob ein Prozess noch läuft."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start_app(name: str, *, print_fn=print) -> bool:
    """Startet eine einzelne App. Gibt True bei Erfolg zurück."""
    cfg = APPS[name]
    port = cfg['port']
    app_dir = cfg['app_dir']
    log_path = cfg['log']

    if not os.path.isdir(app_dir):
        print_fn(f"  ✗  {name}: App-Verzeichnis nicht gefunden: {app_dir}")
        return False

    # Alten Prozess auf diesem Port beenden
    if _is_port_listening(port):
        print_fn(f"  ⟳  {name}: Port {port} belegt – beende alten Prozess …")
        _kill_port(port)

    # App starten
    log_file = open(log_path, 'a')
    try:
        proc = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=app_dir,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    except Exception as e:
        print_fn(f"  ✗  {name}: Start fehlgeschlagen: {e}")
        log_file.close()
        return False
    finally:
        log_file.close()

    # Warten bis Port erreichbar (max. 45 s – Kasse braucht DB-Pool-Init)
    for _ in range(45):
        time.sleep(1)
        if _is_port_listening(port):
            pids = _load_pids()
            pids[name] = proc.pid
            _save_pids(pids)
            print_fn(f"  ✓  {name} gestartet (PID {proc.pid}, Port {port})")
            return True
        if proc.poll() is not None:
            print_fn(f"  ✗  {name}: Prozess abgestürzt – Log: {log_path}")
            return False

    # Letzter Check nach Timeout
    if _is_port_listening(port):
        pids = _load_pids()
        pids[name] = proc.pid
        _save_pids(pids)
        print_fn(f"  ✓  {name} gestartet (PID {proc.pid}, Port {port})")
        return True

    print_fn(f"  ✗  {name}: Timeout – Port {port} nicht erreichbar. Log: {log_path}")
    return False


def stop_app(name: str, *, print_fn=print) -> None:
    """Stoppt eine einzelne App."""
    cfg = APPS[name]
    port = cfg['port']
    pids = _load_pids()

    pid = pids.get(name)
    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            print_fn(f"  ✓  {name} gestoppt (PID {pid})")
        except ProcessLookupError:
            pass
        del pids[name]
        _save_pids(pids)
    elif _is_port_listening(port):
        # Kein bekannter PID, aber Port ist belegt
        _kill_port(port)
        print_fn(f"  ✓  {name}: Port {port} freigegeben")
    else:
        print_fn(f"  –  {name}: nicht gestartet")


def restart_app(name: str, *, print_fn=print) -> bool:
    """Stoppt und startet eine App neu."""
    stop_app(name, print_fn=print_fn)
    time.sleep(1)
    return start_app(name, print_fn=print_fn)


def status_app(name: str) -> dict:
    """Gibt Status-Dict für eine App zurück."""
    cfg = APPS[name]
    port = cfg['port']
    pids = _load_pids()
    pid = pids.get(name)
    listening = _is_port_listening(port)
    alive = _pid_alive(pid) if pid else False
    return {
        'name': name,
        'port': port,
        'running': listening,
        'pid': pid if alive else None,
        'log': cfg['log'],
    }


def start_all(apps: list[str] | None = None, *, print_fn=print) -> dict[str, bool]:
    """Startet alle (oder eine Auswahl von) Apps in der festgelegten Reihenfolge."""
    targets = apps if apps else START_ORDER
    results = {}
    for name in targets:
        if name in APPS:
            results[name] = start_app(name, print_fn=print_fn)
    return results


def stop_all(apps: list[str] | None = None, *, print_fn=print) -> None:
    """Stoppt alle Apps in umgekehrter Reihenfolge (für sauberes Rollback)."""
    targets = list(reversed(apps if apps else START_ORDER))
    for name in targets:
        if name in APPS:
            stop_app(name, print_fn=print_fn)


def status_all() -> list[dict]:
    """Gibt Status aller Apps zurück."""
    return [status_app(name) for name in START_ORDER]


def print_status(*, print_fn=print) -> None:
    """Gibt formatierten Status aller Apps aus."""
    print_fn("")
    print_fn("  App          Port   Status")
    print_fn("  " + "─" * 40)
    for info in status_all():
        icon = "✓" if info['running'] else "✗"
        pid_str = f"  (PID {info['pid']})" if info['pid'] else ""
        print_fn(f"  {icon}  {info['name']:<12} {info['port']}   "
                 f"{'läuft' if info['running'] else 'gestoppt'}{pid_str}")
    print_fn("")
