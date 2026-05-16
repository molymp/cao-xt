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


JAMEICA_MACOS_AARCH64 = _Artefakt(
    name='jameica',
    url='https://www.willuhn.de/products/jameica/releases/current/'
        'jameica/jameica-macos-aarch64.zip',
    sha256_sidecar=None,   # bewegliche current-URL, kein Sidecar
    ziel='app',
)

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
    _schreibe_properties(pfad, eintraege)
    return pfad


# Default-Schema: dediziert (NICHT in die CAO-DB mischen). Auf dem
# Dev-Mac liegen die Tabellen zwar in cao_XT_DEV (Shortcut), ein
# Frisch-Install soll aber ein sauberes ``hibiscus``-Schema nutzen.
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
                       passwordfile: str | None = None) -> list[str]:
    """Liefert das argv zum Start des Dorfkern-gemanagten Jameica.

    Kern: ``-f <userdata>`` zeigt Jameica auf unser ``.hibiscus/
    userdata`` (sonst läge die Config in ``~/Library/jameica``).
    GUI-Default (Standalone) für die Bank-/Master-PW-Ersteinrichtung;
    ``headless`` (= Server-Mode, abgekoppelt) für den späteren Daemon,
    dann mit ``passwordfile`` (``-w``) fürs Master-PW (Datei mit
    600-Rechten, vom Aufrufer verwaltet — NICHT vom Installer).
    """
    sh = os.path.join(basis, 'jameica.app', 'jameica-macos-aarch64.sh')
    userdata = os.path.join(basis, 'userdata')
    cmd = [sh, '-f', userdata]
    if headless:
        cmd += ['-d', '-n']
        if passwordfile:
            cmd += ['-w', passwordfile]
    return cmd


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
          print_fn=print) -> dict:
    """Komplette optionale Hibiscus-Installation.

    Layout::

        <basis>/jameica.app/                (Jameica + JRE)
        <basis>/userdata/                   (Jameica-Userdata, -d Ziel)
        <basis>/userdata/plugins/<plugin>/  (Hibiscus-Plugins)

    Returns ein dict mit Pfaden + Status für den Abschlussbericht.
    """
    app_dir      = basis
    userdata     = os.path.join(basis, 'userdata')
    plugins_dir  = os.path.join(userdata, 'plugins')
    os.makedirs(plugins_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='cxhib-') as tmp:
        # 1) Jameica
        jzip = os.path.join(tmp, 'jameica.zip')
        download_und_pruefe(JAMEICA_MACOS_AARCH64, jzip, print_fn)
        _entpacke(jzip, app_dir)
        # 2) Plugins
        for art in PLUGINS:
            pzip = os.path.join(tmp, f'{art.name}.zip')
            download_und_pruefe(art, pzip, print_fn)
            _entpacke(pzip, plugins_dir)

    # 3) Plaintext-Konfig
    wa = schreibe_webadmin_config(userdata)
    xr = schreibe_xmlrpc_sharing(userdata)
    print_fn(f"    ✓ Webadmin-Listener konfiguriert ({os.path.basename(wa)})")
    print_fn(f"    ✓ XML-RPC-Sharing aktiviert ({os.path.basename(xr)})")

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

    return {
        'app_dir':   app_dir,
        'userdata':  userdata,
        'plugins':   [a.name for a in PLUGINS],
        'pw_gespeichert': pw_ok,
        'db_konfiguriert': db_konfiguriert,
        'start_cmd': jameica_start_cmd(basis),
    }
