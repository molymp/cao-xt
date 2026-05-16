#!/usr/bin/env python3
"""
CAO-XT Installer – optionale Hibiscus/Jameica-Integration (Phase E).

Lädt Jameica + die benötigten Plugins zur Install-Zeit von willuhn.de
(gepinnte SHA-256), entpackt sie in ein Dorfkern-verwaltetes Verzeichnis
und schreibt die *Plaintext*-Konfiguration vor (Webadmin-Listener,
XML-RPC-Sharing). Banking wird nur auf dem Admin-Host angeboten.

WICHTIG zur Authentifizierung
-----------------------------
``jameica.webadmin`` prüft den **Benutzernamen nicht** – das
Basic-Auth-Passwort *ist* das Jameica-Master-Passwort
(``JameicaLoginService.login()``: ``pw.equals(getCallback()
.getPassword())``). Es gibt also keinen separaten API-User; der
Installer kann das Passwort nicht setzen – der User vergibt es bei der
Jameica-Ersteinrichtung selbst. Wir fragen es am Ende ab und legen es
in ``DORFKERN_KONFIG`` (TYP=SECRET, Kategorie HIBISCUS) ab, damit die
Orga-App sich am XML-RPC authentifizieren kann.

Die HBCI-/Bank-Erstkonfig (PIN-TAN, IBAN, Schlüssel) bleibt manuell im
Jameica-GUI – sie ist persönlich und sicherheitskritisch.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ── Artefakt-Definitionen (gepinnt) ─────────────────────────────────
#
# Integritäts-Strategie (wichtig):
# Nur ``hibiscus`` ist ein versioniertes, unveränderliches Artefakt mit
# einem offiziellen ``.SHA-256``-Sidecar → dagegen verifizieren wir
# autoritativ (überlebt Patch-Bumps innerhalb der Linie nicht, aber der
# Sidecar wird ja mitgezogen). Jameica (``current``-Symlink) und die
# drei Nischen-Plugins existieren NUR als ständig neu gebaute Nightly
# bzw. bewegliche ``current``-URL OHNE Sidecar/Signatur. Ein statisch
# verdrahteter Hash wäre dort binnen Tagen veraltet und würde den
# Installer dauernd brechen → kein Sinn. Für diese Artefakte ist die
# CA-validierte HTTPS-Verbindung zu willuhn.de der Integritätsanker;
# der beobachtete SHA-256 wird geloggt (Admin-auditierbar).

@dataclass(frozen=True)
class _Artefakt:
    name: str
    url: str
    # URL des offiziellen ``.SHA-256``-Sidecars, oder None wenn es
    # keinen autoritativen Hash gibt (dann HTTPS-Trust + Log).
    sha256_sidecar: str | None
    # 'app'    → entpackt nach <install_root>/        (enthält jameica.app/)
    # 'plugin' → entpackt nach <userdata>/plugins/    (enthält <name>/)
    ziel: str


_JAMEICA_BASIS_URL = ('https://www.willuhn.de/products/jameica/'
                      'releases/current/jameica/')


@dataclass(frozen=True)
class _JameicaPlattform:
    """Plattform-spezifische Jameica-Eigenheiten.

    Linux-Builds bringen KEIN JRE mit (System-Java nötig, Java 21+);
    macOS-Builds bündeln eine JRE. Launcher + entpacktes Wurzel-
    Verzeichnis unterscheiden sich (``jameica.app`` vs ``jameica``).
    """
    key: str               # 'macos-aarch64' | 'linux64' | …
    zip_name: str          # Datei unter _JAMEICA_BASIS_URL
    root_dir: str          # entpacktes Wurzelverzeichnis im Bundle
    launcher_gui: str      # rel. zu <basis>: GUI/Standalone-Start
    jre_bundled: bool
    # Headless: macOS hat NUR ein GUI-.sh, das hart ``-o`` setzt
    # (= „Master-PW via Cmdline ignorieren") → würde -P/-w aushebeln
    # und Jameica auf die (im -n-Modus unmögliche) Konsole verweisen.
    # Darum auf macOS java DIREKT starten (jre_java + jar). Linux hat
    # ein dediziertes ``jameicaserver.sh`` (Server, kein -o) →
    # headless_launcher nutzen.
    headless_launcher: str  # Linux: rel. server.sh; macOS: '' (java-direkt)
    jre_java: str          # macOS: rel. java-Binary; Linux: '' (System-java)
    jar: str               # macOS: rel. Jameica-Jar; Linux: ''
    headless_args: tuple   # macOS java-direkt: ('-d','-n'); Linux: ()


# JVM-Flags fürs macOS-java-direkt (aus dem GUI-.sh übernommen, ohne
# die GUI-only Flags -Xdock / -XstartOnFirstThread).
_MAC_JVM = ('-Dsun.security.smartcardio.library=/System/Library/'
            'Frameworks/PCSC.framework/Versions/Current/PCSC',
            '-Xmx512m', '-Xss64m')

# machine()-Normalisierung: amd64→x86_64; auf Darwin meldet arm64,
# auf Linux aarch64 – wir mappen über (system, normalisierte machine).
_MACHINE_ALIASES = {'amd64': 'x86_64', 'x64': 'x86_64'}

_PLATTFORMEN: dict[tuple[str, str], _JameicaPlattform] = {
    ('Darwin', 'arm64'): _JameicaPlattform(
        'macos-aarch64', 'jameica-macos-aarch64.zip', 'jameica.app',
        'jameica.app/jameica-macos-aarch64.sh', True,
        '', 'jameica.app/jre-macosaarch64/Contents/Home/bin/java',
        'jameica.app/jameica-macos-aarch64.jar', ('-d', '-n')),
    ('Darwin', 'x86_64'): _JameicaPlattform(
        'macos64', 'jameica-macos64.zip', 'jameica.app',
        'jameica.app/jameica-macos64.sh', True,
        '', 'jameica.app/jre-macos64/Contents/Home/bin/java',
        'jameica.app/jameica-macos64.jar', ('-d', '-n')),
    ('Linux', 'x86_64'): _JameicaPlattform(
        'linux64', 'jameica-linux64.zip', 'jameica',
        'jameica/jameica.sh', False,
        'jameica/jameicaserver.sh', '', '', ()),
    ('Linux', 'aarch64'): _JameicaPlattform(
        'linuxarm64', 'jameica-linuxarm64.zip', 'jameica',
        'jameica/jameica.sh', False,
        'jameica/jameicaserver.sh', '', '', ()),
}


JAVA_MIN_MAJOR = 21

# Paketmanager → (Update-Cmd | None, Install-Cmd-Praefix, JRE-Paket).
# Reihenfolge = Erkennungs-Reihenfolge. headless reicht: Jameica läuft
# im Server-Mode (jameicaserver.sh), kein AWT/SWT nötig.
_PKG_MANAGER = [
    ('apt-get', ['apt-get', 'update'],
     ['apt-get', 'install', '-y'], 'openjdk-21-jre-headless'),
    ('dnf', None, ['dnf', 'install', '-y'], 'java-21-openjdk-headless'),
    ('yum', None, ['yum', 'install', '-y'], 'java-21-openjdk-headless'),
    ('zypper', None, ['zypper', '--non-interactive', 'install'],
     'java-21-openjdk-headless'),
]


def java_major(java_bin: str = 'java') -> int | None:
    """Major-Version des erreichbaren ``java`` (oder None).

    Parst ``java -version`` (Ausgabe auf stderr). Formate:
    ``"21.0.9"`` → 21, Legacy ``"1.8.0_xxx"`` → 8.
    """
    exe = shutil.which(java_bin)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, '-version'], capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    txt = (out.stderr or '') + (out.stdout or '')
    m = re.search(r'version "(\d+)(?:\.(\d+))?', txt)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):       # 1.8 → 8
        return int(m.group(2))
    return major


def _ist_root() -> bool:
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def _sudo_prefix() -> list[str]:
    """``[]`` wenn root, sonst ``['sudo','-n']`` falls sudo da ist."""
    if _ist_root():
        return []
    if shutil.which('sudo'):
        return ['sudo', '-n']
    return []


def ensure_java(min_major: int = JAVA_MIN_MAJOR, *,
                auto_install: bool = True, print_fn=print) -> dict:
    """Stellt sicher, dass Java >= ``min_major`` verfügbar ist.

    Linux-Jameica bringt kein JRE mit. Ist eine passende JVM bereits da
    → nichts tun. Sonst (``auto_install``) per System-Paketmanager
    installieren (apt/dnf/yum/zypper, sudo-aware). Best-effort:
    schlägt sauber fehl mit klarer Anleitung statt Exception.

    Returns ``{'status': 'ok'|'installiert'|'manuell', 'major': int|None,
    'msg': str}``.
    """
    cur = java_major()
    if cur is not None and cur >= min_major:
        print_fn(f"    ✓ System-Java {cur} vorhanden (>= {min_major})")
        return {'status': 'ok', 'major': cur, 'msg': ''}

    if not auto_install:
        return {'status': 'manuell', 'major': cur,
                'msg': f'Java {min_major}+ fehlt (gefunden: {cur}). '
                       f'Manuell installieren.'}

    pm = next(((name, upd, inst, pkg)
               for name, upd, inst, pkg in _PKG_MANAGER
               if shutil.which(name)), None)
    if pm is None:
        return {'status': 'manuell', 'major': cur,
                'msg': 'Kein bekannter Paketmanager (apt/dnf/yum/'
                       'zypper). Java 21+ bitte manuell installieren.'}
    name, upd, inst, pkg = pm
    sudo = _sudo_prefix()
    if not _ist_root() and not sudo:
        return {'status': 'manuell', 'major': cur,
                'msg': f'Java {min_major}+ fehlt und weder root noch '
                       f'sudo verfügbar. Manuell: {name} install {pkg}'}
    try:
        if upd:
            print_fn(f"    … {name} update")
            subprocess.run(sudo + upd, check=True, timeout=300,
                           capture_output=True)
        print_fn(f"    … installiere {pkg} via {name}")
        subprocess.run(sudo + inst + [pkg], check=True, timeout=600,
                       capture_output=True)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b'').decode('utf-8', 'replace')[-300:]
        return {'status': 'manuell', 'major': cur,
                'msg': f'{name}-Install fehlgeschlagen: {err.strip()} '
                       f'→ manuell: {name} install {pkg}'}
    except (OSError, subprocess.SubprocessError) as e:
        return {'status': 'manuell', 'major': cur,
                'msg': f'Paketmanager-Aufruf fehlgeschlagen: {e}'}
    neu = java_major()
    if neu is not None and neu >= min_major:
        print_fn(f"    ✓ Java {neu} installiert ({pkg})")
        return {'status': 'installiert', 'major': neu, 'msg': pkg}
    return {'status': 'manuell', 'major': neu,
            'msg': f'{pkg} installiert, aber java meldet weiter '
                   f'{neu}. PATH/alternatives prüfen.'}


def aktuelle_plattform(system: str | None = None,
                        machine: str | None = None) -> _JameicaPlattform:
    """Ermittelt die Jameica-Plattform für (system, machine).

    Default = laufendes System. Wirft ``RuntimeError`` mit Liste der
    unterstützten Plattformen, wenn nichts passt (z.B. Windows).
    """
    sysname = system or platform.system()
    mach = (machine or platform.machine()).lower()
    mach = _MACHINE_ALIASES.get(mach, mach)
    p = _PLATTFORMEN.get((sysname, mach))
    if p is None:
        unterstuetzt = ', '.join(f'{s}/{m}' for s, m in _PLATTFORMEN)
        raise RuntimeError(
            f"Keine Jameica-Build für {sysname}/{mach}. "
            f"Unterstützt: {unterstuetzt}.")
    return p


def jameica_artefakt(plat: _JameicaPlattform | None = None) -> _Artefakt:
    """Baut das Jameica-Download-Artefakt für die Plattform.
    Bewegliche ``current``-URL → kein Sidecar (HTTPS-Trust + Log)."""
    plat = plat or aktuelle_plattform()
    return _Artefakt(name='jameica',
                     url=_JAMEICA_BASIS_URL + plat.zip_name,
                     sha256_sidecar=None, ziel='app')

# hibiscus hat eine stabile Release-Linie + Sidecar; xmlrpc/webadmin/
# xmlrpc-base existieren nur als Nightly (Nischen-Plugins, kein Sidecar).
PLUGINS = (
    _Artefakt(
        name='hibiscus',
        url='https://www.willuhn.de/products/hibiscus/releases/2.12/'
            'hibiscus-2.12.4.zip',
        sha256_sidecar='https://www.willuhn.de/products/hibiscus/'
                       'releases/2.12/hibiscus-2.12.4.zip.SHA-256',
        ziel='plugin',
    ),
    _Artefakt(
        name='jameica.webadmin',
        url='https://www.willuhn.de/products/jameica/releases/nightly/'
            'jameica.webadmin-2.11.0-nightly.zip',
        sha256_sidecar=None,
        ziel='plugin',
    ),
    _Artefakt(
        name='jameica.xmlrpc',
        url='https://www.willuhn.de/products/jameica/releases/nightly/'
            'jameica.xmlrpc-2.11.0-nightly.zip',
        sha256_sidecar=None,
        ziel='plugin',
    ),
    _Artefakt(
        name='hibiscus.xmlrpc',
        url='https://www.willuhn.de/products/hibiscus/releases/nightly/'
            'hibiscus.xmlrpc-2.11.0-nightly.zip',
        sha256_sidecar=None,
        ziel='plugin',
    ),
)

# Default-Layout: alles unter <repo>/.hibiscus/
DEFAULT_BASIS    = os.path.join(_REPO_ROOT, '.hibiscus')
WEBADMIN_PORT    = 8080
XMLRPC_URL_VORLAGE = 'https://{user}:{pw}@127.0.0.1:%d/xmlrpc' % WEBADMIN_PORT


# ── Download + Verify ───────────────────────────────────────────────

def _sha256_datei(pfad: str) -> str:
    h = hashlib.sha256()
    with open(pfad, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _hole_sidecar_hash(url: str) -> str:
    """Lädt eine ``.SHA-256``-Sidecar-Datei und extrahiert den Hash.

    Format (GNU coreutils): ``<hex>  <dateiname>`` bzw. ``<hex> *<name>``.
    """
    req = urllib.request.Request(
        url, headers={'User-Agent': 'cao-xt-installer'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        txt = resp.read().decode('utf-8', 'replace').strip()
    h = txt.split()[0].lower() if txt else ''
    if len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
        raise RuntimeError(f"Sidecar {url}: kein gültiger SHA-256 "
                           f"({txt[:60]!r})")
    return h


def download_und_pruefe(art: _Artefakt, ziel_zip: str, print_fn=print) -> str:
    """Lädt ``art`` nach ``ziel_zip``.

    Hat das Artefakt einen offiziellen Sidecar (``art.sha256_sidecar``),
    wird der heruntergeladene Hash autoritativ dagegen geprüft und bei
    Mismatch ``RuntimeError`` geworfen (Datei gelöscht). Ohne Sidecar
    ist die CA-validierte HTTPS-Verbindung der Integritätsanker; der
    beobachtete SHA-256 wird nur geloggt (kein Hard-Fail – statisches
    Pinnen beweglicher Nightly/current-URLs ist sinnlos).

    Returns den beobachteten SHA-256 (für Audit/Logging).
    """
    print_fn(f"    ↓ {art.name} … ")
    req = urllib.request.Request(
        art.url, headers={'User-Agent': 'cao-xt-installer'})
    with urllib.request.urlopen(req, timeout=180) as resp, \
            open(ziel_zip, 'wb') as out:
        shutil.copyfileobj(resp, out)
    ist = _sha256_datei(ziel_zip)
    kb = os.path.getsize(ziel_zip) // 1024

    if art.sha256_sidecar:
        erwartet = _hole_sidecar_hash(art.sha256_sidecar)
        if ist != erwartet:
            os.remove(ziel_zip)
            raise RuntimeError(
                f"{art.name}: SHA-256-Mismatch gegen offiziellen "
                f"Sidecar.\n      erwartet: {erwartet}\n"
                f"      erhalten: {ist}\n"
                f"      → Download korrupt oder Version geändert.")
        print_fn(f"      ✓ verifiziert gg. Sidecar ({kb} KB)")
    else:
        print_fn(f"      ✓ via HTTPS geladen ({kb} KB) "
                 f"sha256={ist[:16]}…")
    return ist


def _entpacke(zip_pfad: str, ziel_dir: str) -> None:
    """Entpackt mit Zip-Slip-Schutz UND erhaltenen Unix-Permissions.

    ``ZipFile.extractall`` verwirft das Exec-Bit — fatal für das
    Jameica-Bundle (JRE-``java``, ``*.sh``). Wir stellen den in
    ``ZipInfo.external_attr`` gespeicherten Unix-Mode wieder her.
    """
    os.makedirs(ziel_dir, exist_ok=True)
    basis = os.path.abspath(ziel_dir)
    with zipfile.ZipFile(zip_pfad) as zf:
        for info in zf.infolist():
            p = os.path.normpath(os.path.join(ziel_dir, info.filename))
            if not p.startswith(basis + os.sep) and p != basis:
                raise RuntimeError(
                    f"Unsicherer Zip-Eintrag: {info.filename!r}")
            zf.extract(info, ziel_dir)
            # Oberes 16-Bit-Wort von external_attr = Unix-st_mode.
            mode = (info.external_attr >> 16) & 0o7777
            if mode:
                ziel = os.path.join(ziel_dir, info.filename)
                if not info.is_dir():
                    os.chmod(ziel, mode)


# ── Plaintext-Konfiguration (keine Wallet) ──────────────────────────

def _schreibe_properties(pfad: str, eintraege: dict[str, str]) -> None:
    """Merged ``eintraege`` in eine Jameica-``*.properties``-Datei.

    Vorhandene Keys werden überschrieben, unbekannte beibehalten
    (Jameica-Properties sind simple ``key=value``-Zeilen, ISO-8859-1).
    """
    bestehend: dict[str, str] = {}
    if os.path.isfile(pfad):
        with open(pfad, encoding='iso-8859-1') as fh:
            for zeile in fh:
                zeile = zeile.rstrip('\n')
                if not zeile or zeile.startswith('#') or '=' not in zeile:
                    continue
                k, _, v = zeile.partition('=')
                bestehend[k.strip()] = v
    bestehend.update(eintraege)
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, 'w', encoding='iso-8859-1') as fh:
        fh.write("# von cao-xt hibiscus_setup geschrieben - nicht von Hand "
                 "editieren\n")
        for k in sorted(bestehend):
            fh.write(f"{k}={bestehend[k]}\n")


def schreibe_webadmin_config(userdata: str) -> str:
    """Listener: Auth an, SSL an, nur localhost, fester Port.

    Returns den Pfad der geschriebenen Properties-Datei.
    """
    pfad = os.path.join(
        userdata, 'cfg', 'de.willuhn.jameica.webadmin.Plugin.properties')
    _schreibe_properties(pfad, {
        'listener.http.auth':    'true',
        'listener.http.ssl':     'true',
        'listener.http.port':    str(WEBADMIN_PORT),
        'listener.http.address': '127.0.0.1',
    })
    return pfad


def schreibe_xmlrpc_sharing(userdata: str) -> str:
    """Gibt die von Dorfkern genutzten XML-RPC-Services frei und nutzt
    kurze Methodennamen (``konto.list`` statt voller Interface-Pfad)."""
    pfad = os.path.join(
        userdata, 'cfg', 'de.willuhn.jameica.xmlrpc.Plugin.properties')
    eintraege = {'xmlrpc.useinterfacenames': 'false'}
    for svc in ('address', 'konto', 'umsatz', 'sepaueberweisung',
                'sepalastschrift', 'sepasammelueberweisung',
                'sepasammellastschrift'):
        eintraege[f'hibiscus.xmlrpc.{svc}.shared'] = 'true'
    eintraege['jameica.webadmin.listener.http.shared'] = 'true'
    # Hibiscus-CORE-Service (kein hibiscus.xmlrpc): read-only Status der
    # automatischen Synchronisierung (letzter/naechster Lauf, Status).
    eintraege['hibiscus.synchronizescheduler.shared'] = 'true'
    _schreibe_properties(pfad, eintraege)
    return pfad


_SYNC_SCHED_PROPS = ('de.willuhn.jameica.hbci.'
                     'SynchronizeSchedulerSettings.properties')

# Konservativer Default: PSD2/FinTS erlaubt Konto-Info-Abruf ohne
# frische SCA nur begrenzt (typisch ~4×/24 h, bankabhängig) UND
# erzwingt unabhängig davon mind. alle 90 Tage eine SCA (S-pushTAN,
# Mensch am Handy — kann KEINE App). 360 min über 07–19 Uhr ≈ 3
# Läufe/Tag → bleibt unter dem Limit.
SYNC_DEFAULT_INTERVAL_MIN = 360
SYNC_DEFAULT_START_HOUR   = 7
SYNC_DEFAULT_END_HOUR     = 19


def schreibe_sync_scheduler(userdata: str, *,
                            interval_min: int = SYNC_DEFAULT_INTERVAL_MIN,
                            start_hour: int = SYNC_DEFAULT_START_HOUR,
                            end_hour: int = SYNC_DEFAULT_END_HOUR,
                            enabled: bool = True,
                            stop_on_error: bool = True) -> str:
    """Konfiguriert Hibiscus' interne automatische Synchronisierung.

    Read-only-Scope (Saldo/Umsaetze/Banknachrichten) ist in Hibiscus
    pro Konto bereits Default-an; was fehlt, ist der Zeit-Scheduler.
    Keys: ``de.willuhn.jameica.hbci.SynchronizeSchedulerSettings``.

    ACHTUNG Frequenz: zu viele Abrufe/Tag → Bank erzwingt SCA
    (S-pushTAN, manuell). Default bewusst konservativ (~3/Tag).
    """
    pfad = os.path.join(userdata, 'cfg', _SYNC_SCHED_PROPS)
    _schreibe_properties(pfad, {
        'enabled':          'true' if enabled else 'false',
        'interval.minutes': str(int(interval_min)),
        'start.hour':       str(int(start_hour)),
        'end.hour':         str(int(end_hour)),
        'stoponerror':      'true' if stop_on_error else 'false',
    })
    return pfad


def lies_sync_scheduler(userdata: str) -> dict:
    """Liest die aktuelle Auto-Sync-Scheduler-Konfig (für die Admin-UI).

    Fehlt die Datei → Defaults (deaktiviert-Annahme nur fürs Anzeigen;
    Hibiscus-Default von ``enabled`` ist ohnehin false).
    """
    pfad = os.path.join(userdata, 'cfg', _SYNC_SCHED_PROPS)
    werte = {
        'enabled': False,
        'interval_min': SYNC_DEFAULT_INTERVAL_MIN,
        'start_hour': SYNC_DEFAULT_START_HOUR,
        'end_hour': SYNC_DEFAULT_END_HOUR,
        'stop_on_error': True,
        'vorhanden': False,
    }
    if not os.path.isfile(pfad):
        return werte
    werte['vorhanden'] = True
    with open(pfad, encoding='iso-8859-1') as fh:
        for zeile in fh:
            zeile = zeile.strip()
            if not zeile or zeile.startswith('#') or '=' not in zeile:
                continue
            k, _, v = zeile.partition('=')
            k, v = k.strip(), v.strip()
            if k == 'enabled':
                werte['enabled'] = v.lower() == 'true'
            elif k == 'interval.minutes' and v.isdigit():
                werte['interval_min'] = int(v)
            elif k == 'start.hour' and v.isdigit():
                werte['start_hour'] = int(v)
            elif k == 'end.hour' and v.isdigit():
                werte['end_hour'] = int(v)
            elif k == 'stoponerror':
                werte['stop_on_error'] = v.lower() == 'true'
    return werte


# Letzter Fallback, wenn der Aufrufer KEIN Schema übergibt. Der reale
# Default kommt aus install.py: die Dorfkern-HAUPT-DB (caoxt.ini
# db_name, z.B. cao_XT_DEV) — dort liegen die Hibiscus-Tabellen bereits
# als 1:1-Spiegel, das Dorfkern-Jameica nutzt also genau dieses Schema
# (NICHT ein separates 'hibiscus' — das ist nur die Notfall-Vorgabe).
DEFAULT_DB_SCHEMA = 'hibiscus'

# Quelle: DBSupportMySqlImpl.getJdbcUrl()-Default (Hibiscus-Code).
_JDBC_URL_VORLAGE = (
    'jdbc:mariadb://{host}:{port}/{schema}'
    '?useUnicode=Yes&characterEncoding=ISO8859_1'
    '&serverTimezone=Europe/Paris'
)
_DB_DRIVER_MYSQL = 'de.willuhn.jameica.hbci.server.DBSupportMySqlImpl'


def schreibe_db_config(userdata: str, *, host: str, port: int,
                       schema: str = DEFAULT_DB_SCHEMA,
                       user: str, password: str) -> str:
    """Konfiguriert Hibiscus auf MariaDB statt der eingebetteten H2-DB.

    Schreibt ``cfg/de.willuhn.jameica.hbci.rmi.HBCIDBService.properties``
    (Settings-Klasse = ``HBCIDBService``). Damit hängt ein Frisch-Install
    sofort an derselben MariaDB → "Config liegt in der DB" greift ohne
    weitere Schritte; nur die Bank-/Konten-Erstkonfig (PIN-TAN) macht der
    User danach im Jameica-GUI.

    Das Passwort ist Plaintext (Hibiscus verschlüsselt nur bei
    ``encrypt=true``, Default ist ``false``) — analog zur ohnehin im
    Klartext liegenden caoxt.ini-DB-Sektion auf demselben Server.
    """
    pfad = os.path.join(
        userdata, 'cfg',
        'de.willuhn.jameica.hbci.rmi.HBCIDBService.properties')
    jdbc = _JDBC_URL_VORLAGE.format(host=host, port=int(port), schema=schema)
    _schreibe_properties(pfad, {
        'database.driver':               _DB_DRIVER_MYSQL,
        'database.driver.mysql.jdbcurl':  jdbc,
        'database.driver.mysql.username': user,
        'database.driver.mysql.password': password,
    })
    return pfad


def schreibe_caoxt_ini_block(ini_path: str, *, user: str = 'dorfkern',
                              url: str | None = None) -> None:
    """Fügt/aktualisiert den ``[Hibiscus]``-Block in caoxt.ini.

    Das Passwort steht NICHT in der ini – es liegt in DORFKERN_KONFIG
    (siehe :func:`speichere_master_passwort`). Hier nur URL + User
    (User wird von webadmin ignoriert, aber Basic-Auth braucht formal
    einen).
    """
    import configparser
    cfg = configparser.ConfigParser()
    if os.path.isfile(ini_path):
        cfg.read(ini_path, encoding='utf-8')
    if not cfg.has_section('Hibiscus'):
        cfg.add_section('Hibiscus')
    cfg.set('Hibiscus', 'aktiv', '1')
    cfg.set('Hibiscus', 'xmlrpc_url',
            url or f'https://127.0.0.1:{WEBADMIN_PORT}/xmlrpc')
    cfg.set('Hibiscus', 'xmlrpc_user', user)
    cfg.set('Hibiscus', 'pw_quelle', 'DORFKERN_KONFIG:hibiscus.master_passwort')
    with open(ini_path, 'w', encoding='utf-8') as fh:
        cfg.write(fh)


def jameica_start_cmd(basis: str = DEFAULT_BASIS, *, headless: bool = False,
                       passwordfile: str | None = None,
                       passwordcommand: str | None = None,
                       plat: _JameicaPlattform | None = None) -> list[str]:
    """Liefert das argv zum Start des Dorfkern-gemanagten Jameica.

    Kern: ``-f <userdata>`` zeigt Jameica auf unser ``.hibiscus/
    userdata`` (sonst läge die Config im OS-Default-Verzeichnis).
    GUI-Default (Standalone) für die Bank-/Master-PW-Ersteinrichtung;
    ``headless`` für den Daemon-Betrieb.

    Master-Passwort fürs headless-Unlock:
    - ``passwordcommand`` (``-P``): Jameica ruft das Kommando und liest
      dessen stdout — Bevorzugt, weil das Passwort NICHT als Datei auf
      der Platte landet (Dorfkern: ``python -m installer.hibiscus_pw``).
    - ``passwordfile`` (``-w``): Fallback, Datei mit 600-Rechten.
    ``passwordcommand`` hat Vorrang, wenn beides gesetzt ist.

    Plattformabhängig: Linux hat einen eigenen ``jameicaserver.sh``
    (bereits Server-Mode → keine ``-d -n`` nötig), macOS startet das
    GUI-Skript mit ``-d -n``. Linux bringt KEIN JRE mit – System-Java
    21+ muss vorhanden sein.
    """
    plat = plat or aktuelle_plattform()
    userdata = os.path.join(basis, 'userdata')

    if not headless:
        sh = os.path.join(basis, *plat.launcher_gui.split('/'))
        return [sh, '-f', userdata]

    # ---- headless ----
    if plat.jre_java:
        # macOS: java DIREKT (GUI-.sh erzwingt -o, das -P/-w aushebelt).
        # Jameica prüft inProgramDir gegen das Prozess-CWD → wir cd'en
        # ins Programm-Verzeichnis (wie es das .sh täte), userdata liegt
        # ausserhalb. Alles als ein `sh -c`, da CWD + exec nötig.
        progdir = os.path.join(basis, *plat.root_dir.split('/'))
        java = os.path.join(basis, *plat.jre_java.split('/'))
        jar = os.path.join(basis, *plat.jar.split('/'))
        teile = [f'cd {shlex.quote(progdir)} &&',
                 'exec', shlex.quote(java), *_MAC_JVM,
                 '-jar', shlex.quote(jar),
                 *plat.headless_args,
                 '-f', shlex.quote(userdata)]
        if passwordcommand:
            teile += ['-P', shlex.quote(passwordcommand)]
        elif passwordfile:
            teile += ['-w', shlex.quote(passwordfile)]
        return ['sh', '-c', ' '.join(teile)]

    # Linux: dediziertes Server-Skript (kein -o, cd't selbst).
    sh = os.path.join(basis, *plat.headless_launcher.split('/'))
    cmd = [sh, '-f', userdata, *plat.headless_args]
    if passwordcommand:
        cmd += ['-P', passwordcommand]
    elif passwordfile:
        cmd += ['-w', passwordfile]
    return cmd


def ist_installiert(basis: str = DEFAULT_BASIS,
                    plat: _JameicaPlattform | None = None) -> bool:
    """True, wenn unter ``basis`` ein lauffähiges Jameica liegt
    (Launcher-Skript vorhanden). Für die App-Steuerung, damit die
    Kachel „nicht installiert" statt „abgestürzt" zeigt."""
    try:
        plat = plat or aktuelle_plattform()
    except RuntimeError:
        return False
    launcher = os.path.join(basis, *plat.launcher_gui.split('/'))
    return os.path.isfile(launcher)


def speichere_master_passwort(pw: str, ma_id: int | None = None) -> bool:
    """Legt das Jameica-Master-Passwort in DORFKERN_KONFIG ab
    (TYP=SECRET, Kategorie HIBISCUS).

    Returns ``True`` bei Erfolg, ``False`` wenn die DB nicht erreichbar
    ist (dann muss der User es später in der Admin-UI nachtragen).
    """
    pw = (pw or '').strip()
    if not pw:
        return False
    try:
        from common import konfig
        konfig.run_migration()
        konfig.set(
            'hibiscus.master_passwort', pw, typ='SECRET',
            kategorie='HIBISCUS',
            beschreibung='Jameica-Master-Passwort = Webadmin/XML-RPC '
                         'Basic-Auth-Passwort (Benutzername wird ignoriert).',
            ma_id=ma_id,
        )
        return True
    except Exception:
        return False


# ── Orchestrierung ──────────────────────────────────────────────────

def setup(basis: str = DEFAULT_BASIS, *,
          ini_path: str | None = None,
          master_pw: str | None = None,
          db_host: str | None = None,
          db_port: int = 3306,
          db_schema: str = DEFAULT_DB_SCHEMA,
          db_user: str | None = None,
          db_pass: str | None = None,
          plat: _JameicaPlattform | None = None,
          java_autoinstall: bool = True,
          print_fn=print) -> dict:
    """Komplette optionale Hibiscus-Installation (plattformabhängig).

    Layout::

        <basis>/<root_dir>/                 (Jameica; macOS inkl. JRE)
        <basis>/userdata/                   (Jameica-Userdata, -f Ziel)
        <basis>/userdata/plugins/<plugin>/  (Hibiscus-Plugins, Java)

    ``plat`` default = laufendes System (Linux/macOS, x86_64/arm64).
    Linux bringt kein JRE mit → System-Java 21+ erforderlich.

    Returns ein dict mit Pfaden + Status für den Abschlussbericht.
    """
    plat = plat or aktuelle_plattform()
    app_dir      = basis
    userdata     = os.path.join(basis, 'userdata')
    plugins_dir  = os.path.join(userdata, 'plugins')
    os.makedirs(plugins_dir, exist_ok=True)

    # Linux bringt keine JRE mit → System-Java sicherstellen (Auto-
    # Install via Paketmanager). macOS-Bundle hat eine eigene JRE.
    java_info = {'status': 'gebündelt', 'major': None, 'msg': ''}
    if not plat.jre_bundled:
        java_info = ensure_java(auto_install=java_autoinstall,
                                print_fn=print_fn)

    with tempfile.TemporaryDirectory(prefix='cxhib-') as tmp:
        # 1) Jameica (plattformspezifisches Bundle)
        print_fn(f"    Plattform: {plat.key} "
                 f"(JRE {'gebündelt' if plat.jre_bundled else 'extern'})")
        jzip = os.path.join(tmp, 'jameica.zip')
        download_und_pruefe(jameica_artefakt(plat), jzip, print_fn)
        _entpacke(jzip, app_dir)
        # 2) Plugins
        for art in PLUGINS:
            pzip = os.path.join(tmp, f'{art.name}.zip')
            download_und_pruefe(art, pzip, print_fn)
            _entpacke(pzip, plugins_dir)

    # 3) Plaintext-Konfig
    wa = schreibe_webadmin_config(userdata)
    xr = schreibe_xmlrpc_sharing(userdata)
    sc = schreibe_sync_scheduler(userdata)
    print_fn(f"    ✓ Webadmin-Listener konfiguriert ({os.path.basename(wa)})")
    print_fn(f"    ✓ XML-RPC-Sharing aktiviert ({os.path.basename(xr)})")
    print_fn(f"    ✓ Auto-Sync-Scheduler aktiviert ({os.path.basename(sc)})")

    # 3b) MariaDB-Anbindung (statt H2) – damit "Config liegt in der DB"
    db_konfiguriert = False
    if db_host and db_user:
        schreibe_db_config(
            userdata, host=db_host, port=db_port, schema=db_schema,
            user=db_user, password=db_pass or '')
        db_konfiguriert = True
        print_fn(f"    ✓ Hibiscus-DB → MariaDB {db_host}:{db_port}"
                 f"/{db_schema} (statt H2)")
    else:
        print_fn("    –  Keine DB-Parameter übergeben → Hibiscus bleibt "
                 "auf H2 (in Jameica manuell umstellen)")

    # 4) caoxt.ini-Block
    if ini_path:
        schreibe_caoxt_ini_block(ini_path)
        print_fn("    ✓ [Hibiscus]-Block in caoxt.ini geschrieben")

    # 5) Master-Passwort (optional, falls schon bekannt)
    pw_ok = False
    if master_pw:
        pw_ok = speichere_master_passwort(master_pw)
        print_fn("    ✓ Master-Passwort in DORFKERN_KONFIG abgelegt"
                 if pw_ok else
                 "    ⚠  Master-Passwort konnte nicht gespeichert werden "
                 "(DB?) – später in der Admin-UI nachtragen")

    if not plat.jre_bundled and java_info['status'] == 'manuell':
        print_fn(f"    ⚠  System-Java nicht sichergestellt: "
                 f"{java_info['msg']}")

    return {
        'app_dir':   app_dir,
        'userdata':  userdata,
        'plattform': plat.key,
        'jre_extern': not plat.jre_bundled,
        'java':      java_info,
        'plugins':   [a.name for a in PLUGINS],
        'pw_gespeichert': pw_ok,
        'db_konfiguriert': db_konfiguriert,
        'start_cmd': jameica_start_cmd(basis, plat=plat),
    }
