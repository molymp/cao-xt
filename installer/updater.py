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
import fcntl
import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

_REPO_ROOT     = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_VERSION_FILE  = os.path.join(_REPO_ROOT, 'VERSION.json')
_DORFKERN_CTL  = os.path.join(_REPO_ROOT, 'dorfkern-ctl')


# Instanz-Konfig laden (instance_name + systemd_prefix), damit Lock-,
# Log- und Backup-Pfade pro Instanz separat sind. So koennen DEV- und
# PROD-Updates auf demselben Host parallel oder verschachtelt laufen,
# ohne sich gegenseitig den Lock oder das Backup wegzuziehen.
def _load_instance() -> tuple:
    try:
        from common.config import load_instance_config
        cfg = load_instance_config()
        return cfg['instance_name'], cfg['systemd_prefix']
    except Exception:
        return '', 'dorfkern'


_INSTANCE_NAME, _PREFIX = _load_instance()

# Update-Log: pro Instanz separat. Im System-Mode landet das in
# /var/log/<prefix>/update.log (persistent ueber Reboot), sonst /tmp.
try:
    from common.config import log_path as _log_path_for
    _LOG_FILE = _log_path_for('update', _INSTANCE_NAME)
except Exception:
    _LOG_FILE = os.path.join(os.sep, 'tmp', f'{_PREFIX}-update.log')

# Update-Lock: verhindert parallele Update-Laeufe DERSELBEN Instanz.
# Standardpfad /var/lock; bei fehlenden Rechten faellt _acquire_lock()
# auf /tmp zurueck.
_LOCK_FILE = f'/var/lock/{_PREFIX}-update.lock'

# DB-Dumps vor Migrationen. Per XT_BACKUP_DIR ueberschreibbar.
_BACKUP_DIR = os.environ.get('XT_BACKUP_DIR', f'/var/backups/{_PREFIX}')

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


def _run(cmd: list, cwd: str = _REPO_ROOT, check: bool = True,
         capture: bool = False, timeout: int = 120) -> subprocess.CompletedProcess:
    """Führt einen Befehl aus."""
    if capture:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    return subprocess.run(cmd, cwd=cwd, check=check, timeout=timeout)


def _git(*args) -> subprocess.CompletedProcess:
    return _run(['git'] + list(args), capture=True)


# ─── Versionsabfrage ──────────────────────────────────────────────────

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


def _semver_tuple(v: str) -> tuple:
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
    Prueft, ob ein Update verfuegbar ist – COMMIT-BASIERT.

    Wir vergleichen HEAD gegen origin/<branch>: gibt es Commits, die wir
    noch nicht haben, ist ein Update verfuegbar. Eine manuell zu pflegende
    VERSION.json ist NICHT erforderlich (frueher war sie fuer
    'available' zwingend, was den Mechanismus de facto stillgelegt hat,
    sobald jemand vergessen hatte zu bumpen).

    Returns:
        dict mit Schluesseln:
            - available (bool)
            - ahead_count (int)         – Anzahl Commits hinter dem Remote
            - local_commit (str)        – aktueller HEAD short-Hash
            - remote_commit (str)       – origin/<branch> short-Hash
            - local_version (str|None)  – aus VERSION.json, nur Anzeige
            - remote_version (str|None) – aus VERSION.json (origin), Anzeige
            - commits (list[str])       – Subject-Liste der neuen Commits
            - impact (dict)             – Flags, falls VERSION.json sie liefert
            - branch (str)
            - error (str|None)
    """
    result = {
        'available':      False,
        'ahead_count':    0,
        'local_commit':   '',
        'remote_commit':  '',
        'local_version':  None,
        'remote_version': None,
        'commits':        [],
        'impact':         {},
        'branch':         '',
        'error':          None,
    }

    if not branch:
        branch = _current_branch()
    result['branch'] = branch

    local = load_local_version()
    if local:
        result['local_version'] = local.get('version')

    head = _git('rev-parse', '--short', 'HEAD')
    if head.returncode == 0:
        result['local_commit'] = head.stdout.strip()

    fetch = _git('fetch', 'origin', branch)
    if fetch.returncode != 0:
        result['error'] = f"git fetch fehlgeschlagen: {fetch.stderr.strip()}"
        return result

    remote_head = _git('rev-parse', '--short', f'origin/{branch}')
    if remote_head.returncode == 0:
        result['remote_commit'] = remote_head.stdout.strip()

    remote = load_remote_version(branch)
    if remote:
        result['remote_version'] = remote.get('version')
        result['impact'] = remote.get('impact', {}) or {}

    rev_list = _git('rev-list', '--count', f'HEAD..origin/{branch}')
    if rev_list.returncode == 0:
        try:
            result['ahead_count'] = int(rev_list.stdout.strip() or '0')
        except ValueError:
            result['ahead_count'] = 0
    result['available'] = result['ahead_count'] > 0

    if result['available']:
        log_r = _git('log', '--pretty=format:%h %s', f'HEAD..origin/{branch}')
        if log_r.returncode == 0:
            result['commits'] = [l for l in log_r.stdout.splitlines() if l.strip()]

    return result


# ─── Lock, Working-Tree-Check, Bootstrap ──────────────────────────────

def _acquire_lock() -> Optional[object]:
    """Versucht eine exklusive Lock auf das Lockfile dieser Instanz.

    Liefert das offene File-Handle (Lock haelt bis zum close()) oder
    None, wenn ein anderer Updater laeuft. Faellt bei fehlenden
    Schreibrechten auf das Pendant in /tmp zurueck.
    """
    fallback_lock = f'/tmp/{_PREFIX}-update.lock'
    for path in (_LOCK_FILE, fallback_lock):
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        except PermissionError:
            continue
        except OSError as exc:
            _log(f"  Lockfile {path}: {exc}")
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Lock haengt bei jemand anders — Update laeuft schon
            os.close(fd)
            return None
        # PID hinterlegen, damit man bei Lock-Konflikt weiss, wer's hat
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        return os.fdopen(fd, 'r+')
    return None


def _release_lock(lock) -> None:
    """Schliesst Lock (gibt sie damit frei)."""
    if lock is not None:
        try:
            lock.close()
        except Exception:
            pass


def _working_tree_clean() -> Tuple[bool, list]:
    """True wenn keine modifizierten getrackten Dateien vorhanden sind.

    Untracked Files (??) und ignorierte (!!) sind OK — auf PROD landen
    da typischerweise nur Build-Artefakte und das venv. Modifizierte
    getrackte Dateien (M/A/D/R/U/...) brechen ab, weil git pull
    --ff-only daran scheitert und wir das vorher sauber melden wollen.
    """
    r = _git('status', '--porcelain')
    if r.returncode != 0:
        return False, ['git status fehlgeschlagen']
    dirty = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        # Erste zwei Zeichen sind XY-Status, dann Space, dann Pfad
        status = line[:2]
        if status not in ('??', '!!'):
            dirty.append(line)
    return (not dirty), dirty


def _ensure_caoxt_ini() -> None:
    """Stellt sicher, dass caoxt/caoxt.ini existiert. Falls die lokale
    Datei fehlt (frischer Klon, geloeschtes Backup), wird sie aus
    caoxt/caoxt.ini.example kopiert. Schadet nie etwas zu pruefen.
    """
    ini  = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')
    ex   = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini.example')
    if os.path.exists(ini):
        return
    if not os.path.exists(ex):
        _log("  Hinweis: weder caoxt.ini noch .example vorhanden – Konfig manuell anlegen.")
        return
    try:
        import shutil
        shutil.copy2(ex, ini)
        _log(f"  caoxt.ini aus Vorlage erzeugt: {ini}")
        _log("  WICHTIG: DB-Zugangsdaten in caoxt.ini eintragen.")
    except OSError as exc:
        _log(f"  Konnte caoxt.ini nicht erzeugen: {exc}")


# ─── DB-Dump / DB-Restore ─────────────────────────────────────────────

def _load_db_config() -> Optional[dict]:
    """Laedt DB-Config (host/port/name/user/password) aus caoxt.ini."""
    try:
        if _REPO_ROOT not in sys.path:
            sys.path.insert(0, _REPO_ROOT)
        from common.config import load_db_config
        return load_db_config()
    except Exception as exc:
        _log(f"  Konnte DB-Config nicht laden: {exc}")
        return None


def _dump_database() -> Optional[str]:
    """Erzeugt einen mysqldump.gz der konfigurierten DB.

    Liefert den Pfad zur Dump-Datei oder None bei Fehler.
    Passwort wird via MYSQL_PWD-Env reingereicht, nicht via -p (sonst
    landet es in der Prozessliste).
    """
    cfg = _load_db_config()
    if cfg is None:
        return None

    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
    except OSError as exc:
        _log(f"  Backup-Verzeichnis {_BACKUP_DIR} nicht anlegbar: {exc}")
        return None

    ts = time.strftime('%Y%m%d_%H%M%S')
    dump_path = os.path.join(_BACKUP_DIR, f'dorfkern_{ts}.sql.gz')

    env = os.environ.copy()
    env['MYSQL_PWD'] = cfg['password']

    try:
        with open(dump_path, 'wb') as out:
            dump = subprocess.Popen(
                ['mysqldump',
                 '-h', cfg['host'],
                 '-P', str(cfg['port']),
                 '-u', cfg['user'],
                 '--single-transaction',
                 '--quick',
                 '--routines',
                 '--triggers',
                 cfg['name']],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            gz = subprocess.Popen(
                ['gzip', '-9'],
                stdin=dump.stdout,
                stdout=out,
                stderr=subprocess.PIPE,
            )
            # Wichtig: dump.stdout in unserem Prozess schliessen, sonst
            # bekommt gzip kein EOF wenn mysqldump fertig ist.
            dump.stdout.close()
            _, gz_err = gz.communicate(timeout=1800)
            _, dump_err = dump.communicate(timeout=1800)
    except FileNotFoundError as exc:
        _log(f"  Tool fehlt fuer DB-Dump: {exc}")
        return None
    except subprocess.TimeoutExpired:
        _log("  DB-Dump-Timeout (>30 min). Abbruch.")
        return None
    except OSError as exc:
        _log(f"  Dump-Fehler: {exc}")
        return None

    if dump.returncode != 0:
        _log(f"  mysqldump fehlgeschlagen: "
             f"{dump_err.decode(errors='replace').strip()}")
        try:
            os.unlink(dump_path)
        except OSError:
            pass
        return None
    if gz.returncode != 0:
        _log(f"  gzip fehlgeschlagen: "
             f"{gz_err.decode(errors='replace').strip()}")
        try:
            os.unlink(dump_path)
        except OSError:
            pass
        return None

    size_mb = os.path.getsize(dump_path) / (1024 * 1024)
    _log(f"  Dump: {dump_path} ({size_mb:.1f} MB)")
    return dump_path


def _restore_database(dump_path: str) -> bool:
    """Spielt einen .sql.gz-Dump in die konfigurierte DB zurueck."""
    if not dump_path or not os.path.isfile(dump_path):
        _log(f"  Dump nicht gefunden: {dump_path}")
        return False

    cfg = _load_db_config()
    if cfg is None:
        return False

    env = os.environ.copy()
    env['MYSQL_PWD'] = cfg['password']

    try:
        gunzip = subprocess.Popen(['gunzip', '-c', dump_path],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        mysql = subprocess.Popen(
            ['mysql',
             '-h', cfg['host'],
             '-P', str(cfg['port']),
             '-u', cfg['user'],
             cfg['name']],
            stdin=gunzip.stdout,
            stderr=subprocess.PIPE,
            env=env,
        )
        gunzip.stdout.close()
        _, mysql_err = mysql.communicate(timeout=3600)
        _, gunzip_err = gunzip.communicate(timeout=60)
    except FileNotFoundError as exc:
        _log(f"  Tool fehlt fuer Restore: {exc}")
        return False
    except subprocess.TimeoutExpired:
        _log("  DB-Restore-Timeout (>60 min). Abbruch.")
        return False

    if gunzip.returncode != 0:
        _log(f"  gunzip: {gunzip_err.decode(errors='replace').strip()}")
        return False
    if mysql.returncode != 0:
        _log(f"  mysql-Restore: {mysql_err.decode(errors='replace').strip()}")
        return False

    _log(f"  DB-Restore aus {dump_path} erfolgreich.")
    return True


# ─── pip / Migration / systemd-Units / Health ─────────────────────────

def _pip_install_requirements() -> bool:
    """pip install im venv (Installer + jede App-requirements.txt)."""
    venv_pip = os.path.join(_REPO_ROOT, '.venv', 'bin', 'pip3')
    if not os.path.exists(venv_pip):
        venv_pip = 'pip3'
    req_result = _run([venv_pip, 'install', '-q', '-r',
                      os.path.join(_REPO_ROOT, 'installer', 'requirements.txt')],
                     capture=True, timeout=600)
    if req_result.returncode != 0:
        _log(f"  FEHLER: pip install fehlgeschlagen\n{req_result.stderr}")
        return False
    for app_dir in ['kasse-app', 'kiosk-app', 'orga-app', 'admin-app']:
        req = os.path.join(_REPO_ROOT, app_dir, 'app', 'requirements.txt')
        if os.path.exists(req):
            _run([venv_pip, 'install', '-q', '-r', req],
                 capture=True, timeout=600)
    return True


def _run_migrations() -> bool:
    """Migrationen ueber installer.db_init.run_migrations() laufen lassen."""
    try:
        r = _run([sys.executable, '-c',
                  'import sys; sys.path.insert(0, "."); '
                  'from installer.db_init import run_migrations; run_migrations()'],
                 capture=True, timeout=900)
    except Exception as exc:
        _log(f"  FEHLER bei DB-Migration: {exc}")
        return False
    if r.returncode != 0:
        _log(f"  FEHLER bei DB-Migration:\n{r.stderr}")
        return False
    return True


def _regenerate_systemd_units() -> None:
    """Regeneriert systemd-Units, wenn dorfkern.target installiert ist.

    Dispatcht auf den erkannten Mode (user oder system) und delegiert
    an die jeweiligen Helper in ``installer.systemd.host_setup``.
    Bei Misserfolg wird gewarnt; das Update laeuft weiter — die alten
    Units bleiben dann aktiv (kein blockendes Fehlerverhalten).
    """
    try:
        from installer.systemd.manager import systemd_mode, invalidate_cache
        from installer.systemd import host_setup
    except Exception:
        return

    mode = systemd_mode()
    if mode is None:
        return  # weder System- noch User-Target installiert

    _log(f"  systemd-Units regenerieren ({mode}-Mode) …")

    # Wir routen host_setup-Ausgaben in unser _log, damit alles im
    # caoxt-update.log landet.
    if mode == 'user':
        ok = host_setup.regenerate_user(_REPO_ROOT, print_fn=_log)
    else:  # 'system'
        ok = host_setup.regenerate_system(_REPO_ROOT, print_fn=_log)

    if ok:
        invalidate_cache()
        _log("  Units aktualisiert, daemon-reload OK.")
    else:
        _log("  WARNUNG: Units-Regeneration fehlgeschlagen — "
             "alte Units bleiben aktiv.")


def _http_health_check(timeout: int = 3) -> Tuple[int, int]:
    """HTTP-GET / auf jeder Web-App. Liefert (ok_count, total).

    Eine App gilt als "lebt", sobald irgendein HTTP-Status zurueckkommt
    — auch 30x/4xx/5xx. Connection-Refused oder Timeout = tot.
    """
    import urllib.error
    import urllib.request
    apps = [
        ('admin', int(os.environ.get('ADMIN_PORT', '5004'))),
        ('orga',  int(os.environ.get('ORGA_PORT',  '5003'))),
        ('kasse', int(os.environ.get('KASSE_PORT', '5002'))),
        ('kiosk', int(os.environ.get('KIOSK_PORT', '5001'))),
    ]
    ok_count = 0
    for name, port in apps:
        url = f'http://127.0.0.1:{port}/'
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=timeout):
                ok_count += 1
        except urllib.error.HTTPError:
            # 4xx/5xx = App antwortet, also lebt sie
            ok_count += 1
        except (urllib.error.URLError, OSError):
            _log(f"  {name} (Port {port}): keine Antwort")
    return ok_count, len(apps)


# ─── Update-Hauptablauf ───────────────────────────────────────────────

def perform_update(branch: str = '') -> bool:
    """
    Führt ein Update durch.

    Ablauf:
      0. Lock holen, Working Tree muss sauber sein
      1. Apps stoppen (via dorfkern-ctl → systemd, falls installiert)
      2. git pull --ff-only
      3. caoxt.ini bootstrappen
      4. pip install (wenn requirements_changed)
      5. systemd-Units regenerieren (falls dorfkern.target installiert)
      6. DB-Dump (wenn db_migration_required)
      7. DB-Migrationen
      8. Apps starten
      9. HTTP-Health-Check

    Rollback (bei Fehler vor Schritt 7): git reset --hard
    Rollback (bei Fehler in/nach Schritt 7): git reset + DB-Restore

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    if not branch:
        branch = _current_branch()
    _log("─── CAO-XT Update gestartet ───────────────────────────────")

    lock = _acquire_lock()
    if lock is None:
        _log(f"FEHLER: Ein anderer Update-Lauf hat den Lock. "
             f"Pruefen: {_LOCK_FILE} bzw. /tmp/{_PREFIX}-update.lock")
        return False

    try:
        clean, dirty = _working_tree_clean()
        if not clean:
            _log("FEHLER: Working Tree ist nicht sauber.")
            for line in dirty[:10]:
                _log(f"  {line}")
            if len(dirty) > 10:
                _log(f"  … und {len(dirty) - 10} weitere")
            _log("Bitte lokale Aenderungen committen, stashen oder "
                 "verwerfen, dann Update neu starten.")
            return False

        # Impact-Flags aus Remote-VERSION.json holen
        remote = load_remote_version(branch)
        impact = remote.get('impact', {}) if remote else {}
        db_migration_required = impact.get('db_migration_required', False)
        req_changed           = impact.get('requirements_changed', False)

        # Head vor dem Update merken (fuer Rollback)
        head_before = _git('rev-parse', 'HEAD')
        rollback_ref = (head_before.stdout.strip()
                        if head_before.returncode == 0 else None)
        dump_path = None  # wird gesetzt, sobald DB-Dump gemacht wurde

        # ── Schritt 1: Apps stoppen ─────────────────────────────
        _log("Schritt 1: Apps stoppen …")
        # Wir benutzen dorfkern-ctl, damit der systemd-Pfad (falls
        # installiert) automatisch genommen wird. Der frueher hier
        # benutzte 'python -m installer.app_manager stop_all' war ein
        # No-Op (Modul hat kein __main__) — Apps blieben in Wahrheit
        # die ganze Zeit ueber laufen.
        _run([_DORFKERN_CTL, 'stop'], check=False, timeout=120)

        # ── Schritt 2: git pull ─────────────────────────────────
        _log("Schritt 2: git pull --ff-only …")
        # Defensive: caoxt.ini soll Git lokal bitte komplett vergessen,
        # falls jemand auf einem alten Klon noch das frueher getrackte
        # File hat. Idempotent.
        _git('update-index', '--skip-worktree', 'caoxt/caoxt.ini')
        # Snapshot der caoxt.ini VOR dem Pull. Hintergrund: wenn die
        # Datei auf einem aelteren Klon noch im Index war und ein Pull
        # einen Commit reinbringt, der sie aus dem Tracking entfernt,
        # loescht git die Datei im Working Tree (sie war ja "im Index
        # alt, im Index neu nicht da"). Der nachfolgende
        # _ensure_caoxt_ini()-Restore zieht dann die Vorlage rein —
        # echte DB-Credentials sind weg. Der Snapshot wird nach dem
        # Pull verglichen und wenn die Datei verschwunden/identisch zur
        # Vorlage ist, restoren wir aus dem Snapshot.
        ini_path = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')
        ini_snapshot = None
        if os.path.isfile(ini_path):
            try:
                with open(ini_path, 'rb') as f:
                    ini_snapshot = f.read()
            except OSError as exc:
                _log(f"  Warnung: caoxt.ini-Snapshot fehlgeschlagen: {exc}")

        pull = _run(['git', 'pull', '--ff-only', 'origin', branch],
                    cwd=_REPO_ROOT, capture=True, timeout=120)
        if pull.returncode != 0:
            _log(f"  FEHLER: git pull fehlgeschlagen\n{pull.stderr}")
            _rollback(rollback_ref, dump_path=None)
            return False
        _log(f"  {pull.stdout.strip()}")

        # caoxt.ini-Snapshot pruefen: wenn der Pull die Datei
        # geloescht hat (klassisch: Untracking-Commit kam rein) ODER
        # sie nun byte-identisch zur Vorlage ist (heisst: irgendwas
        # hat sie mit example ersetzt), Snapshot zurueckspielen.
        if ini_snapshot is not None:
            example_path = os.path.join(_REPO_ROOT, 'caoxt',
                                          'caoxt.ini.example')
            example_bytes = b''
            if os.path.isfile(example_path):
                try:
                    with open(example_path, 'rb') as f:
                        example_bytes = f.read()
                except OSError:
                    pass

            ini_jetzt = None
            if os.path.isfile(ini_path):
                try:
                    with open(ini_path, 'rb') as f:
                        ini_jetzt = f.read()
                except OSError:
                    pass

            verloren     = ini_jetzt is None
            ist_vorlage  = (ini_jetzt is not None and example_bytes
                            and ini_jetzt == example_bytes)
            if verloren or ist_vorlage:
                _log("  ⚠  caoxt.ini wurde durch den Pull veraendert "
                     "(geloescht oder mit Vorlage ersetzt). Stelle "
                     "Snapshot vor dem Pull wieder her.")
                try:
                    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
                    with open(ini_path, 'wb') as f:
                        f.write(ini_snapshot)
                    _log("  ✓  caoxt.ini aus Snapshot wiederhergestellt.")
                except OSError as exc:
                    _log(f"  ✗  Snapshot-Restore fehlgeschlagen: {exc}")

        _ensure_caoxt_ini()

        # ── Schritt 3: Abhaengigkeiten ──────────────────────────
        _log("Schritt 3: Python-Abhaengigkeiten …")
        if req_changed:
            if not _pip_install_requirements():
                _rollback(rollback_ref, dump_path=None)
                return False
            _log("  Abhaengigkeiten aktualisiert.")
        else:
            _log("  Keine neuen Abhaengigkeiten (requirements_changed = false).")

        # ── Schritt 4: systemd-Units (idempotent) ───────────────
        _log("Schritt 4: systemd-Units pruefen …")
        _regenerate_systemd_units()

        # ── Schritt 5: DB-Dump + Migration ──────────────────────
        if db_migration_required:
            _log("Schritt 5a: DB-Dump vor Migration …")
            dump_path = _dump_database()
            if dump_path is None:
                _log("  FEHLER: DB-Dump fehlgeschlagen — Migration nicht "
                     "riskiert. Rollback (nur Code).")
                _rollback(rollback_ref, dump_path=None)
                return False

            _log("Schritt 5b: DB-Migrationen …")
            if not _run_migrations():
                _log("  Migration fehlgeschlagen — Rollback inkl. DB-Restore.")
                _rollback(rollback_ref, dump_path=dump_path)
                return False
            _log("  DB-Migrationen abgeschlossen.")
        else:
            _log("Schritt 5: Keine DB-Migrationen erforderlich.")

        # ── Schritt 6: Apps starten ─────────────────────────────
        _log("Schritt 6: Apps starten …")
        _run([_DORFKERN_CTL, 'start'], check=False, timeout=180)

        # ── Schritt 7: HTTP-Health-Check ────────────────────────
        _log("Schritt 7: HTTP-Health-Check …")
        time.sleep(5)
        ok_count, total = _http_health_check()
        _log(f"  {ok_count}/{total} Apps antworten via HTTP.")
        if ok_count < total:
            _log(f"  WARNUNG: Nicht alle Apps antworten. Logs pruefen mit "
                 f"`journalctl -u {_PREFIX}-<app>` bzw. /tmp/{_PREFIX}-<app>.log.")

        # Neue Version melden
        new_local = load_local_version()
        new_v = new_local.get('version', '?') if new_local else '?'
        _log("")
        _log(f"Update abgeschlossen. Installierte Version: {new_v}")
        if dump_path:
            _log(f"DB-Dump verfuegbar (Aufbewahrung manuell): {dump_path}")
        _log("─────────────────────────────────────────────────────────────")
        return True
    finally:
        _release_lock(lock)


def _rollback(ref: Optional[str], dump_path: Optional[str] = None) -> None:
    """Rollt Code auf ``ref`` zurueck und stellt optional die DB wieder her.

    Reihenfolge: Apps werden VOR dem git reset gestoppt (sie sollen
    nicht auf inkonsistentem Code laufen), dann reset, dann ggf.
    DB-Restore, dann Apps wieder starten.
    """
    if not ref:
        _log("  Rollback: kein Referenz-Commit bekannt — übersprungen.")
        return
    _log(f"  Rollback auf {ref[:8]} …")
    _run([_DORFKERN_CTL, 'stop'], check=False, timeout=120)
    _run(['git', 'reset', '--hard', ref], cwd=_REPO_ROOT, capture=True)

    if dump_path:
        _log(f"  DB-Restore aus {dump_path} …")
        if not _restore_database(dump_path):
            _log("  ACHTUNG: DB-Restore fehlgeschlagen! "
                 "Manuelle Pruefung der DB erforderlich.")

    # Falls Units vor dem Rollback regeneriert wurden: jetzt nochmal,
    # um die alte Unit-Definition wieder einzuspielen.
    _regenerate_systemd_units()

    _log("  Apps neu starten …")
    _run([_DORFKERN_CTL, 'start'], check=False, timeout=180)
    _log("  Rollback abgeschlossen.")


# ─── CLI ──────────────────────────────────────────────────────────────

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
    parser.add_argument('--check',  action='store_true',
                        help='Nur auf Updates prüfen')
    parser.add_argument('--update', action='store_true',
                        help='Update sofort durchführen')
    parser.add_argument('--branch', default='',
                        help='Remote-Branch (Standard: aktueller Branch)')
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     CAO-XT Update-Mechanismus                           ║")
    print("║     Habacher Dorfladen                                  ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    info("Prüfe auf Updates …")
    status = check_for_updates(args.branch)

    if status.get('error'):
        warn(f"Update-Prüfung: {status['error']}")
        return 1

    local_c  = status['local_commit']
    remote_c = status['remote_commit']
    impact   = status['impact']

    if not status['available']:
        ok(f"System ist aktuell (HEAD {local_c} = origin/{status['branch']})")
        return 0

    n = status['ahead_count']
    print()
    print(f"  Aktueller Commit    : {local_c}")
    print(f"  Remote-Commit       : {remote_c}")
    print(f"  Neue Commits        : {n}")
    if status['local_version'] or status['remote_version']:
        lv = status['local_version'] or '–'
        rv = status['remote_version'] or '–'
        print(f"  Version (Anzeige)   : {lv} → {rv}")
    print()

    if impact.get('breaking_change'):
        warn("ACHTUNG: Breaking Change! Manuelle Überprüfung empfohlen.")
    if impact.get('db_migration_required'):
        warn("Datenbank-Migration erforderlich (Dump wird vorher erstellt).")
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

    if args.check:
        return 0

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
