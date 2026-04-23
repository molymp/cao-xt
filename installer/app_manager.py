"""
CAO-XT App Manager – Start/Stop/Restart/Status für alle Apps und Daemons.

Flask-Apps (type='web', Port-basiert):
  admin  → Port 5004
  orga        → Port 5003
  kasse       → Port 5002
  kiosk       → Port 5001

Daemons (type='daemon', PID-basiert, kein Port):
  haccp-poller  → zieht zyklisch TFA-Messwerte, schreibt Heartbeat

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

# Venv-Python: Flask und alle App-Abhängigkeiten sind dort installiert.
# Fallback auf sys.executable wenn kein venv vorhanden (z.B. CI).
_VENV_PYTHON = os.path.join(_REPO_ROOT, '.venv', 'bin', 'python3')
_APP_PYTHON  = _VENV_PYTHON if os.path.isfile(_VENV_PYTHON) else sys.executable

PID_FILE = '/tmp/caoxt-pids.json'
LOG_DIR  = '/tmp'

APPS = {
    'admin': {
        'type': 'web',
        'port': 5004,
        'app_dir': os.path.join(_REPO_ROOT, 'admin-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-admin.log'),
    },
    'orga': {
        'type': 'web',
        'port': 5003,
        'app_dir': os.path.join(_REPO_ROOT, 'orga-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-orga.log'),
    },
    'kasse': {
        'type': 'web',
        'port': 5002,
        'app_dir': os.path.join(_REPO_ROOT, 'kasse-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-kasse.log'),
    },
    'kiosk': {
        'type': 'web',
        'port': 5001,
        'app_dir': os.path.join(_REPO_ROOT, 'kiosk-app', 'app'),
        'log': os.path.join(LOG_DIR, 'caoxt-kiosk.log'),
    },
    'haccp-poller': {
        'type': 'daemon',
        'module': 'modules.haccp.poller',
        'cwd': _REPO_ROOT,
        'log': os.path.join(LOG_DIR, 'caoxt-haccp-poller.log'),
    },
}

# Start-Reihenfolge: Admin zuerst (Stammdaten-Basis), danach Orga
# (legt HACCP-Tabellen an), dann Poller, dann Kasse, Kiosk zuletzt.
START_ORDER = ['admin', 'orga', 'haccp-poller', 'kasse', 'kiosk']

# Legacy-Aliase: `app_manager verwaltung start` / `app_manager wawi start`
# werden auf die neuen Namen gemappt. Soll in Dorfkern v2.1 entfernt werden.
_LEGACY_ALIASES = {
    'verwaltung': 'admin',
    'wawi':       'orga',
}


def _resolve(name: str) -> str:
    return _LEGACY_ALIASES.get(name, name)


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
    """Startet eine einzelne App/Daemon. Gibt True bei Erfolg zurück.
    Dispatch nach ``type``: 'web' wartet auf Port, 'daemon' prueft Lebenszeichen."""
    name = _resolve(name)
    cfg = APPS[name]
    if cfg.get('type', 'web') == 'daemon':
        return _start_daemon(name, cfg, print_fn=print_fn)
    return _start_web_app(name, cfg, print_fn=print_fn)


def _start_web_app(name: str, cfg: dict, *, print_fn=print) -> bool:
    """Startet eine Flask-App (port-basiert)."""
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
            [_APP_PYTHON, 'app.py'],
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


def _start_daemon(name: str, cfg: dict, *, print_fn=print) -> bool:
    """Startet einen port-losen Hintergrund-Daemon via ``python -m <module>``.

    Health-Check: kurz warten und pruefen, dass der Prozess nicht sofort
    abgestuerzt ist. Fuer echten Gesundheitscheck dient die Logdatei bzw.
    der app-eigene Heartbeat (z.B. ``XT_HACCP_POLLER_STATUS`` beim Poller).
    """
    module = cfg['module']
    cwd    = cfg.get('cwd', _REPO_ROOT)
    log_path = cfg['log']

    # Alten Prozess ueber PID-Datei stoppen (kein Port zum Checken)
    pids = _load_pids()
    alt_pid = pids.get(name)
    if alt_pid and _pid_alive(alt_pid):
        print_fn(f"  ⟳  {name}: alter Prozess (PID {alt_pid}) läuft noch – beende …")
        try:
            os.kill(alt_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Kurz warten, dann falls noetig KILL
        for _ in range(10):
            if not _pid_alive(alt_pid):
                break
            time.sleep(1)

    log_file = open(log_path, 'a')
    try:
        proc = subprocess.Popen(
            [_APP_PYTHON, '-m', module],
            cwd=cwd,
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

    # 3 Sekunden beobachten, dann ist der DB-Pool + TFA-Ping durch.
    for _ in range(3):
        time.sleep(1)
        if proc.poll() is not None:
            print_fn(f"  ✗  {name}: Prozess abgestürzt (Exit {proc.returncode}) – Log: {log_path}")
            return False

    pids = _load_pids()
    pids[name] = proc.pid
    _save_pids(pids)
    print_fn(f"  ✓  {name} gestartet (PID {proc.pid}, Daemon)")
    return True


def stop_app(name: str, *, print_fn=print) -> None:
    """Stoppt eine einzelne App/Daemon."""
    name = _resolve(name)
    cfg = APPS[name]
    pids = _load_pids()
    pid = pids.get(name)
    is_daemon = cfg.get('type', 'web') == 'daemon'

    if pid and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            print_fn(f"  ✓  {name} gestoppt (PID {pid})")
        except ProcessLookupError:
            pass
        del pids[name]
        _save_pids(pids)
    elif not is_daemon and _is_port_listening(cfg['port']):
        # Kein bekannter PID, aber Port ist belegt (nur Web-Apps)
        _kill_port(cfg['port'])
        print_fn(f"  ✓  {name}: Port {cfg['port']} freigegeben")
    else:
        print_fn(f"  –  {name}: nicht gestartet")


def restart_app(name: str, *, print_fn=print) -> bool:
    """Stoppt und startet eine App neu."""
    stop_app(name, print_fn=print_fn)
    time.sleep(1)
    return start_app(name, print_fn=print_fn)


def status_app(name: str) -> dict:
    """Gibt Status-Dict für eine App/Daemon zurück.
    Web-Apps gelten als 'running', wenn der Port lauscht; Daemons, wenn
    der PID noch lebt."""
    name = _resolve(name)
    cfg = APPS[name]
    is_daemon = cfg.get('type', 'web') == 'daemon'
    pids = _load_pids()
    pid = pids.get(name)
    alive = _pid_alive(pid) if pid else False
    if is_daemon:
        running = alive
        port = None
    else:
        port = cfg['port']
        running = _is_port_listening(port)
    return {
        'name': name,
        'type': cfg.get('type', 'web'),
        'port': port,
        'running': running,
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
    """Gibt formatierten Status aller Apps/Daemons aus."""
    print_fn("")
    print_fn("  App            Port     Status")
    print_fn("  " + "─" * 45)
    for info in status_all():
        icon = "✓" if info['running'] else "✗"
        pid_str = f"  (PID {info['pid']})" if info['pid'] else ""
        port_str = str(info['port']) if info['port'] else "daemon"
        print_fn(f"  {icon}  {info['name']:<14} {port_str:<8} "
                 f"{'läuft' if info['running'] else 'gestoppt'}{pid_str}")
    print_fn("")
