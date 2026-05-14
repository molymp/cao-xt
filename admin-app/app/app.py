"""
CAO-XT Admin-App – Flask-Hauptanwendung
Starten: cd admin-app/app && python3 app.py
"""
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, send_from_directory)
from jinja2 import ChoiceLoader, FileSystemLoader
from functools import wraps
from datetime import datetime
import base64
import configparser
import hashlib
import os
import socket
import subprocess
import sys
import logging
import config
import db as db_modul
from db import get_db, get_db_transaction, test_verbindung, reset_pool
from common.auth import mitarbeiter_login_karte
from common.permission import flask_helpers as _perm_flask_helpers

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['JSON_ENSURE_ASCII'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DOKU_DIR = os.path.join(BASE_DIR, 'doku')

# Zusaetzliche Template-Quelle: common/templates/ fuer gemeinsame Bausteine
# (Navbar, Toast, Touch-Widgets, Login-Shell). Wird mit App-eigenen Templates
# ueber ChoiceLoader kombiniert (App-Templates haben Vorrang).
_COMMON_TEMPLATES = os.path.normpath(
    os.path.join(BASE_DIR, '..', '..', 'common', 'templates')
)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(_COMMON_TEMPLATES),
])

# Dorfkern-Permissions: hat_recht in Jinja-Templates verfuegbar machen
# (Sidebar-Filtering + ausgegraute Eintraege bei fehlenden Rechten).
_permission_required, _perm_ctx = _perm_flask_helpers()
app.context_processor(_perm_ctx)


# ── DB-Migrationen ──────────────────────────────────────────────

def _migrationen_ausfuehren():
    """Erstellt benötigte Tabellen falls nicht vorhanden."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_DRUCKER_CONFIG (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    terminal_nr  INT NOT NULL,
                    ip_adresse   VARCHAR(64) NOT NULL,
                    port         INT DEFAULT 9100,
                    bezeichnung  VARCHAR(128),
                    geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_terminal (terminal_nr)
                )
            """)
            log.info("Migration: XT_DRUCKER_CONFIG geprüft/erstellt.")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_EINSTELLUNGEN (
                    schluessel   VARCHAR(100) NOT NULL PRIMARY KEY,
                    wert         VARCHAR(500) NOT NULL DEFAULT '',
                    beschreibung VARCHAR(255),
                    geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    geaendert_von VARCHAR(100)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Systemweite Einstellungen (key-value)'
            """)
            # Standardwerte für Parken-Schalter (INSERT IGNORE → nur beim ersten Mal)
            cur.execute("""
                INSERT IGNORE INTO XT_EINSTELLUNGEN (schluessel, wert, beschreibung)
                VALUES
                    ('kiosk_parken_aktiv', '1', 'Parken-Funktion in der Kiosk-App aktiv'),
                    ('kasse_parken_aktiv', '1', 'Parken-Funktion in der Kasse-App aktiv'),
                    ('personal_bundesland', 'BY', 'Bundesland fuer gesetzliche Feiertage (BY, BW, BE, BB, HB, HH, HE, MV, NI, NW, RP, SL, SN, ST, SH, TH)'),
                    ('personal_urlaub_uebertrag_verfall', '03-31', 'Stichtag (Format MM-TT) im Folgejahr, bis zu dem Urlaubsuebertraege aus dem Vorjahr genommen werden muessen – danach verfallen sie ersatzlos')
            """)
            log.info("Migration: XT_EINSTELLUNGEN geprüft/erstellt.")
            # Benachrichtigungs-Empfaenger (E-Mail-Verteiler je Bereich).
            # Spiegel des Schemas in modules/orga/personal/schema.sql –
            # idempotent, damit die Admin auch ohne orga-Start laeuft.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_BENACHRICHTIGUNG_EMPFAENGER (
                    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    BEREICH      VARCHAR(40)  NOT NULL,
                    EMAIL        VARCHAR(150) NOT NULL,
                    NAME         VARCHAR(100) NULL,
                    AKTIV        TINYINT UNSIGNED NOT NULL DEFAULT 1,
                    ERSTELLT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ERSTELLT_VON INT UNSIGNED NULL,
                    UNIQUE KEY uq_bereich_email (BEREICH, EMAIL),
                    INDEX idx_bereich_aktiv (BEREICH, AKTIV)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='E-Mail-Verteiler fuer Hinweis-Benachrichtigungen'
            """)
            log.info("Migration: XT_BENACHRICHTIGUNG_EMPFAENGER geprüft/erstellt.")
            # Spalte VERFAELLT_AM in XT_PERSONAL_URLAUB_KORREKTUR –
            # fuer Urlaubsuebertrag-Verfall (Spiegel zu
            # modules/orga/personal/schema.sql). Nur ausfuehren, wenn die
            # Zieltabelle bereits existiert (sonst legt das orga-Modul sie
            # beim ersten Personal-Zugriff an und die Spalte kommt dort mit).
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                " WHERE TABLE_SCHEMA = DATABASE() "
                "   AND TABLE_NAME = 'XT_PERSONAL_URLAUB_KORREKTUR'"
            )
            if cur.fetchone()['n']:
                cur.execute("""
                    ALTER TABLE XT_PERSONAL_URLAUB_KORREKTUR
                      ADD COLUMN IF NOT EXISTS VERFAELLT_AM DATE NULL
                      COMMENT 'Stichtag, bis zu dem diese Korrektur verbraucht sein muss'
                      AFTER KOMMENTAR
                """)
                log.info("Migration: XT_PERSONAL_URLAUB_KORREKTUR.VERFAELLT_AM geprüft.")
            # Log-Tabelle fuer Stunden-Korrekturen (GoBD, append-only) –
            # Spiegel zu modules/orga/personal/schema.sql.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_PERSONAL_STUNDEN_KORREKTUR_LOG (
                    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    PERS_ID          INT UNSIGNED NOT NULL,
                    REF_REC_ID       INT UNSIGNED NOT NULL,
                    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
                    FELDER_ALT_JSON  JSON         NULL,
                    FELDER_NEU_JSON  JSON         NULL,
                    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    GEAEND_VON       INT UNSIGNED NULL,
                    INDEX idx_pers_id   (PERS_ID),
                    INDEX idx_geaend_at (GEAEND_AT)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_STUNDEN_KORREKTUR'
            """)
            log.info("Migration: XT_PERSONAL_STUNDEN_KORREKTUR_LOG geprüft/erstellt.")
            # Spalte IN_ZEITERFASSUNG in XT_PERSONAL_LOHNART + Seed-Eintrag
            # fuer 'Leitende Angestellte / GF' (Spiegel zu
            # modules/orga/personal/schema.sql).
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                " WHERE TABLE_SCHEMA = DATABASE() "
                "   AND TABLE_NAME = 'XT_PERSONAL_LOHNART'"
            )
            if cur.fetchone()['n']:
                cur.execute("""
                    ALTER TABLE XT_PERSONAL_LOHNART
                      ADD COLUMN IF NOT EXISTS IN_ZEITERFASSUNG TINYINT(1)
                         NOT NULL DEFAULT 1
                         COMMENT '1 = nimmt an Zeiterfassung teil, 0 = nicht'
                         AFTER SV_PFLICHTIG_FLAG
                """)
                cur.execute("""
                    INSERT IGNORE INTO XT_PERSONAL_LOHNART
                      (LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG,
                       SV_PFLICHTIG_FLAG, IN_ZEITERFASSUNG, SORT)
                    VALUES (7, 'Leitende Angestellte / GF', 0, 1, 0, 70)
                """)
                log.info("Migration: XT_PERSONAL_LOHNART.IN_ZEITERFASSUNG geprüft.")
            # Spalte vorlaufzeit_tage in XT_KIOSK_PRODUKTE (Backwaren-Vorlauf,
            # Spiegel zu kiosk-app/schema.sql M2). Nur ausfuehren, wenn die
            # Backwaren-Tabelle bereits existiert.
            cur.execute(
                "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES "
                " WHERE TABLE_SCHEMA = DATABASE() "
                "   AND TABLE_NAME = 'XT_KIOSK_PRODUKTE'"
            )
            if cur.fetchone()['n']:
                cur.execute("""
                    ALTER TABLE XT_KIOSK_PRODUKTE
                      ADD COLUMN IF NOT EXISTS vorlaufzeit_tage TINYINT
                         NOT NULL DEFAULT 0
                         COMMENT 'Tage Vorlauf fuer Vorbestellungen (0 = keine, 2 = z.B. Laugenbaguette)'
                         AFTER hinweis
                """)
                # Views aktualisieren, damit der neue Wert auch gelesen werden
                # kann. CREATE OR REPLACE ist idempotent.
                cur.execute("""
                    CREATE OR REPLACE VIEW XT_KIOSK_V_ARTIKEL_VERWALTUNG AS
                    SELECT
                        a.REC_ID                                    AS id,
                        a.ARTNUM                                    AS artnum,
                        a.KURZNAME                                  AS name,
                        ROUND(a.VK5B * 100)                         AS preis_cent,
                        COALESCE(p.kategorie_id, 0)                 AS kategorie_id,
                        COALESCE(k.name, '– nicht zugeordnet –')    AS kategorie_name,
                        COALESCE(p.einheit,    'Stck.')              AS einheit,
                        COALESCE(p.wochentage, '')                  AS wochentage,
                        p.zutaten,
                        COALESCE(p.aktiv, 1)                        AS aktiv,
                        p.hinweis,
                        p.bild_pfad,
                        COALESCE(p.vorlaufzeit_tage, 0)             AS vorlaufzeit_tage,
                        CASE WHEN p.id IS NULL THEN 'fehlt' ELSE 'vorhanden' END AS kiosk_eintrag
                    FROM ARTIKEL a
                    LEFT JOIN XT_KIOSK_PRODUKTE p   ON p.id = a.REC_ID
                    LEFT JOIN XT_KIOSK_KATEGORIEN k ON k.id = p.kategorie_id
                    WHERE a.WARENGRUPPE = '101'
                    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME
                """)
                cur.execute("""
                    CREATE OR REPLACE VIEW XT_KIOSK_V_PRODUKTE AS
                    SELECT
                        a.REC_ID                                    AS id,
                        a.ARTNUM                                    AS artnum,
                        a.KURZNAME                                  AS name,
                        ROUND(a.VK5B * 100)                         AS preis_cent,
                        p.kategorie_id,
                        COALESCE(k.name, '– Sonstige –')            AS kategorie_name,
                        COALESCE(k.sort_order, 999)                 AS kategorie_sort,
                        p.einheit,
                        COALESCE(p.wochentage, '')                  AS wochentage,
                        p.zutaten,
                        p.aktiv,
                        p.hinweis,
                        p.bild_pfad,
                        COALESCE(p.vorlaufzeit_tage, 0)             AS vorlaufzeit_tage
                    FROM ARTIKEL a
                    JOIN XT_KIOSK_PRODUKTE p     ON p.id = a.REC_ID
                    LEFT JOIN XT_KIOSK_KATEGORIEN k ON k.id = p.kategorie_id
                    WHERE a.WARENGRUPPE = '101'
                      AND p.aktiv > 0
                    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME
                """)
                log.info("Migration: XT_KIOSK_PRODUKTE.vorlaufzeit_tage + Views aktualisiert.")
    except Exception as e:
        log.warning("Migration fehlgeschlagen (DB evtl. nicht erreichbar): %s", e)


def _dorfkern_konfig_initialisieren():
    """Legt DORFKERN_KONFIG an und saet initial aus caoxt.ini.

    Die Admin-App ist Eigentuemer dieser Tabelle (Phase 3). INSERT IGNORE
    sorgt dafuer, dass nachtraegliche Admin-UI-Aenderungen nicht
    ueberschrieben werden, wenn der Seed beim naechsten Start erneut laeuft.
    """
    try:
        from common import konfig
    except Exception as exc:
        log.warning("DORFKERN_KONFIG-Init: Modul-Import fehlgeschlagen: %s", exc)
        return
    konfig.run_migration()
    try:
        n = konfig.seed_aus_ini()
        if n:
            log.info("DORFKERN_KONFIG: %d Werte aus caoxt.ini uebernommen.", n)
    except Exception as exc:
        log.warning("DORFKERN_KONFIG-Seed fehlgeschlagen: %s", exc)


def _terminal_registry_initialisieren():
    """Legt die TERMINAL-Tabelle an (Phase 4). Admin-App ist Eigentuemer."""
    try:
        from common import terminal as _terminal
    except Exception as exc:
        log.warning("TERMINAL-Init: Modul-Import fehlgeschlagen: %s", exc)
        return
    _terminal.run_migration()


def _permission_initialisieren():
    """Legt DORFKERN_PERMISSION_* an und saet den Objekt-Katalog (Phase 6)."""
    try:
        from common import permission
    except Exception as exc:
        log.warning("Permission-Init: Modul-Import fehlgeschlagen: %s", exc)
        return
    permission.run_migration()
    try:
        n = permission.seed_objekte()
        if n:
            log.info("DORFKERN_PERMISSION_OBJEKT: %d Eintraege angelegt.", n)
    except Exception as exc:
        log.warning("Permission-Seed fehlgeschlagen: %s", exc)


def _aktivierung_initialisieren():
    """Legt DORFKERN_APP_AKTIVIERUNG an und saet die 4 Default-Apps (Phase 7)."""
    try:
        from common import aktivierung
    except Exception as exc:
        log.warning("Aktivierung-Init: Modul-Import fehlgeschlagen: %s", exc)
        return
    aktivierung.run_migration()
    try:
        n = aktivierung.seed_defaults()
        if n:
            log.info("DORFKERN_APP_AKTIVIERUNG: %d Eintraege angelegt.", n)
    except Exception as exc:
        log.warning("Aktivierung-Seed fehlgeschlagen: %s", exc)


def _einkauf_initialisieren():
    """Legt XT_EINKAUF_LIEFERANT an und saet UTZ als Default (Phase 1)."""
    try:
        from common import einkauf as _ek
    except Exception as exc:
        log.warning("Einkauf-Init: Modul-Import fehlgeschlagen: %s", exc)
        return
    _ek.run_migration()
    try:
        n = _ek.seed_defaults()
        if n:
            log.info("XT_EINKAUF_LIEFERANT: %d Default-Eintraege angelegt.", n)
    except Exception as exc:
        log.warning("Einkauf-Seed fehlgeschlagen: %s", exc)


_migrationen_ausfuehren()
_dorfkern_konfig_initialisieren()
_terminal_registry_initialisieren()
_permission_initialisieren()
_aktivierung_initialisieren()
_einkauf_initialisieren()


def _cao_hashsum_initialisieren():
    """Trägt die CAO-HASHSUM-Salt-Schluessel in DORFKERN_KONFIG ein
    (Kategorie CAO_HASH_SALT, mit leeren Werten + Hinweis-Beschreibung).
    Die eigentlichen Salt-Werte muss der Admin manuell pflegen –
    sie liegen NICHT im Repo."""
    try:
        from common import cao_hashsum as _ch
        _ch.seed_registry()
        log.info('CAO-Hash-Salt-Registry geprueft (Kategorie CAO_HASH_SALT).')
    except Exception as exc:
        log.warning('CAO-Hash-Salt-Registry-Init fehlgeschlagen: %s', exc)


_cao_hashsum_initialisieren()

# RFID-Tabelle (Mitarbeiter alternativ ueber Alarm-RFID-Tag identifizieren)
try:
    from common import rfid as _rfid_mod
    _rfid_mod.run_migration()
except Exception as _exc:
    log.warning("RFID-Migration uebersprungen: %s", _exc)


# ── Git-Commit-Hash (einmalig beim Start) ─────────────────────

try:
    _r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=5, cwd=BASE_DIR,
    )
    GIT_COMMIT_SHORT = _r.stdout.strip() if _r.returncode == 0 else ""
except Exception:
    GIT_COMMIT_SHORT = ""


# ── Authentifizierung ────────────────────────────────────────────

def _mitarbeiter_login(login_name: str, passwort: str) -> dict | None:
    """
    Prüft Credentials gegen MITARBEITER-Tabelle.
    CAO speichert Passwörter als MD5-Hash (Großbuchstaben).
    """
    pw_hash = hashlib.md5(passwort.encode('utf-8')).hexdigest().upper()
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT MA_ID, LOGIN_NAME, VNAME, NAME FROM MITARBEITER "
                "WHERE LOGIN_NAME = %s AND USER_PASSWORD = %s",
                (login_name, pw_hash),
            )
            return cur.fetchone()
    except Exception as e:
        log.warning("Login-Abfrage fehlgeschlagen: %s", e)
        return None


def _login_required(f):
    @wraps(f)
    def _wrapper(*args, **kwargs):
        if not session.get('ma_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return _wrapper


# ── Permission-Guard (Dorfkern v2, Phase 6) ──────────────────────
#
# Analog zur Orga-App: vor jedem Request pruefen wir Pfad-Prefix gegen
# Permission-Objekte. ``LESE_PFLEGE``-Objekte trennen GET (Lesen) von
# anderen Methoden (Pflegen). Bei nicht-Match faellt der Check auf
# ``admin.zugriff`` (Default-Zugriff Admin-App) zurueck.
#
# Reihenfolge: spezifische Pfade vor allgemeineren. First-match wins.
_ADMIN_PERMISSION_MAP: list[tuple[str, str]] = [
    # System (technische Wartung)
    ('/system/apps',                 'admin.system.apps'),
    ('/system/haccp-poller',         'admin.system.haccp_poller'),
    ('/system/einkauf-poller',       'admin.system.einkauf_poller'),
    ('/system/mitarbeiter',          'admin.system.mitarbeiter'),
    ('/system/updates',              'admin.system.updates'),
    ('/system/power',                'admin.system.power'),
    ('/drucker',                     'admin.system.drucker'),
    ('/api/drucker',                 'admin.system.drucker'),
    ('/terminals',                   'admin.system.terminals'),
    ('/api/terminals',               'admin.system.terminals'),
    ('/tse',                         'admin.system.tse'),
    ('/api/tse',                     'admin.system.tse'),
    ('/db-config',                   'admin.system.db_config'),
    # Dorfkern-Konfiguration
    ('/dorfkern/konfig',             'admin.dorfkern.konfig'),
    ('/dorfkern/terminals',          'admin.dorfkern.terminals'),
    ('/dorfkern/aktivierungen',      'admin.dorfkern.aktivierungen'),
    ('/rechte',                      'admin.dorfkern.rechte'),
    ('/api/rechte',                  'admin.dorfkern.rechte'),
    ('/einstellungen',               'admin.dorfkern.einstellungen'),
    ('/api/einstellungen',           'admin.dorfkern.einstellungen'),
    ('/feiertage',                   'admin.dorfkern.feiertage'),
    ('/api/feiertage',               'admin.dorfkern.feiertage'),
    ('/benachrichtigungen',          'admin.dorfkern.benachrichtigungen'),
    ('/api/benachrichtigungen',      'admin.dorfkern.benachrichtigungen'),
    ('/funktionen',                  'admin.dorfkern.funktionen'),
    ('/admin/handbuch',              'admin.dorfkern.handbuch'),
    ('/admin/doku',                  'admin.dorfkern.handbuch'),
    # Stammdaten — Mittagstisch eigenes Recht, alles andere Sammel
    ('/stammdaten/mittagstisch',     'admin.stammdaten.mittagstisch'),
    ('/api/stammdaten/mittagstisch', 'admin.stammdaten.mittagstisch'),
    ('/stammdaten',                  'admin.stammdaten'),
    ('/api/stammdaten',              'admin.stammdaten'),
    # Artikel = Backwaren-Pflege (Sidebar: Daten → 🥐 Backwaren)
    ('/artikel',                     'admin.artikel'),
    ('/api/artikel',                 'admin.artikel'),
    # Zeiten-Import (Sidebar: Daten → 📥 Zeiten-Import)
    ('/zeiten-import',               'admin.zeiten_import'),
    # /rechte/dorfkern teilt sich das Rechte-Editor-Objekt mit /rechte
    ('/rechte/dorfkern',             'admin.dorfkern.rechte'),
    # Einkauf
    ('/einkauf/oauth',               'admin.einkauf.oauth'),
    ('/api/einkauf/oauth',           'admin.einkauf.oauth'),
    ('/einkauf/bestellungen',        'admin.einkauf.bestellungen'),
    ('/api/einkauf/bestellungen',    'admin.einkauf.bestellungen'),
    ('/einkauf/lieferanten',         'admin.einkauf.lieferanten'),
    ('/api/einkauf/lieferanten',     'admin.einkauf.lieferanten'),
    ('/api/einkauf',                 'admin.einkauf.bestellungen'),
    ('/einkauf',                     'admin.einkauf.bestellungen'),
]

# Objekte mit LESE_PFLEGE-Unterscheidung. GET → LESEN, sonst → PFLEGEN.
_ADMIN_LESE_PFLEGE_KEYS = {key for _, key in _ADMIN_PERMISSION_MAP}

# Pfade ohne Permission-Check (Login, statische Ressourcen, Health).
# /produktbilder + /binaer absichtlich offen — Bilder werden vom
# Orga-/Kiosk-Frontend nachgeladen.
_ADMIN_PERMISSION_WHITELIST: tuple[str, ...] = (
    '/login', '/logout',
    '/brand/', '/static/', '/favicon',
    '/produktbilder/', '/binaer/',
    '/api/status',
    '/coming-soon',
)


def _admin_verweigern(path: str, key: str, is_basis: bool = False):
    """Berechtigung verweigert. is_basis=True → admin.zugriff fehlt,
    dann direkt zum Login (sonst Endless-Redirect aufs Dashboard,
    das selbst auch geschuetzt ist)."""
    from flask import request as _r, redirect, url_for, flash, jsonify
    if path.startswith('/api/') or \
            'application/json' in (_r.headers.get('Accept', '') or ''):
        return jsonify(ok=False,
                       msg=f'Keine Berechtigung fuer {key}'), 403
    if is_basis:
        session.clear()
        flash(f'Keine Berechtigung fuer die Admin-App ({key}). '
              f'Bitte melde dich mit einem berechtigten Konto an.',
              'error')
        return redirect(url_for('login'))
    flash(f'Keine Berechtigung ({key}).', 'error')
    try:
        return redirect(url_for('dashboard'))
    except Exception:
        return redirect('/')


@app.before_request
def _admin_permission_guard():
    path = request.path or ''
    # Whitelist (Login, Static, etc.)
    if any(path.startswith(w) for w in _ADMIN_PERMISSION_WHITELIST):
        return None
    ma_id = session.get('ma_id')
    if not ma_id:
        # Nicht eingeloggt → @_login_required leitet einzeln um.
        return None
    try:
        from common import permission as _p
    except Exception as exc:
        log.warning("Permission-Modul fehlt: %s — Guard passiv.", exc)
        return None
    is_read = request.method in ('GET', 'HEAD', 'OPTIONS')

    # Spezifische Pfade first-match
    for prefix, key in _ADMIN_PERMISSION_MAP:
        if path.startswith(prefix):
            if key in _ADMIN_LESE_PFLEGE_KEYS:
                recht = 'LESEN' if is_read else 'PFLEGEN'
            else:
                recht = 'BEIDES'
            if _p.hat_recht(ma_id, key, recht):
                return None
            return _admin_verweigern(path, f'{key} ({recht})')
    # Default: jeder angemeldete MA braucht admin.zugriff
    if _p.hat_recht(ma_id, 'admin.zugriff'):
        return None
    return _admin_verweigern(path, 'admin.zugriff', is_basis=True)


# ── Context-Processor ────────────────────────────────────────────

@app.context_processor
def _inject_globals():
    kasse_url = config.KASSE_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
        if config.KASSE_PORT else '')
    kiosk_url = config.KIOSK_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KIOSK_PORT}'
        if config.KIOSK_PORT else '')
    orga_url = config.ORGA_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.ORGA_PORT}'
        if config.ORGA_PORT else '')
    # Feature-Gating (Phase 7): deaktivierte Apps werden aus dem Switcher
    # ausgeblendet, indem die URL auf leer gesetzt wird → Template rendert
    # "app-inaktiv".
    try:
        from common import aktivierung as _akt
        if not _akt.ist_aktiv('KASSE'): kasse_url = ''
        if not _akt.ist_aktiv('KIOSK'): kiosk_url = ''
        if not _akt.ist_aktiv('ORGA'):  orga_url  = ''
    except Exception as _exc:
        log.debug("Feature-Gating uebersprungen: %s", _exc)
    return {
        "firma_name":       config.FIRMA_NAME,
        "kasse_url":        kasse_url,
        "kiosk_url":        kiosk_url,
        "orga_url":         orga_url,
        "db_ok":            test_verbindung(),
        "current_user": {
            "ma_id":      session.get('ma_id'),
            "login_name": session.get('login_name'),
            "vname":      session.get('vname'),
            "name":       session.get('ma_name'),
        } if session.get('ma_id') else None,
        "git_commit_short": GIT_COMMIT_SHORT,
    }


# ── Login / Logout ──────────────────────────────────────────────

@app.get('/login')
def login():
    if session.get('ma_id'):
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.post('/login')
def login_post():
    login_name = request.form.get('login_name', '').strip()
    passwort   = request.form.get('passwort', '')
    ma = _mitarbeiter_login(login_name, passwort)
    if ma:
        session['ma_id']      = ma['MA_ID']
        session['login_name'] = ma['LOGIN_NAME']
        session['vname']      = ma['VNAME']
        session['ma_name']    = ma['NAME']
        return redirect(url_for('dashboard'))
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.post('/login/karte')
def login_karte():
    """Login per Mitarbeiter-Karte (Barcode-Scan)."""
    guid = request.form.get('guid', '').strip()
    if not guid:
        return render_template('login.html', fehler='Kein Barcode erkannt.')
    ma = mitarbeiter_login_karte(guid)
    if ma:
        session['ma_id']      = ma['MA_ID']
        session['login_name'] = ma['LOGIN_NAME']
        session['vname']      = ma['VNAME']
        session['ma_name']    = ma['NAME']
        return redirect(url_for('dashboard'))
    return render_template('login.html',
                           fehler='Karte nicht erkannt oder keine Mitarbeiterkarte.')


@app.get('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Dashboard ────────────────────────────────────────────────────

@app.route('/')
@_login_required
def dashboard():
    return render_template('dashboard.html')


# ── Phase B: Datenbank-Zugangsdaten ─────────────────────────────

def _read_ini_config() -> dict:
    """Liest die caoxt.ini und gibt die Datenbank-Sektion zurück."""
    cfg = configparser.ConfigParser()
    cfg.read(config.INI_PATH)
    if not cfg.has_section('Datenbank'):
        return {}
    return dict(cfg.items('Datenbank'))


@app.route('/db-config')
@_login_required
def db_config():
    ini = _read_ini_config()
    return render_template('db_config.html', ini=ini)


@app.post('/db-config')
@_login_required
def db_config_save():
    cfg = configparser.ConfigParser()
    cfg.read(config.INI_PATH)
    if not cfg.has_section('Datenbank'):
        cfg.add_section('Datenbank')
    cfg.set('Datenbank', 'db_loc',  request.form.get('db_loc', '').strip())
    cfg.set('Datenbank', 'db_port', request.form.get('db_port', '3306').strip())
    cfg.set('Datenbank', 'db_name', request.form.get('db_name', '').strip())
    cfg.set('Datenbank', 'db_user', request.form.get('db_user', '').strip())
    pw = request.form.get('db_pass', '').strip()
    if pw:
        cfg.set('Datenbank', 'db_pass', pw)
    try:
        with open(config.INI_PATH, 'w') as f:
            cfg.write(f)
        log.info("caoxt.ini aktualisiert durch %s", session.get('login_name'))
        # In-Memory-Config und DB-Pool mit neuen Werten neu laden
        config.reload_db_config()
        reset_pool()
        # Migrationen erneut versuchen (beim Start evtl. fehlgeschlagen)
        _migrationen_ausfuehren()
        return jsonify(ok=True, msg='Konfiguration gespeichert.')
    except Exception as e:
        log.error("caoxt.ini schreiben fehlgeschlagen: %s", e)
        return jsonify(ok=False, msg=f'Fehler: {e}'), 500


@app.post('/db-config/test')
@_login_required
def db_config_test():
    """Testet die aktuelle DB-Verbindung."""
    ok = test_verbindung(force=True)
    return jsonify(ok=ok, msg='Verbindung erfolgreich.' if ok else 'Verbindung fehlgeschlagen.')


# ── Phase C: Bondrucker-Admin ──────────────────────────────

@app.route('/drucker')
@_login_required
def drucker():
    return render_template('drucker.html')


@app.get('/api/drucker')
@_login_required
def api_drucker_list():
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM XT_DRUCKER_CONFIG ORDER BY terminal_nr")
            return jsonify(ok=True, drucker=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/drucker')
@_login_required
def api_drucker_create():
    d = request.get_json(force=True)
    try:
        with get_db() as cur:
            cur.execute(
                "INSERT INTO XT_DRUCKER_CONFIG (terminal_nr, ip_adresse, port, bezeichnung) "
                "VALUES (%s, %s, %s, %s)",
                (d['terminal_nr'], d['ip_adresse'], d.get('port', 9100), d.get('bezeichnung', '')),
            )
        return jsonify(ok=True, msg='Drucker angelegt.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.put('/api/drucker/<int:drucker_id>')
@_login_required
def api_drucker_update(drucker_id):
    d = request.get_json(force=True)
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE XT_DRUCKER_CONFIG SET terminal_nr=%s, ip_adresse=%s, port=%s, bezeichnung=%s "
                "WHERE id=%s",
                (d['terminal_nr'], d['ip_adresse'], d.get('port', 9100), d.get('bezeichnung', ''), drucker_id),
            )
        return jsonify(ok=True, msg='Drucker aktualisiert.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.delete('/api/drucker/<int:drucker_id>')
@_login_required
def api_drucker_delete(drucker_id):
    try:
        with get_db() as cur:
            cur.execute("DELETE FROM XT_DRUCKER_CONFIG WHERE id=%s", (drucker_id,))
        return jsonify(ok=True, msg='Drucker gelöscht.')
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/drucker/<int:drucker_id>/test')
@_login_required
def api_drucker_test(drucker_id):
    """Socket-Ping auf den Drucker (Verbindungstest)."""
    try:
        with get_db() as cur:
            cur.execute("SELECT ip_adresse, port FROM XT_DRUCKER_CONFIG WHERE id=%s", (drucker_id,))
            row = cur.fetchone()
        if not row:
            return jsonify(ok=False, msg='Drucker nicht gefunden.'), 404
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((row['ip_adresse'], row['port']))
        s.close()
        if result == 0:
            return jsonify(ok=True, msg=f"Verbindung zu {row['ip_adresse']}:{row['port']} erfolgreich.")
        return jsonify(ok=False, msg=f"Keine Verbindung zu {row['ip_adresse']}:{row['port']}.")
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase D: Terminal-Admin ────────────────────────────────

@app.route('/terminals')
@_login_required
def terminals():
    return render_template('terminals.html')


@app.route('/terminals/<int:terminal_nr>')
@_login_required
def terminal_detail(terminal_nr):
    """Vollstaendige Terminal-Konfiguration. Loest die fruehere
    /admin/terminal-Seite der Kasse-App ab (Brand-Light-Look)."""
    return render_template('terminal_detail.html', terminal_nr=terminal_nr)


@app.get('/api/terminals')
@_login_required
def api_terminals_list():
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM XT_KASSE_TERMINALS ORDER BY TERMINAL_NR")
            return jsonify(ok=True, terminals=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.get('/api/terminals/<int:terminal_nr>')
@_login_required
def api_terminal_einzeln(terminal_nr):
    """Liefert die komplette Konfig eines Terminals fuer die Detail-Seite."""
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR=%s",
                        (terminal_nr,))
            row = cur.fetchone()
        if not row:
            return jsonify(ok=False, msg='Terminal nicht gefunden.'), 404
        return jsonify(ok=True, terminal=row)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# Whitelist: Felder, die ueber die zentrale Admin-API gepflegt werden.
# TSE-bezogene Felder (TSE_ID, FISKALY_*, SWISSBIT_PFAD) liegen in /tse,
# nicht hier – die nicht-TSE-Konfig wandert komplett aus der Kasse-App in
# die Admin-App.
_TERMINAL_TEXT_FELDER = (
    'BEZEICHNUNG', 'FIRMA_NAME', 'FIRMA_ZUSATZ',
    'DRUCKER_IP',
    'KONTO_BANK', 'KONTO_NEBENKASSE',
    'KONTO_KASSENDIFF_AUFWAND', 'KONTO_KASSENDIFF_ERTRAG',
    'EC_TERMINAL_IP', 'EC_ZVT_PASSWORT',
)
_TERMINAL_INT_FELDER = (
    'DRUCKER_PORT', 'KASSENLADE',
    'SOFORT_DRUCKEN', 'SCHUBLADE_AUTO_OEFFNEN', 'QR_CODE',
    'TRAININGS_MODUS',
    'EC_TERMINAL_PORT',
)
_TERMINAL_ENUM_FELDER = {
    'EC_MODUS':          ('manuell', 'zvt'),
    'EC_TAGESABSCHLUSS': ('manuell', 'auto', 'auto_vergleich'),
}


@app.put('/api/terminals/<int:terminal_nr>')
@_login_required
def api_terminal_update(terminal_nr):
    """Aktualisiert die Terminal-Konfig. Akzeptiert *eine Teilmenge* der
    Felder als JSON; alle nicht uebergebenen Felder bleiben unveraendert.
    Whitelist-basiert (TSE-Felder werden ignoriert).
    """
    d = request.get_json(force=True) or {}
    setze: list[tuple[str, object]] = []
    for feld in _TERMINAL_TEXT_FELDER:
        key = feld.lower()
        if key in d:
            wert = d[key]
            setze.append((feld, (wert.strip() if isinstance(wert, str) else wert) or None))
    for feld in _TERMINAL_INT_FELDER:
        key = feld.lower()
        if key in d:
            try:
                setze.append((feld, int(d[key]) if d[key] not in ('', None) else 0))
            except (ValueError, TypeError):
                return jsonify(ok=False,
                               msg=f'{feld} muss ganzzahlig sein.'), 400
    for feld, gueltige in _TERMINAL_ENUM_FELDER.items():
        key = feld.lower()
        if key in d:
            wert = (d[key] or '').strip()
            if wert not in gueltige:
                return jsonify(ok=False,
                               msg=f'{feld} muss eines von {gueltige} sein.'), 400
            setze.append((feld, wert))
    if not setze:
        return jsonify(ok=False, msg='Keine Aenderungen.'), 400
    sql = ("UPDATE XT_KASSE_TERMINALS SET "
           + ", ".join(f"{feld}=%s" for feld, _ in setze)
           + " WHERE TERMINAL_NR=%s")
    werte = [w for _, w in setze] + [terminal_nr]
    try:
        with get_db() as cur:
            cur.execute(sql, werte)
            if cur.rowcount == 0:
                # Kein UPDATE -> Eintrag fehlt; Insert mit den uebergebenen Feldern.
                cols = [feld for feld, _ in setze]
                cur.execute(
                    f"INSERT INTO XT_KASSE_TERMINALS (TERMINAL_NR, {', '.join(cols)}) "
                    f"VALUES (%s, {', '.join(['%s']*len(cols))})",
                    [terminal_nr] + [w for _, w in setze]
                )
        return jsonify(ok=True, msg='Terminal aktualisiert.',
                       felder=[f for f, _ in setze])
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/terminals/<int:terminal_nr>/drucker/test')
@_login_required
def api_terminal_drucker_test(terminal_nr):
    """Sendet eine kleine ESC/POS-Testseite an den Bondrucker des Terminals.
    Frueher in kasse-app/.../admin_drucker_test – jetzt zentral in Admin,
    damit alle Terminal-Tests aus dem Admin-Backoffice ausgeloest werden
    koennen, nicht nur vom Kassen-Terminal selbst.
    """
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT DRUCKER_IP, DRUCKER_PORT FROM XT_KASSE_TERMINALS "
                "WHERE TERMINAL_NR=%s", (terminal_nr,))
            row = cur.fetchone()
        if not row or not row.get('DRUCKER_IP'):
            return jsonify(ok=False,
                           msg='Keine Drucker-IP konfiguriert.'), 400
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((row['DRUCKER_IP'], int(row.get('DRUCKER_PORT') or 9100)))
        sock.sendall(
            b'\x1b\x40'                # Reset
            b'\x1b\x61\x01'            # zentriert
            b'\x1b\x45\x01'            # Fett
            b'CAO-XT Admin-App\n'
            b'\x1b\x45\x00'
            b'Druckertest Terminal '
            + str(terminal_nr).encode() + b'\n'
            b'\n\n\n\n\n\n'
            b'\x1d\x56\x01'            # Schnitt
        )
        sock.close()
        return jsonify(ok=True, msg='Testseite gesendet.')
    except Exception as e:
        return jsonify(ok=False, msg=f'Drucker nicht erreichbar: {e}'), 502


# ── Phase D: TSE-Admin ─────────────────────────────────────

@app.route('/tse')
@_login_required
def tse():
    return render_template('tse.html')


@app.get('/api/tse')
@_login_required
def api_tse_list():
    """TSE-Geräte aus XT_KASSE_TSE_GERAETE mit zugeordneten Terminals."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT g.*,
                       GROUP_CONCAT(t.TERMINAL_NR ORDER BY t.TERMINAL_NR) AS TERMINAL_NRS
                  FROM XT_KASSE_TSE_GERAETE g
                  LEFT JOIN XT_KASSE_TERMINALS t ON t.TSE_ID = g.REC_ID
                 GROUP BY g.REC_ID
                 ORDER BY g.REC_ID DESC
            """)
            return jsonify(ok=True, geraete=cur.fetchall())
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase E: Backwaren/Artikel-Admin ───────────────────────

# Produktbilder-Verzeichnis: standardmäßig im kiosk-app/app/produktbilder/.
# Beide Apps (Kiosk zur Anzeige, Admin zum Verwalten) greifen auf dasselbe Verzeichnis zu.
PRODUKTBILDER_DIR = os.environ.get('PRODUKTBILDER_DIR') or os.path.join(
    BASE_DIR, '..', '..', 'kiosk-app', 'app', 'produktbilder')
PRODUKTBILDER_DIR = os.path.abspath(PRODUKTBILDER_DIR)
ERLAUBTE_BILD_ENDUNGEN = {"jpg", "jpeg", "png", "webp"}
MAX_BILD_GROESSE = 5 * 1024 * 1024  # 5 MB


def _cent_zu_euro_str(cent: int) -> str:
    """Hilfsfunktion für Template-Formatierung."""
    return f"{cent / 100:.2f} €"


@app.route('/artikel')
@_login_required
def artikel():
    with get_db() as cur:
        cur.execute("SELECT * FROM XT_KIOSK_V_ARTIKEL_VERWALTUNG")
        artikel_liste = cur.fetchall()
        cur.execute("SELECT * FROM XT_KIOSK_KATEGORIEN ORDER BY sort_order")
        kategorien = cur.fetchall()
    return render_template(
        'artikel.html',
        artikel=artikel_liste,
        kategorien=kategorien,
        cent_zu_euro=_cent_zu_euro_str,
    )


@app.route('/artikel/<int:artikel_id>', methods=['POST'])
@_login_required
def artikel_speichern(artikel_id):
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify(ok=False, msg='Keine Daten empfangen'), 400
    try:
        with get_db() as cur:
            # vorlaufzeit_tage: 0..14, sonst auf 0 normalisieren
            try:
                vorlauf = int(data.get("vorlaufzeit_tage", 0) or 0)
            except (TypeError, ValueError):
                vorlauf = 0
            if vorlauf < 0 or vorlauf > 14:
                vorlauf = 0
            cur.execute("SELECT id FROM XT_KIOSK_PRODUKTE WHERE id=%s", (artikel_id,))
            exists = cur.fetchone()
            if exists:
                cur.execute(
                    """UPDATE XT_KIOSK_PRODUKTE
                       SET kategorie_id=%s, einheit=%s, wochentage=%s,
                           zutaten=%s, aktiv=%s, hinweis=%s,
                           vorlaufzeit_tage=%s
                       WHERE id=%s""",
                    (data.get("kategorie_id"), data.get("einheit", "Stck."),
                     data.get("wochentage", ""), data.get("zutaten"),
                     data.get("aktiv", 1), data.get("hinweis"),
                     vorlauf, artikel_id))
            else:
                cur.execute(
                    """INSERT INTO XT_KIOSK_PRODUKTE
                       (id, kategorie_id, einheit, wochentage, zutaten, aktiv, hinweis,
                        vorlaufzeit_tage)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (artikel_id, data.get("kategorie_id"), data.get("einheit", "Stck."),
                     data.get("wochentage", ""), data.get("zutaten"),
                     data.get("aktiv", 1), data.get("hinweis"),
                     vorlauf))
    except Exception as e:
        log.error("artikel_speichern ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True)


@app.route('/artikel/<int:artikel_id>/bild', methods=['POST'])
@_login_required
def artikel_bild_hochladen(artikel_id):
    """Bild für einen Artikel hochladen."""
    datei = request.files.get('bild')
    if not datei or not datei.filename:
        return jsonify(ok=False, msg='Keine Datei ausgewählt'), 400
    endung = datei.filename.rsplit('.', 1)[-1].lower() if '.' in datei.filename else ''
    if endung not in ERLAUBTE_BILD_ENDUNGEN:
        return jsonify(ok=False, msg=f"Nur {', '.join(sorted(ERLAUBTE_BILD_ENDUNGEN))} erlaubt"), 400
    datei.seek(0, 2)
    if datei.tell() > MAX_BILD_GROESSE:
        return jsonify(ok=False, msg='Datei zu groß (max. 5 MB)'), 400
    datei.seek(0)

    # Bytes lesen (fuer BINAERDATEN-BLOB UND legacy-Filesystem-Cache).
    daten_bytes = datei.read()
    dateiname = f"{artikel_id}.{endung}"

    # Primaer-Bild in CAO BINAERDATEN ablegen (MODUL_ID=1020 Artikel).
    # Damit ist es sofort im CAO-Faktura-Artikelstamm-Reiter
    # "Dateilinks" sichtbar.
    from common import binaerdaten as _bd
    try:
        _bd.run_migration()  # idempotent: stellt Standard-Typ sicher
        typ_id = _bd.typ_id_holen(_bd.TYP_NAME_PRODUKTBILD)
        binaer_id = _bd.binaer_primaer_ersetzen(
            modul_id=_bd.MODUL_ID_ARTIKEL,
            referenz_id=int(artikel_id),
            binaer_typ=typ_id,
            pfad=f'/produktbilder/{dateiname}',
            datei=dateiname,
            daten=daten_bytes,
            erst_name=session.get('login_name') or 'admin-app',
        )
    except Exception as e:
        log.error("Bild-BINAERDATEN-Insert ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    bild_url_pfad = f"/binaer/{binaer_id}"

    # Legacy-Filesystem-Cache parallel pflegen (best-effort, damit
    # bestehende Setups ohne BINAERDATEN-Endpoint weiterlaufen).
    try:
        os.makedirs(PRODUKTBILDER_DIR, exist_ok=True)
        for alt_endung in ERLAUBTE_BILD_ENDUNGEN:
            alt_pfad = os.path.join(PRODUKTBILDER_DIR,
                                     f"{artikel_id}.{alt_endung}")
            if os.path.exists(alt_pfad):
                os.remove(alt_pfad)
        with open(os.path.join(PRODUKTBILDER_DIR, dateiname), 'wb') as fh:
            fh.write(daten_bytes)
    except Exception as fs_exc:
        log.warning("Bild-FS-Cache best-effort ID=%s: %s",
                    artikel_id, fs_exc)

    try:
        with get_db() as cur:
            cur.execute("SELECT id FROM XT_KIOSK_PRODUKTE WHERE id=%s", (artikel_id,))
            if cur.fetchone():
                cur.execute("UPDATE XT_KIOSK_PRODUKTE SET bild_pfad=%s WHERE id=%s",
                            (bild_url_pfad, artikel_id))
            else:
                cur.execute("INSERT INTO XT_KIOSK_PRODUKTE (id, bild_pfad, aktiv) VALUES (%s, %s, 1)",
                            (artikel_id, bild_url_pfad))
    except Exception as e:
        log.error("Bild-DB-Update ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, bild_url=bild_url_pfad)


@app.route('/artikel/<int:artikel_id>/bild', methods=['DELETE'])
@_login_required
def artikel_bild_loeschen(artikel_id):
    """Bild eines Artikels löschen.

    Entfernt das Hauptbild aus CAO ``BINAERDATEN`` (MODUL_ID=1020),
    aus dem Filesystem-Cache und setzt ``XT_KIOSK_PRODUKTE.bild_pfad``
    auf NULL.
    """
    geloescht = False
    # 1) BINAERDATEN-Hauptbild loeschen (MODUL_ID=1020 = Artikel).
    try:
        from common import binaerdaten as _bd
        n = _bd.binaer_primaer_loeschen(
            _bd.MODUL_ID_ARTIKEL, int(artikel_id))
        if n:
            geloescht = True
    except Exception as exc:
        log.warning("BINAERDATEN-Delete ID=%s: %s", artikel_id, exc)
    # 2) Legacy-Filesystem-Cache leeren.
    for endung in ERLAUBTE_BILD_ENDUNGEN:
        pfad = os.path.join(PRODUKTBILDER_DIR, f"{artikel_id}.{endung}")
        if os.path.exists(pfad):
            os.remove(pfad)
            geloescht = True
    # 3) bild_pfad in der Kiosk-Tabelle nullen.
    try:
        with get_db() as cur:
            cur.execute("UPDATE XT_KIOSK_PRODUKTE SET bild_pfad=NULL WHERE id=%s", (artikel_id,))
    except Exception as e:
        log.error("Bild-löschen DB ID=%s: %s", artikel_id, e)
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, geloescht=geloescht)


@app.route('/artikel/bereinigen', methods=['POST'])
@_login_required
def artikel_bereinigen():
    """Verwaiste Kiosk-Produkte (ohne CAO-Artikel) entfernen."""
    with get_db() as cur:
        cur.execute("SELECT id FROM XT_KIOSK_V_VERWAISTE")
        ids = [r['id'] for r in cur.fetchall()]
        geloescht = 0
        for pid in ids:
            try:
                cur.execute("DELETE FROM XT_KIOSK_PRODUKTE WHERE id=%s", (pid,))
                geloescht += 1
            except Exception:
                pass
    return jsonify(ok=True, geloescht=geloescht)


@app.route('/produktbilder/<path:dateiname>')
def produktbild(dateiname):
    """Liefert Produktbilder (für Vorschau in der Admin)."""
    from flask import send_from_directory
    return send_from_directory(PRODUKTBILDER_DIR, dateiname)


@app.route('/binaer/<int:rec_id>')
def binaerdaten_blob(rec_id: int):
    """Liefert einen BLOB aus CAO ``BINAERDATEN`` (Bilder, PDFs, …).

    Honoriert ``If-None-Match`` für Browser-Caching, damit das BLOB
    nicht bei jedem Aufruf erneut über die Leitung geht.
    """
    from flask import request as _req, Response, abort
    from common import binaerdaten as _bd
    etag = f'binaer-{rec_id}'
    if (_req.headers.get('If-None-Match') or '') == etag:
        return ('', 304, {'ETag': etag,
                          'Cache-Control': 'public, max-age=86400'})
    row = _bd.binaer_holen(rec_id)
    if not row or not row.get('DATEN'):
        abort(404)
    mime = _bd.mime_aus_dateiname(row.get('DATEI') or '')
    return Response(
        bytes(row['DATEN']),
        mimetype=mime,
        headers={
            'Content-Length': str(len(row['DATEN'])),
            'ETag': etag,
            'Cache-Control': 'public, max-age=86400',
        },
    )


# ── Phase F: Funktionen (Feature-Toggles) ─────────────────────────

@app.route('/funktionen')
@_login_required
def funktionen():
    return render_template('funktionen.html')


@app.get('/api/einstellungen')
@_login_required
def api_einstellungen_list():
    """Gibt alle Einstellungen als Dict zurück."""
    try:
        with get_db() as cur:
            cur.execute("SELECT schluessel, wert, beschreibung FROM XT_EINSTELLUNGEN")
            rows = cur.fetchall()
        return jsonify(ok=True, einstellungen={r['schluessel']: r for r in rows})
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.put('/api/einstellungen/<schluessel>')
@_login_required
def api_einstellung_setzen(schluessel: str):
    """Setzt eine Einstellung. Body: { "wert": "1" }"""
    d = request.get_json(force=True)
    wert = str(d.get('wert', ''))
    benutzer = session.get('login_name', '')
    try:
        with get_db() as cur:
            # Validierung: Parken kann nur deaktiviert werden, wenn kein Bon geparkt ist
            if schluessel == 'kiosk_parken_aktiv' and wert == '0':
                cur.execute(
                    "SELECT COUNT(*) AS n FROM XT_KIOSK_WARENKOERBE WHERE status='geparkt'"
                )
                if cur.fetchone()['n'] > 0:
                    return jsonify(ok=False,
                                   msg='Kann nicht deaktiviert werden: Es gibt noch geparkte Warenkörbe.'), 409
            if schluessel == 'kasse_parken_aktiv' and wert == '0':
                cur.execute(
                    "SELECT COUNT(*) AS n FROM XT_KASSE_VORGAENGE WHERE STATUS='GEPARKT'"
                )
                if cur.fetchone()['n'] > 0:
                    return jsonify(ok=False,
                                   msg='Kann nicht deaktiviert werden: Es gibt noch geparkte Bons.'), 409
            cur.execute(
                "UPDATE XT_EINSTELLUNGEN SET wert=%s, geaendert_von=%s WHERE schluessel=%s",
                (wert, benutzer, schluessel),
            )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Phase G: Feiertage (Personal-Modul) ──────────────────────────
#
# Verwaltet XT_PERSONAL_FEIERTAG (gesetzlich via holidays-Paket + manuell).
# Das aktive Bundesland liegt in XT_EINSTELLUNGEN.personal_bundesland.
#

BUNDESLAENDER = (
    ('BW', 'Baden-Wuerttemberg'), ('BY', 'Bayern'), ('BE', 'Berlin'),
    ('BB', 'Brandenburg'),        ('HB', 'Bremen'),  ('HH', 'Hamburg'),
    ('HE', 'Hessen'),             ('MV', 'Mecklenburg-Vorpommern'),
    ('NI', 'Niedersachsen'),      ('NW', 'Nordrhein-Westfalen'),
    ('RP', 'Rheinland-Pfalz'),    ('SL', 'Saarland'),
    ('SN', 'Sachsen'),            ('ST', 'Sachsen-Anhalt'),
    ('SH', 'Schleswig-Holstein'), ('TH', 'Thueringen'),
)


def _aktuelles_bundesland() -> str:
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT wert FROM XT_EINSTELLUNGEN WHERE schluessel='personal_bundesland'"
            )
            row = cur.fetchone()
            if row and row.get('wert'):
                return str(row['wert']).strip().upper()
    except Exception:
        pass
    return 'BY'


@app.route('/feiertage')
@_login_required
def feiertage():
    jahr_str = request.args.get('jahr', '')
    try:
        jahr = int(jahr_str) if jahr_str else datetime.now().year
    except (TypeError, ValueError):
        jahr = datetime.now().year
    bundesland = _aktuelles_bundesland()
    eintraege = []
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_AT
                     FROM XT_PERSONAL_FEIERTAG
                    WHERE YEAR(DATUM) = %s AND BUNDESLAND IN (%s, 'BUND')
                    ORDER BY DATUM, QUELLE='manuell' DESC, REC_ID""",
                (int(jahr), bundesland),
            )
            eintraege = cur.fetchall() or []
    except Exception as e:
        log.warning("Feiertage laden fehlgeschlagen: %s", e)
    return render_template(
        'feiertage.html',
        jahr=jahr,
        bundesland=bundesland,
        bundeslaender=BUNDESLAENDER,
        eintraege=eintraege,
    )


@app.post('/api/feiertage/bundesland')
@_login_required
def api_feiertage_bundesland():
    """Setzt das aktive Bundesland."""
    d = request.get_json(force=True)
    neu = str(d.get('bundesland', '')).strip().upper()
    if neu not in {k for k, _ in BUNDESLAENDER}:
        return jsonify(ok=False, msg='Unbekanntes Bundesland.'), 400
    benutzer = session.get('login_name', '')
    try:
        with get_db() as cur:
            cur.execute(
                "UPDATE XT_EINSTELLUNGEN SET wert=%s, geaendert_von=%s "
                " WHERE schluessel='personal_bundesland'",
                (neu, benutzer),
            )
        return jsonify(ok=True, bundesland=neu)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/feiertage/sync')
@_login_required
def api_feiertage_sync():
    """Synchronisiert gesetzliche Feiertage aus dem holidays-Paket fuer
    (jahr, aktuelles_bundesland). INSERT IGNORE – vorhandene Eintraege
    bleiben unveraendert."""
    d = request.get_json(force=True) or {}
    try:
        jahr = int(d.get('jahr') or datetime.now().year)
    except (TypeError, ValueError):
        return jsonify(ok=False, msg='Ungueltige Jahresangabe.'), 400
    bundesland = _aktuelles_bundesland()
    try:
        import holidays
    except ImportError:
        return jsonify(ok=False,
                       msg='Python-Paket "holidays" nicht installiert.'), 500
    try:
        try:
            kal = holidays.country_holidays('DE', subdiv=bundesland, years=jahr)
        except Exception:
            kal = holidays.country_holidays('DE', years=jahr)
        eingefuegt = 0
        with get_db_transaction() as cur:
            for tag, name in sorted(kal.items()):
                cur.execute(
                    """INSERT IGNORE INTO XT_PERSONAL_FEIERTAG
                         (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
                       VALUES (%s, %s, %s, 'paket', NULL)""",
                    (tag, str(name), bundesland),
                )
                eingefuegt += cur.rowcount
        return jsonify(ok=True, eingefuegt=eingefuegt, jahr=jahr, bundesland=bundesland)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/feiertage/manuell')
@_login_required
def api_feiertag_manuell_anlegen():
    """Legt einen manuellen Feiertag an. Body: {datum, name}"""
    d = request.get_json(force=True) or {}
    datum = str(d.get('datum', '')).strip()
    name = str(d.get('name', '')).strip()
    if not datum or not name:
        return jsonify(ok=False, msg='Datum und Name erforderlich.'), 400
    try:
        datetime.strptime(datum, '%Y-%m-%d')
    except ValueError:
        return jsonify(ok=False, msg='Datum im Format JJJJ-MM-TT angeben.'), 400
    bundesland = _aktuelles_bundesland()
    ma_id = session.get('ma_id') or 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                """INSERT INTO XT_PERSONAL_FEIERTAG
                     (DATUM, NAME, BUNDESLAND, QUELLE, ERSTELLT_VON)
                   VALUES (%s, %s, %s, 'manuell', %s)""",
                (datum, name, bundesland, int(ma_id)),
            )
        return jsonify(ok=True)
    except Exception as e:
        # Duplikat via UNIQUE-Key ist der haeufigste Fehler
        return jsonify(ok=False, msg=str(e)), 400


@app.delete('/api/feiertage/<int:rec_id>')
@_login_required
def api_feiertag_loeschen(rec_id: int):
    """Loescht einen manuellen Feiertag. Paket-Eintraege lassen sich
    so nicht entfernen (re-Sync wuerde sie ohnehin wiederherstellen)."""
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM XT_PERSONAL_FEIERTAG "
                " WHERE REC_ID=%s AND QUELLE='manuell'",
                (int(rec_id),),
            )
            anz = cur.rowcount
        if not anz:
            return jsonify(ok=False,
                           msg='Nicht gefunden oder kein manueller Eintrag.'), 404
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Benachrichtigungs-Empfaenger (E-Mails fuer Hinweis-Hooks) ────────

# Bereiche, fuer die aktuell Hinweis-Mails verschickt werden. Ergaenzend
# hinzufuegen, sobald eine neue Benachrichtigungs-Kategorie auftaucht.
BENACHRICHTIGUNG_BEREICHE: tuple[tuple[str, str], ...] = (
    ('abwesenheit_antrag',  'Abwesenheit: neuer Antrag vom MA'),
    ('urlaub_antrag',       'Urlaub: neuer Antrag vom MA'),
)


def _benachrichtigung_bereich_ok(bereich: str) -> bool:
    return bereich in {k for k, _ in BENACHRICHTIGUNG_BEREICHE}


@app.get('/benachrichtigungen')
@_login_required
def benachrichtigungen():
    eintraege = []
    try:
        with get_db() as cur:
            cur.execute(
                """SELECT REC_ID, BEREICH, EMAIL, NAME, AKTIV, ERSTELLT_AT
                     FROM XT_BENACHRICHTIGUNG_EMPFAENGER
                    ORDER BY BEREICH, EMAIL"""
            )
            eintraege = cur.fetchall() or []
    except Exception as e:
        log.warning("Benachrichtigungs-Empfaenger laden fehlgeschlagen: %s", e)
    return render_template(
        'benachrichtigungen.html',
        bereiche=BENACHRICHTIGUNG_BEREICHE,
        eintraege=eintraege,
    )


@app.post('/api/benachrichtigungen')
@_login_required
def api_benachrichtigung_anlegen():
    d = request.get_json(force=True) or {}
    bereich = str(d.get('bereich', '')).strip()
    email = str(d.get('email', '')).strip()
    name = str(d.get('name', '')).strip() or None
    if not _benachrichtigung_bereich_ok(bereich):
        return jsonify(ok=False, msg='Unbekannter Bereich.'), 400
    if '@' not in email or len(email) > 150:
        return jsonify(ok=False, msg='Ungueltige E-Mail-Adresse.'), 400
    ma_id = session.get('ma_id') or 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                """INSERT INTO XT_BENACHRICHTIGUNG_EMPFAENGER
                     (BEREICH, EMAIL, NAME, ERSTELLT_VON)
                   VALUES (%s, %s, %s, %s)""",
                (bereich, email, name, int(ma_id) if ma_id else None),
            )
        return jsonify(ok=True)
    except Exception as e:
        # UNIQUE (BEREICH, EMAIL) ist der haeufige Fehlerfall
        return jsonify(ok=False, msg=str(e)), 400


@app.post('/api/benachrichtigungen/<int:rec_id>/aktiv')
@_login_required
def api_benachrichtigung_aktiv(rec_id: int):
    """Toggelt den AKTIV-Schalter eines Empfaengers."""
    d = request.get_json(force=True) or {}
    aktiv = 1 if d.get('aktiv') else 0
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "UPDATE XT_BENACHRICHTIGUNG_EMPFAENGER SET AKTIV=%s "
                " WHERE REC_ID=%s",
                (aktiv, int(rec_id)),
            )
            if cur.rowcount == 0:
                return jsonify(ok=False, msg='Nicht gefunden.'), 404
        return jsonify(ok=True, aktiv=aktiv)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.delete('/api/benachrichtigungen/<int:rec_id>')
@_login_required
def api_benachrichtigung_loeschen(rec_id: int):
    try:
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM XT_BENACHRICHTIGUNG_EMPFAENGER WHERE REC_ID=%s",
                (int(rec_id),),
            )
            if cur.rowcount == 0:
                return jsonify(ok=False, msg='Nicht gefunden.'), 404
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


# ── Handbuch ─────────────────────────────────────────────────────

@app.get('/admin/doku/<path:dateiname>')
@_login_required
def admin_doku_datei(dateiname):
    """Statische Dateien aus dem doku/-Verzeichnis (Bilder für Handbuch)."""
    return send_from_directory(os.path.abspath(_DOKU_DIR), dateiname)


@app.get('/admin/handbuch')
@_login_required
def admin_handbuch():
    """Mitarbeiter-Handbuch – alle eingeloggten User dürfen lesen,
    Administratoren dürfen bearbeiten."""
    pfad = os.path.join(_DOKU_DIR, 'handbuch.html')
    try:
        with open(pfad, encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        return 'Handbuch nicht gefunden.', 404
    ist_admin = bool(session.get('admin') or session.get('ma_id'))
    inject = (f'<script id="hb-inject">'
              f'window.HANDBUCH_ADMIN = {"true" if ist_admin else "false"};'
              f'</script>\n')
    html = html.replace('</head>', inject + '</head>', 1)
    return html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.post('/admin/handbuch/speichern')
@_login_required
def admin_handbuch_speichern():
    """Speichert das bearbeitete Handbuch. Backup der alten Version wird angelegt."""
    data = request.get_json(force=True) or {}
    html = data.get('html', '').strip()
    if not html:
        return jsonify({'ok': False, 'fehler': 'Kein Inhalt'}), 400
    pfad   = os.path.join(_DOKU_DIR, 'handbuch.html')
    backup = pfad + '.bak'
    try:
        if os.path.exists(pfad):
            with open(pfad, 'rb') as f_in, open(backup, 'wb') as f_bak:
                f_bak.write(f_in.read())
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write(html)
    except OSError as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 500
    return jsonify({'ok': True})


@app.post('/admin/handbuch/upload')
@_login_required
def admin_handbuch_upload():
    """Speichert ein hochgeladenes Bild im doku/-Verzeichnis."""
    data      = request.get_json(force=True) or {}
    dateiname = os.path.basename(data.get('filename', ''))
    b64data   = data.get('data', '')
    if not dateiname or not b64data:
        return jsonify({'ok': False, 'fehler': 'filename oder data fehlt'}), 400
    if ',' in b64data:
        b64data = b64data.split(',', 1)[1]
    try:
        bild_bytes = base64.b64decode(b64data)
        ziel = os.path.join(_DOKU_DIR, dateiname)
        with open(ziel, 'wb') as f:
            f.write(bild_bytes)
    except Exception as e:
        return jsonify({'ok': False, 'fehler': str(e)}), 500
    return jsonify({'ok': True, 'filename': f'/admin/doku/{dateiname}'})


# ── System: CAO-Rechte (read-only) ──────────────────────────────

@app.route('/rechte')
@_login_required
def rechte_seite():
    """Read-only Uebersicht der CAO-BENUTZERRECHTE.

    Pflege ausschliesslich in cao_admin.exe. Die Ansicht zeigt
    Gruppen, Modul-Baum mit Rechte-Bits und User-Zuordnungen/Overrides.
    """
    import cao_rechte as _cr
    return render_template('rechte.html',
                           gruppen=_cr.gruppen_laden())


@app.get('/api/rechte/baum')
@_login_required
def api_rechte_baum():
    """Modul-Baum fuer eine Gruppe (query-param ``gruppe``)."""
    import cao_rechte as _cr
    try:
        gruppe_id = int(request.args.get('gruppe', '0'))
    except ValueError:
        return jsonify(ok=False, msg='Ungueltige gruppe'), 400
    baum = _cr.modul_baum(gruppe_id)
    # Bits pro Eintrag aufloesen, damit das Template simpel bleibt.
    for kat in baum:
        for modul in kat['module']:
            modul['bits'] = _cr.rechte_zu_bits(modul['rechte'],
                                               modul['modul_id'], 0)
            for sub in modul['submodule']:
                sub['bits'] = _cr.rechte_zu_bits(sub['rechte'],
                                                 sub['modul_id'],
                                                 sub['submodul_id'])
    return jsonify(ok=True, baum=baum)


@app.get('/api/rechte/benutzer')
@_login_required
def api_rechte_benutzer():
    """Mitarbeiter-Liste mit Gruppen-Zuordnung."""
    import cao_rechte as _cr
    return jsonify(ok=True, benutzer=_cr.mitarbeiter_mit_gruppen())


@app.get('/api/rechte/benutzer/<int:ma_id>/overrides')
@_login_required
def api_rechte_benutzer_overrides(ma_id: int):
    """User-spezifische Rechte-Overrides."""
    import cao_rechte as _cr
    overrides = _cr.benutzer_overrides(ma_id)
    for o in overrides:
        o['bits'] = _cr.rechte_zu_bits(o['rechte'], o['modul_id'],
                                       o['submodul_id'])
    return jsonify(ok=True, overrides=overrides)


# ── System: CAO-Einstellungen (read-only) ───────────────────────

@app.route('/einstellungen')
@_login_required
def einstellungen_seite():
    """Read-only Uebersicht der CAO-REGISTRY (Anwendungseinstellungen).

    Pflege ausschliesslich in cao_admin.exe (Menue „Einstellungen").
    Die Ansicht gruppiert nach MAINKEY-Kategorien und listet je Eintrag
    Wert, Typ sowie die Flags CACHABLE/READONLY.
    """
    return render_template('einstellungen.html')


@app.get('/api/einstellungen/registry')
@_login_required
def api_einstellungen_registry():
    """REGISTRY-Eintraege, nach Kategorie gruppiert."""
    import cao_einstellungen as _ce
    try:
        kategorien = _ce.gruppiert_nach_kategorie()
        return jsonify(ok=True, kategorien=kategorien)
    except Exception as e:
        log.exception('REGISTRY laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Mengeneinheiten ───────────────────────────────────

@app.route('/stammdaten/mengeneinheiten')
@_login_required
def stammdaten_mengeneinheit_seite():
    """Read-only Liste der CAO-``MENGENEINHEIT``-Tabelle.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Mengeneinheiten*.
    """
    return render_template('stammdaten_mengeneinheit.html')


@app.get('/api/stammdaten/mengeneinheiten')
@_login_required
def api_stammdaten_mengeneinheit():
    """JSON-Liste der Mengeneinheiten inkl. EN16931-Klarnamen."""
    import stammdaten_mengeneinheit as _me
    try:
        return jsonify(ok=True, eintraege=_me.liste())
    except Exception as e:
        log.exception('MENGENEINHEIT laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Zahlungsarten ─────────────────────────────────

@app.route('/stammdaten/zahlungsarten')
@_login_required
def stammdaten_zahlungsart_seite():
    """Read-only Liste der CAO-``ZAHLUNGSARTEN``-Tabelle.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Zahlungsarten*.
    """
    return render_template('stammdaten_zahlungsart.html')


@app.get('/api/stammdaten/zahlungsarten')
@_login_required
def api_stammdaten_zahlungsart():
    """JSON-Liste der Zahlungsarten mit Y/N-Flags als Bool."""
    import stammdaten_zahlungsart as _za
    try:
        return jsonify(ok=True, eintraege=_za.liste())
    except Exception as e:
        log.exception('ZAHLUNGSARTEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Lieferarten ───────────────────────────────────

@app.route('/stammdaten/lieferarten')
@_login_required
def stammdaten_lieferart_seite():
    """Read-only Liste der CAO-``LIEFERARTEN``-Tabelle.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Lieferarten*.
    """
    return render_template('stammdaten_lieferart.html')


@app.get('/api/stammdaten/lieferarten')
@_login_required
def api_stammdaten_lieferart():
    """JSON-Liste der Lieferarten inkl. Standard-Belegtext."""
    import stammdaten_lieferart as _la
    try:
        return jsonify(ok=True, eintraege=_la.liste())
    except Exception as e:
        log.exception('LIEFERARTEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Laender + MwSt ────────────────────────────────

@app.route('/stammdaten/laender')
@_login_required
def stammdaten_land_seite():
    """Read-only Liste der CAO-``LAND``-Tabelle mit MwSt-Saetzen.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Laender*.
    """
    return render_template('stammdaten_land.html')


@app.get('/api/stammdaten/laender')
@_login_required
def api_stammdaten_land():
    """JSON-Liste der Laender inkl. MwSt-Saetze und EU-Flag."""
    import stammdaten_land as _lnd
    try:
        return jsonify(ok=True, eintraege=_lnd.liste())
    except Exception as e:
        log.exception('LAND laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Adressgruppen ─────────────────────────────────

@app.route('/stammdaten/adressgruppen')
@_login_required
def stammdaten_adressgruppe_seite():
    """Read-only Baum der CAO-``ADRESSGRUPPEN``-Tabelle.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Adressgruppen*.
    """
    return render_template('stammdaten_adressgruppe.html')


@app.get('/api/stammdaten/adressgruppen')
@_login_required
def api_stammdaten_adressgruppe():
    """JSON-Liste der Adressgruppen inkl. Parent-ID fuer Baum."""
    import stammdaten_adressgruppe as _ag
    try:
        res = _ag.liste()
        return jsonify(ok=True,
                       parent_spalte=res['parent_spalte'],
                       eintraege=res['eintraege'])
    except Exception as e:
        log.exception('ADRESSGRUPPEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Warengruppen ──────────────────────────────────

@app.route('/stammdaten/warengruppen')
@_login_required
def stammdaten_warengruppe_seite():
    """Read-only Baum der CAO-``WARENGRUPPEN``-Tabelle.

    Spiegelt die cao_admin.exe-Seite *Einstellungen → Warengruppen*
    mit Kalkulation (VK1..VK5-Faktoren), Steuercode und Default-Konten.
    """
    return render_template('stammdaten_warengruppe.html')


@app.get('/api/stammdaten/warengruppen')
@_login_required
def api_stammdaten_warengruppe():
    """JSON-Liste der Warengruppen inkl. Parent-ID fuer Baum."""
    import stammdaten_warengruppe as _wg
    try:
        res = _wg.liste()
        return jsonify(ok=True, eintraege=res['eintraege'])
    except Exception as e:
        log.exception('WARENGRUPPEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Kontenrahmen ──────────────────────────────────

@app.route('/stammdaten/kontenrahmen')
@_login_required
def stammdaten_kontenrahmen_seite():
    """Read-only-Liste der CAO-``FIBU_KONTEN``-Tabelle (mehrere Rahmen)."""
    return render_template('stammdaten_kontenrahmen.html')


@app.get('/api/stammdaten/kontenrahmen')
@_login_required
def api_stammdaten_kontenrahmen():
    """JSON-Liste aller Konten aller Rahmen."""
    import stammdaten_kontenrahmen as _kr
    try:
        res = _kr.liste()
        return jsonify(ok=True,
                       rahmen=res['rahmen'],
                       eintraege=res['eintraege'])
    except Exception as e:
        log.exception('KONTENRAHMEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Firmen-Bankkonten ────────────────────────────

@app.route('/stammdaten/firmen-bankkonten')
@_login_required
def stammdaten_firmenbank_seite():
    """Read-only-Liste der Firmen-Bankkonten (FIBU_KONTEN, KONTOART=20)."""
    return render_template('stammdaten_firmenbank.html')


@app.get('/api/stammdaten/firmen-bankkonten')
@_login_required
def api_stammdaten_firmenbank():
    """JSON-Liste aller Firmen-Bankkonten, gruppiert nach Rahmen."""
    import stammdaten_firmenbank as _fb
    try:
        res = _fb.liste()
        return jsonify(ok=True,
                       rahmen=res['rahmen'],
                       eintraege=res['eintraege'])
    except Exception as e:
        log.exception('FIRMEN-BANKKONTEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Firmendaten ──────────────────────────────────

@app.route('/stammdaten/firma')
@_login_required
def stammdaten_firma_seite():
    """Read-only-Detail der FIRMA-Tabelle (Mandantenstammsatz)."""
    return render_template('stammdaten_firma.html')


@app.get('/api/stammdaten/firma')
@_login_required
def api_stammdaten_firma():
    """JSON-Detail der Firmendaten (oder None falls Tabelle leer)."""
    import stammdaten_firma as _fa
    try:
        return jsonify(ok=True, firma=_fa.firma())
    except Exception as e:
        log.exception('FIRMA laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Artikelattribute ─────────────────────────────

@app.route('/stammdaten/artikelattribute')
@_login_required
def stammdaten_attribut_seite():
    """Read-only Liste der Artikelattribute + Optionen + Nutzung."""
    return render_template('stammdaten_attribut.html')


@app.get('/api/stammdaten/artikelattribute')
@_login_required
def api_stammdaten_attribut():
    import stammdaten_attribut as _at
    try:
        return jsonify(ok=True, eintraege=_at.liste())
    except Exception as e:
        log.exception('ARTIKEL_ATTRIBUT laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Nummernkreise ────────────────────────────────

@app.route('/stammdaten/nummernkreise')
@_login_required
def stammdaten_nummernkreise_seite():
    """Read-only Liste der Nummernkreise (REGISTRY 'MAIN\\NUMBERS')."""
    return render_template('stammdaten_nummernkreise.html')


@app.get('/api/stammdaten/nummernkreise')
@_login_required
def api_stammdaten_nummernkreise():
    import stammdaten_nummernkreise as _nk
    try:
        res = _nk.liste()
        return jsonify(ok=True,
                       eintraege=res['eintraege'],
                       log_total=res['log_total'])
    except Exception as e:
        log.exception('NUMMERNKREISE laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Export-Queries ───────────────────────────────

@app.route('/stammdaten/exporte')
@_login_required
def stammdaten_export_seite():
    """Read-only Liste der CAO-Reports (EXPORT + EXPORT_KATEGORIEN)."""
    return render_template('stammdaten_export.html')


@app.get('/api/stammdaten/exporte')
@_login_required
def api_stammdaten_export():
    import stammdaten_export as _ex
    try:
        res = _ex.liste()
        return jsonify(ok=True,
                       kategorien=res['kategorien'],
                       eintraege=res['eintraege'])
    except Exception as e:
        log.exception('EXPORT laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── CAO-Stammdaten: Binaerdaten ──────────────────────────────────

@app.route('/stammdaten/binaerdaten')
@_login_required
def stammdaten_binaer_seite():
    """Read-only Uebersicht der Binaerdaten-Typen + Speichernutzung."""
    return render_template('stammdaten_binaer.html')


@app.get('/api/stammdaten/binaerdaten')
@_login_required
def api_stammdaten_binaer():
    import stammdaten_binaer as _bi
    try:
        res = _bi.liste()
        return jsonify(ok=True,
                       kategorien=res['kategorien'],
                       total_anzahl=res['total_anzahl'],
                       total_bytes=res['total_bytes'])
    except Exception as e:
        log.exception('BINAERDATEN laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── System: App-Steuerung ────────────────────────────────────────

@app.route('/system/apps')
@_login_required
def system_apps_seite():
    """Status + Start/Stop/Restart aller Apps."""
    return render_template('system_apps.html')


@app.get('/api/system/apps')
@_login_required
def api_system_apps():
    import system_apps as _sa
    try:
        return jsonify(ok=True, apps=_sa.liste())
    except Exception as e:
        log.exception('system_apps liste fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/system/apps/<name>/<aktion>')
@_login_required
def api_system_apps_aktion(name: str, aktion: str):
    """``aktion`` = 'start' | 'stop' | 'restart'."""
    import system_apps as _sa
    if aktion == 'start':
        return jsonify(_sa.start(name))
    if aktion == 'stop':
        return jsonify(_sa.stop(name))
    if aktion == 'restart':
        return jsonify(_sa.restart(name))
    return jsonify(ok=False, msg=f'Unbekannte Aktion: {aktion}'), 400


@app.get('/api/system/apps/<name>/log')
@_login_required
def api_system_apps_log(name: str):
    import system_apps as _sa
    try:
        zeilen = int(request.args.get('zeilen', '80'))
    except (TypeError, ValueError):
        zeilen = 80
    return jsonify(_sa.log_tail(name, zeilen=zeilen))


# ── System: HACCP-Poller ─────────────────────────────────────────

@app.route('/system/haccp-poller')
@_login_required
def system_haccp_poller_seite():
    """Status + Konfig-Uebersicht fuer den HACCP-Poller-Daemon."""
    return render_template('system_haccp_poller.html')


@app.get('/api/system/haccp-poller')
@_login_required
def api_system_haccp_poller():
    import system_haccp_poller as _hp
    try:
        return jsonify(ok=True, **_hp.status())
    except Exception as e:
        log.exception('system_haccp_poller status fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/system/haccp-poller')
@_login_required
def api_system_haccp_poller_speichern():
    """Speichert HACCP-Konfig in DORFKERN_KONFIG.

    JSON-Body: {'tfa_api_key'?: str, 'tfa_base_url'?: str,
                'poll_intervall_s'?: int}
    Feld weglassen oder None = nicht aendern. Leerer String = explizit
    leeren (Rueckfall auf Env/Default beim Lesen).
    """
    import system_haccp_poller as _hp
    body = request.get_json(silent=True) or {}
    ma_id = session.get('mitarbeiter_id')
    try:
        intervall = body.get('poll_intervall_s')
        if intervall is not None and intervall != '':
            intervall = int(intervall)
        else:
            intervall = None
    except (TypeError, ValueError):
        return jsonify(ok=False,
                       msg='poll_intervall_s muss eine Zahl sein'), 400
    return jsonify(_hp.speichern(
        tfa_api_key=body.get('tfa_api_key'),
        tfa_base_url=body.get('tfa_base_url'),
        poll_intervall_s=intervall,
        ma_id=ma_id,
    ))


# ── Stammdaten: Mittagstisch ─────────────────────────────────────

@app.route('/stammdaten/mittagstisch')
@_login_required
def stammdaten_mittagstisch_seite():
    """Read-only Uebersicht der Mittagstisch-Konfiguration."""
    return render_template('stammdaten_mittagstisch.html')


@app.get('/api/stammdaten/mittagstisch')
@_login_required
def api_stammdaten_mittagstisch():
    import system_mittagstisch as _mt
    try:
        return jsonify(ok=True, **_mt.status())
    except Exception as e:
        log.exception('stammdaten_mittagstisch status fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/stammdaten/mittagstisch')
@_login_required
def api_stammdaten_mittagstisch_speichern():
    """Speichert Mittagstisch-Konfig in DORFKERN_KONFIG.

    JSON-Body: {'spreadsheet_id'?: str, 'credentials_json'?: str}
    Leerer credentials_json-String = alter Wert bleibt (nicht loeschen).
    """
    import system_mittagstisch as _mt
    body = request.get_json(silent=True) or {}
    ma_id = session.get('mitarbeiter_id')
    return jsonify(_mt.speichern(
        spreadsheet_id=body.get('spreadsheet_id'),
        credentials_json=body.get('credentials_json'),
        ma_id=ma_id,
    ))


@app.post('/api/stammdaten/mittagstisch/credentials/loeschen')
@_login_required
def api_stammdaten_mittagstisch_credentials_loeschen():
    """Entfernt die gespeicherten Service-Account-Credentials aus der DB."""
    import system_mittagstisch as _mt
    ma_id = session.get('mitarbeiter_id')
    return jsonify(_mt.credentials_loeschen(ma_id=ma_id))


# ── System: Dorfkern-Rechte-Matrix ───────────────────────────────

@app.route('/rechte/dorfkern')
@_login_required
def rechte_dorfkern_seite():
    """Editierbare Matrix Rolle x Permission-Objekt."""
    return render_template('system_rechte_dorfkern.html')


@app.get('/api/rechte/dorfkern/matrix')
@_login_required
def api_rechte_dorfkern_matrix():
    import system_rechte_dorfkern as _rd
    try:
        return jsonify(ok=True, **_rd.matrix())
    except Exception as e:
        log.exception('Matrix laden fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/rechte/dorfkern/zelle')
@_login_required
def api_rechte_dorfkern_zelle():
    """Body: {rolle, objekt_key, recht}. recht='' loescht den Eintrag."""
    import system_rechte_dorfkern as _rd
    body = request.get_json(silent=True) or {}
    return jsonify(_rd.zelle_setzen(
        rolle=body.get('rolle', ''),
        objekt_key=body.get('objekt_key', ''),
        recht=body.get('recht', ''),
    ))


# ── System: Mitarbeiter (Rechte-Uebersicht) ──────────────────────

@app.route('/system/mitarbeiter')
@_login_required
def system_mitarbeiter_seite():
    """Mitarbeiter-Liste mit CAO-Rolle und abgeleiteten Dorfkern-Rechten."""
    return render_template('system_mitarbeiter.html')


@app.get('/api/system/mitarbeiter')
@_login_required
def api_system_mitarbeiter():
    import system_mitarbeiter as _sm
    try:
        return jsonify(ok=True, mitarbeiter=_sm.liste())
    except Exception as e:
        log.exception('Mitarbeiter-Liste fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


# ── System: Updates ──────────────────────────────────────────────

@app.route('/system/updates')
@_login_required
def system_updates():
    return render_template('system_updates.html')


@app.route('/api/system/update-status')
@_login_required
def api_update_status():
    """Prueft auf Updates – commit-basiert via installer.updater.

    Es gibt KEINE manuelle VERSION.json-Pflege mehr: 'available' wird
    rein aus 'gibt es Commits in origin/<branch> die ich nicht habe?'
    abgeleitet. VERSION.json wird – wenn vorhanden – nur als
    Anzeige-Hint gelesen.
    """
    try:
        from installer import updater as _upd
    except Exception as exc:
        return jsonify({'error': f'Updater nicht verfuegbar: {exc}'}), 200

    status = _upd.check_for_updates()
    if status.get('error'):
        return jsonify({'error': status['error'],
                         'local_commit': status.get('local_commit', '')}), 200
    # Auf maximal 30 Commits in der Anzeige begrenzen
    status['commits'] = (status.get('commits') or [])[:30]

    # Stand des laufenden App-Prozesses (beim Boot ermittelt) zusaetzlich
    # mitliefern. Wenn der Working-Tree zwischenzeitlich aktualisiert
    # wurde (z.B. durch ein vorheriges Update oder manuellen pull), aber
    # der Admin-App-Prozess noch im Speicher haengt, ist 'available' zwar
    # false (lokal == remote), trotzdem muss ein Neustart her, damit
    # neuer Code wirksam wird.
    status['running_commit']    = GIT_COMMIT_SHORT
    status['restart_required']  = bool(
        GIT_COMMIT_SHORT and status.get('local_commit')
        and GIT_COMMIT_SHORT != status['local_commit']
    )
    return jsonify(status)


@app.route('/api/system/update', methods=['POST'])
@_login_required
def api_system_update():
    """
    Startet das Update im Hintergrund.
    Das Script loggt nach /tmp/<prefix>-update.log (Default
    /tmp/dorfkern-update.log; bei Instanz 'prod' z.B.
    /tmp/dorfkern-prod-update.log).
    """
    repo_root = os.path.normpath(os.path.join(BASE_DIR, '..', '..'))
    venv_python = os.path.join(repo_root, '.venv', 'bin', 'python3')
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    # Log-Pfad aus dem Updater holen, damit Instanz-Suffix konsistent bleibt.
    try:
        from installer import updater as _upd
        log_path = _upd._LOG_FILE
    except Exception:
        log_path = '/tmp/dorfkern-update.log'

    try:
        subprocess.Popen(
            [venv_python, '-m', 'installer.updater', '--update'],
            cwd=repo_root,
            stdout=open(log_path, 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({'ok': True, 'log': log_path})


@app.route('/api/system/restart-all', methods=['POST'])
@_login_required
def api_system_restart_all():
    """Startet ALLE Apps neu, damit ein bereits aktualisierter Working-Tree
    wirksam wird (Fall: ``restart_required=True``).

    Wichtig: nicht nur Admin neustarten. Wenn der Working-Tree neuer ist
    als der laufende Prozess, betrifft das in der Regel alle Apps —
    z. B. weil sich gemeinsame Module unter ``common/`` geaendert haben.
    Nur Admin frisch zu starten wuerde die anderen Apps mit dem alten
    Code weiterlaufen lassen und ergibt inkonsistente Sicht.

    Wir loesen den Restart ueber ``dorfkern-ctl`` aus, damit dieselbe
    Stop/Start-Logik wie bei einem regulaeren Update genutzt wird
    (PID-File / systemd, je nach Modus). Der Subprozess wird in einer
    neuen Session abgekoppelt – bevor er den eigenen Admin-Service
    killt, hat Flask die HTTP-Antwort bereits ausgeliefert. dorfkern-ctl
    iteriert dann durch alle Apps in der definierten Reihenfolge.
    """
    repo_root = os.path.normpath(os.path.join(BASE_DIR, '..', '..'))
    ctl = os.path.join(repo_root, 'dorfkern-ctl')
    if not os.path.exists(ctl):
        return jsonify({'ok': False,
                        'error': 'dorfkern-ctl nicht gefunden'}), 500

    # Restart-Log instanz-suffigiert (passend zur Updater-Konvention).
    # log_path() bevorzugt /var/log/<prefix>/restart.log, fallback /tmp.
    try:
        from common.config import load_instance_config, log_path
        inst = load_instance_config().get('instance_name', '')
        restart_log = log_path('restart', inst)
    except Exception:
        restart_log = '/tmp/dorfkern-restart.log'

    try:
        subprocess.Popen(
            [ctl, 'restart'],   # kein App-Arg = alle Apps
            cwd=repo_root,
            stdout=open(restart_log, 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'log': restart_log})


# ── Power-Steuerung (Feierabend-Knopf, Reboot) ──────────────────

@app.route('/system/power')
@_login_required
def system_power():
    return render_template('system_power.html')


def _trigger_poweroff(args: list[str]) -> tuple[bool, str]:
    """Fuehrt 'sudo -n <args>' detached aus. Liefert (ok, errstr).

    start_new_session=True kapppt den Subprozess vom Flask-Worker ab,
    sodass die HTTP-Antwort noch rausgeht bevor systemd anfaengt,
    Services abzuwuerg en.
    """
    try:
        subprocess.Popen(['sudo', '-n'] + args,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True, ''
    except Exception as exc:
        return False, str(exc)


@app.route('/api/system/shutdown', methods=['POST'])
@_login_required
def api_system_shutdown():
    """Faehrt den Rechner sofort herunter (Feierabend-Knopf).

    Voraussetzung: /etc/sudoers.d/dorfkern-shutdown erlaubt dem
    dorfkern-User '/sbin/shutdown -h now' passwortfrei. Wird vom
    Installer (host_setup.install_system) angelegt.
    """
    ok, err = _trigger_poweroff(['/sbin/shutdown', '-h', 'now'])
    if not ok:
        return jsonify({'ok': False, 'error': err}), 500
    return jsonify({'ok': True})


@app.route('/api/system/reboot', methods=['POST'])
@_login_required
def api_system_reboot():
    """Startet den Rechner neu (z.B. nach Update das einen vollen Boot
    braucht — Kernel-Update, Treiber, etc.). Im Gegensatz zu
    /api/system/restart-all (das nur die Apps neu startet)."""
    ok, err = _trigger_poweroff(['/sbin/shutdown', '-r', 'now'])
    if not ok:
        return jsonify({'ok': False, 'error': err}), 500
    return jsonify({'ok': True})


# ── Wartungs-Modus (Kiosk ↔ Greeter Toggle) ──────────────────

_MAINTENANCE_SCRIPT = '/usr/local/bin/dorfkern-maintenance-mode'


def _run_maintenance(args: list[str]) -> tuple[bool, str, str]:
    """Ruft das maintenance-mode-Skript via sudo synchron.

    Liefert (ok, stdout, stderr_or_err). Synchron weil der LightDM-
    Restart nur ~1s dauert und wir das Ergebnis dem Frontend
    zurueckmelden wollen (Frontend zeigt aktualisierten Status an).
    """
    try:
        r = subprocess.run(['sudo', '-n', _MAINTENANCE_SCRIPT] + args,
                           capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, '', f'Skript fehlt: {_MAINTENANCE_SCRIPT}'
    except Exception as exc:
        return False, '', str(exc)
    out = (r.stdout or '').strip()
    err = (r.stderr or '').strip()
    return r.returncode == 0, out, err or f'exit {r.returncode}'


@app.route('/api/system/maintenance', methods=['GET'])
@_login_required
def api_system_maintenance_status():
    """Liefert den aktuellen Wartungs-Modus.

    Returns: {'ok': True, 'mode': 'kiosk'|'maintenance'|'unknown',
              'message': str}
    """
    ok, out, err = _run_maintenance(['--status'])
    if not ok:
        return jsonify({'ok': False, 'error': err}), 500
    mode = 'unknown'
    low = out.lower()
    if 'kiosk' in low:
        mode = 'kiosk'
    elif 'maintenance' in low:
        mode = 'maintenance'
    elif 'greeter' in low:
        mode = 'greeter'
    return jsonify({'ok': True, 'mode': mode, 'message': out})


@app.route('/api/system/maintenance', methods=['POST'])
@_login_required
def api_system_maintenance_set():
    """Setzt den Wartungs-Modus.

    Body (JSON oder Form): mode=maintenance|kiosk
    Default ohne Argument: maintenance (= Greeter zeigen).

    Achtung: Wirkt am Bildschirm der Box (LightDM-Restart). Die
    Apps und damit der Admin-Browser laufen weiter; der Aufrufer
    sieht keinen Verbindungsabbruch.
    """
    payload = request.get_json(silent=True) or request.form
    target = (payload.get('mode', '') if payload else '').strip().lower()
    if target == 'kiosk':
        args = ['--kiosk']
    elif target == 'greeter':
        args = ['--greeter']
    elif target in ('maintenance', 'wartung', ''):
        args = ['--maintenance']
    else:
        return jsonify({'ok': False,
                        'error': f"Unbekannter Mode {target!r}"}), 400
    ok, out, err = _run_maintenance(args)
    if not ok:
        return jsonify({'ok': False, 'error': err, 'output': out}), 500
    return jsonify({'ok': True, 'output': out})


# ── Zeiten-CSV Import (ShiftJuggler Attendance-Export) ───────────

@app.route('/zeiten-import', methods=['GET', 'POST'])
@_login_required
def zeiten_import():
    """Upload-Formular fuer eine ShiftJuggler-Attendance-CSV.

    GET  → Formular mit Format-Infos (Template: zeiten_import.html).
    POST → Datei parsen und entweder Dry-Run-Report oder scharf importieren.

    Der eigentliche Import liegt in
    ``modules.orga.personal.tools.import_zeiten`` – die Admin-App ruft
    ihn nur auf und zeigt den Report an.
    """
    if request.method == 'GET':
        return render_template('zeiten_import.html',
                               stats=None, dry_run=None, fehler=None)

    datei = request.files.get('csv')
    dry_run = bool(request.form.get('dry_run'))
    if not datei or not datei.filename:
        return render_template('zeiten_import.html',
                               stats=None, dry_run=dry_run,
                               fehler='Keine Datei ausgewaehlt.')

    import tempfile
    from modules.orga.personal.tools.import_zeiten import importiere_csv

    suffix = '.csv' if datei.filename.lower().endswith('.csv') else ''
    fd, tmp_path = tempfile.mkstemp(prefix='zeiten_import_', suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as fh:
            datei.save(fh)
        try:
            stats = importiere_csv(tmp_path,
                                   benutzer_ma_id=session['ma_id'],
                                   dry_run=dry_run)
        except Exception as e:
            log.warning("Zeiten-Import fehlgeschlagen: %s", e)
            return render_template('zeiten_import.html',
                                   stats=None, dry_run=dry_run,
                                   fehler=f'Import fehlgeschlagen: {e}')
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return render_template('zeiten_import.html',
                           stats=stats, dry_run=dry_run, fehler=None,
                           dateiname=datei.filename)


# ── Gemeinsame Brand-Assets (common/brand/*) ──────────────────
_BRAND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'brand')
)


@app.route('/brand/<path:dateiname>')
def _brand_asset(dateiname):
    """Liefert Dorfkern-Logo-Assets (dorfkern-logo.js etc.) aus common/brand/."""
    return send_from_directory(_BRAND_DIR, dateiname,
                               max_age=60 * 60 * 24)


@app.route('/favicon.ico')
def _favicon():
    """Favicon-Default-Pfad — Browser fragen /favicon.ico an, wenn kein
    <link rel='icon'> im <head> steht (z.B. login.html erbt kein base.html)."""
    return send_from_directory(_BRAND_DIR, 'favicon.ico',
                               max_age=60 * 60 * 24,
                               mimetype='image/x-icon')


# ── Gemeinsame Statik (common/static/*) – dorfkern.css et al. ──
from common.static_serving import register_common_static as _reg_common_static  # noqa: E402
_reg_common_static(app)


# ── Legacy-Redirects (Dorfkern v2 Rename /verwaltung → /admin) ─
# Bestehende Bookmarks / Druck-QR-Codes treffen weiterhin auf /verwaltung/...
# Wir antworten 301 auf /admin/...  Soll in Dorfkern v2.1 entfernt werden.
@app.route('/verwaltung', defaults={'pfad': ''}, strict_slashes=False)
@app.route('/verwaltung/<path:pfad>')
def _legacy_verwaltung_redirect(pfad):
    ziel = '/admin' + (('/' + pfad) if pfad else '')
    if request.query_string:
        ziel += '?' + request.query_string.decode('utf-8', 'ignore')
    return redirect(ziel, code=301)


# ── Dorfkern v2: Konfiguration + Terminal-Registry ────────────

from common import konfig as _konfig  # noqa: E402
from common import terminal as _terminal  # noqa: E402
from common import aktivierung as _aktivierung  # noqa: E402

_KONFIG_TYPEN = ('STRING', 'INT', 'BOOL', 'JSON', 'SECRET')


@app.route('/dorfkern/konfig')
@_login_required
def dorfkern_konfig():
    kategorien = sorted({e['KATEGORIE'] for e in _konfig.alle()
                         if e.get('KATEGORIE')})
    return render_template('dorfkern_konfig.html',
                           kategorien=kategorien,
                           typen=_KONFIG_TYPEN)


@app.get('/api/dorfkern/konfig')
@_login_required
def api_dorfkern_konfig_list():
    kategorie = request.args.get('kategorie') or None
    try:
        eintraege = _konfig.alle(kategorie=kategorie)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    # SECRET-Werte maskieren
    for e in eintraege:
        if e.get('TYP') == 'SECRET' and e.get('WERT'):
            w = str(e['WERT'])
            e['WERT'] = (w[:2] + '…' + w[-1:]) if len(w) > 4 else '…'
    return jsonify(ok=True, eintraege=eintraege)


@app.post('/api/dorfkern/konfig')
@_login_required
def api_dorfkern_konfig_upsert():
    d = request.get_json(force=True) or {}
    schluessel = (d.get('schluessel') or '').strip()
    if not schluessel:
        return jsonify(ok=False, msg='SCHLUESSEL darf nicht leer sein.'), 400
    typ = (d.get('typ') or 'STRING').upper()
    if typ not in _KONFIG_TYPEN:
        return jsonify(ok=False, msg=f'Ungueltiger TYP: {typ}'), 400
    try:
        _konfig.set(
            schluessel,
            d.get('wert', ''),
            typ=typ,
            kategorie=(d.get('kategorie') or 'ALLGEMEIN').strip(),
            beschreibung=(d.get('beschreibung') or None),
            ma_id=session.get('ma_id'),
        )
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, msg='Konfiguration gespeichert.')


@app.delete('/api/dorfkern/konfig/<path:schluessel>')
@_login_required
def api_dorfkern_konfig_delete(schluessel):
    try:
        with get_db_transaction() as cur:
            cur.execute("DELETE FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                        (schluessel,))
        _konfig.invalidate(schluessel)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, msg='Eintrag geloescht.')


@app.route('/dorfkern/terminals')
@_login_required
def dorfkern_terminals():
    return render_template(
        'dorfkern_terminals.html',
        host_hostname=_terminal.hostname(),
        host_mac=_terminal.mac_adresse(),
        host_ip=_terminal.lokale_ip(),
    )


@app.get('/api/dorfkern/terminals')
@_login_required
def api_dorfkern_terminals_list():
    typ = request.args.get('typ') or None
    try:
        # DATETIME-Felder als ISO-String fuer JSON-Kompatibilitaet
        eintraege = _terminal.alle(typ=typ)
        for e in eintraege:
            kontakt = e.get('LETZTER_KONTAKT')
            if kontakt and hasattr(kontakt, 'isoformat'):
                e['LETZTER_KONTAKT'] = kontakt.isoformat(sep=' ',
                                                        timespec='seconds')
        return jsonify(ok=True, eintraege=eintraege)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/dorfkern/terminals')
@_login_required
def api_dorfkern_terminals_create():
    d = request.get_json(force=True) or {}
    try:
        tid = _terminal.anlegen(
            bezeichnung=(d.get('bezeichnung') or '').strip(),
            typ=(d.get('typ') or '').upper(),
            hostname_=(d.get('hostname') or None),
            mac=(d.get('mac_adresse') or None),
        )
    except ValueError as e:
        return jsonify(ok=False, msg=str(e)), 400
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, terminal_id=tid, msg='Terminal angelegt.')


@app.put('/api/dorfkern/terminals/<int:terminal_id>')
@_login_required
def api_dorfkern_terminals_update(terminal_id):
    d = request.get_json(force=True) or {}
    try:
        _terminal.aktualisieren(terminal_id, **d)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, msg='Terminal aktualisiert.')


@app.delete('/api/dorfkern/terminals/<int:terminal_id>')
@_login_required
def api_dorfkern_terminals_delete(terminal_id):
    try:
        _terminal.loeschen(terminal_id)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, msg='Terminal geloescht.')


# ── Dorfkern v2: App-Aktivierungen (Phase 7) ──────────────────

@app.route('/dorfkern/aktivierungen')
@_login_required
def dorfkern_aktivierungen():
    return render_template('dorfkern_aktivierungen.html')


@app.get('/api/dorfkern/aktivierungen')
@_login_required
def api_dorfkern_aktivierungen_list():
    try:
        eintraege = _aktivierung.alle()
        for e in eintraege:
            g = e.get('GEAENDERT_AM')
            if g and hasattr(g, 'isoformat'):
                e['GEAENDERT_AM'] = g.isoformat(sep=' ', timespec='seconds')
            lb = e.get('LIZENZ_BIS')
            if lb and hasattr(lb, 'isoformat'):
                e['LIZENZ_BIS'] = lb.isoformat()
        return jsonify(ok=True, eintraege=eintraege)
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/dorfkern/aktivierungen/<app_name>')
@_login_required
def api_dorfkern_aktivierungen_upsert(app_name):
    d = request.get_json(force=True) or {}
    try:
        _aktivierung.set_aktiv(
            app_name,
            aktiv=bool(d.get('aktiv')),
            lizenz_bis=(d.get('lizenz_bis') or None),
            hinweis=(d.get('hinweis') or None),
        )
    except ValueError as e:
        return jsonify(ok=False, msg=str(e)), 400
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500
    return jsonify(ok=True, msg='Aktivierung gespeichert.')


# ── Einkauf: Lieferanten-Registry + IMAP (Phase 1) ───────────────

from common import einkauf as _einkauf  # noqa: E402


@app.route('/einkauf/lieferanten')
@_login_required
def einkauf_lieferanten_seite():
    """Verwaltung Einkauf-Lieferanten + IMAP-Zugang."""
    return render_template('einkauf_lieferanten.html')


@app.get('/api/einkauf/lieferanten')
@_login_required
def api_einkauf_lieferanten_liste():
    eintraege = _einkauf.liste()
    # Pro Eintrag das "web_password_gesetzt"-Flag mitliefern, damit das
    # UI eine Plomben-Markierung zeigen kann ohne das Passwort zu lesen.
    for e in eintraege:
        e['WEB_PASSWORD_GESETZT'] = _einkauf.web_password_gesetzt(
            e['KUERZEL'])
    return jsonify(ok=True, eintraege=eintraege)


@app.post('/api/einkauf/lieferanten')
@_login_required
def api_einkauf_lieferanten_anlegen():
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    try:
        rec_id = _einkauf.anlegen(body, ma_id=ma_id)
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc)), 400
    except Exception as exc:
        log.exception('einkauf.anlegen fehlgeschlagen')
        msg = str(exc)
        # Wahrscheinlichster Fall: Duplicate-Key auf KUERZEL → 409.
        if 'Duplicate' in msg or 'uq_kuerzel' in msg:
            return jsonify(ok=False,
                           msg=f'Kuerzel ist bereits vergeben.'), 409
        return jsonify(ok=False, msg=msg), 500
    # Web-Passwort optional gleich mit anlegen
    pw = body.get('WEB_PASSWORD')
    if pw:
        kuerzel = (body.get('KUERZEL') or '').strip().upper()
        _einkauf.web_password_setzen(kuerzel, pw, ma_id=ma_id)
    return jsonify(ok=True, rec_id=rec_id)


@app.put('/api/einkauf/lieferanten/<int:rec_id>')
@_login_required
def api_einkauf_lieferanten_aktualisieren(rec_id):
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    eintrag = _einkauf.holen(rec_id)
    if not eintrag:
        return jsonify(ok=False, msg='Lieferant nicht gefunden.'), 404
    try:
        _einkauf.aktualisieren(rec_id, body, ma_id=ma_id)
    except Exception as exc:
        log.exception('einkauf.aktualisieren fehlgeschlagen')
        return jsonify(ok=False, msg=str(exc)), 500
    # Optional: Web-Passwort mit-aktualisieren (None = unveraendert,
    # '' = Passwort entfernen, sonst neu setzen).
    if 'WEB_PASSWORD' in body:
        pw = body.get('WEB_PASSWORD')
        if pw is not None:
            _einkauf.web_password_setzen(eintrag['KUERZEL'], pw,
                                         ma_id=ma_id)
    return jsonify(ok=True)


@app.get('/api/einkauf/adressen-suche')
@_login_required
def api_einkauf_adressen_suche():
    """Suche in ADRESSEN nach Suchtext fuer das CAO-Lieferant-Feld
    im Lieferanten-Modal. Such-Felder: MATCHCODE / NAME1 / NAME2.
    Lese-only.
    """
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify(ok=True, eintraege=[])
    like = f'%{q}%'
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT REC_ID, MATCHCODE, NAME1, NAME2, PLZ, ORT
                FROM ADRESSEN
                WHERE MATCHCODE LIKE %s OR NAME1 LIKE %s OR NAME2 LIKE %s
                ORDER BY MATCHCODE
                LIMIT 12
            """, (like, like, like))
            rows = cur.fetchall() or []
    except Exception as exc:
        return jsonify(ok=False, msg=str(exc)), 500
    return jsonify(ok=True, eintraege=rows)


@app.post('/api/einkauf/lieferanten/<int:rec_id>/web-test')
@_login_required
def api_einkauf_lieferanten_web_test(rec_id):
    """Versucht den Web-Login fuer einen Lieferanten und liefert
    Diagnose-Output (Cookies, Status, Title, finale URL).
    Lese-only – keine Daten werden gespeichert."""
    from common import einkauf_lief_web as _web
    res = _web.web_login_test(rec_id)
    return jsonify(**res), 200 if res.get('ok') else 502


@app.post('/api/einkauf/lieferanten/<int:rec_id>/web-artikel-probe')
@_login_required
def api_einkauf_lieferanten_artikel_probe(rec_id):
    """Diagnose-Endpoint: loggt sich ein und probiert mehrere
    plausible Artikel-Detail-URLs fuer eine gegebene ArtNr.
    Body: {'artnr': str}. Returns: best_url, best_score,
    titel, snippet, raw_snippet, versuche[].
    """
    from common import einkauf_lief_web as _web
    body = request.get_json(silent=True) or {}
    artnr = (body.get('artnr') or '').strip()
    if not artnr:
        return jsonify(ok=False, msg='artnr fehlt'), 400
    res = _web.web_artikel_diagnose(rec_id, artnr)
    return jsonify(**res), 200 if res.get('ok') else 502


@app.delete('/api/einkauf/lieferanten/<int:rec_id>')
@_login_required
def api_einkauf_lieferanten_loeschen(rec_id):
    eintrag = _einkauf.holen(rec_id)
    if not eintrag:
        return jsonify(ok=False, msg='Lieferant nicht gefunden.'), 404
    try:
        _einkauf.loeschen(rec_id)
        # Web-Passwort gleich mit aufraeumen
        _einkauf.web_password_setzen(eintrag['KUERZEL'], '')
    except Exception as exc:
        log.exception('einkauf.loeschen fehlgeschlagen')
        return jsonify(ok=False, msg=str(exc)), 500
    return jsonify(ok=True)


@app.get('/api/einkauf/imap')
@_login_required
def api_einkauf_imap_lesen():
    return jsonify(ok=True, **_einkauf.imap_konfig())


@app.post('/api/einkauf/imap')
@_login_required
def api_einkauf_imap_speichern():
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    try:
        port = body.get('port')
        if port is not None and port != '':
            port = int(port)
        else:
            port = None
        poll_min = body.get('poll_min')
        if poll_min is not None and poll_min != '':
            poll_min = int(poll_min)
        else:
            poll_min = None
    except (TypeError, ValueError):
        return jsonify(ok=False,
                       msg='port/poll_min muessen Zahlen sein'), 400
    cfg = _einkauf.imap_konfig_speichern(
        host=body.get('host'),
        port=port,
        user=body.get('user'),
        password=body.get('password'),  # None = unveraendert
        use_ssl=body.get('use_ssl'),
        folder=body.get('folder'),
        poll_min=poll_min,
        ma_id=ma_id,
    )
    return jsonify(ok=True, **cfg)


@app.post('/api/einkauf/imap/test')
@_login_required
def api_einkauf_imap_test():
    """Versucht IMAP-Login mit der gespeicherten Konfiguration."""
    res = _einkauf.imap_verbindungstest()
    status = 200 if res.get('ok') else 502
    return jsonify(**res), status


# ── Einkauf: Gmail-API / OAuth 2.0 ──────────────────────────────

def _gmail_redirect_uri() -> str:
    """Baut die OAuth-Callback-URL aus der aktuellen Request-URL.

    Wichtig: dieser Pfad muss exakt in der Google-Cloud-Console als
    Authorized-Redirect-URI hinterlegt sein. Das UI zeigt dem User die
    aktuell errechnete URL an, damit er sie kopieren kann.
    """
    base = request.host_url.rstrip('/')
    return f'{base}/einkauf/oauth/callback'


@app.get('/api/einkauf/gmail')
@_login_required
def api_einkauf_gmail_lesen():
    cfg = _einkauf.gmail_konfig()
    cfg['redirect_uri'] = _gmail_redirect_uri()
    return jsonify(ok=True, **cfg)


@app.post('/api/einkauf/gmail')
@_login_required
def api_einkauf_gmail_speichern():
    body = request.get_json(silent=True) or {}
    ma_id = session.get('ma_id')
    try:
        poll_min = body.get('poll_min')
        if poll_min not in (None, ''):
            poll_min = int(poll_min)
        else:
            poll_min = None
    except (TypeError, ValueError):
        return jsonify(ok=False,
                       msg='poll_min muss eine Zahl sein'), 400
    cfg = _einkauf.gmail_konfig_speichern(
        client_id=body.get('client_id'),
        client_secret=body.get('client_secret'),
        user_email=body.get('user_email'),
        poll_min=poll_min,
        ma_id=ma_id,
    )
    cfg['redirect_uri'] = _gmail_redirect_uri()
    return jsonify(ok=True, **cfg)


@app.get('/einkauf/oauth/start')
@_login_required
def einkauf_oauth_start():
    """Startet den OAuth-Consent-Flow (Browser-Redirect zu Google)."""
    import secrets as _secrets
    state = _secrets.token_urlsafe(32)
    session['einkauf_oauth_state'] = state
    try:
        auth_url, _, code_verifier = _einkauf.gmail_oauth_url(
            _gmail_redirect_uri(), state=state)
    except (ValueError, RuntimeError) as exc:
        return redirect(url_for('einkauf_lieferanten_seite')
                        + f'?oauth_error={str(exc)[:120]}')
    # PKCE-Verifier zwischenspeichern – der Callback braucht ihn fuer
    # den Token-Tausch (sonst antwortet Google mit
    # 'invalid_grant: Missing code verifier').
    session['einkauf_oauth_verifier'] = code_verifier
    return redirect(auth_url)


@app.get('/einkauf/oauth/callback')
@_login_required
def einkauf_oauth_callback():
    """Empfaengt den Authorization-Code und tauscht ihn gegen einen
    Refresh-Token. Bei Erfolg/Fehler Redirect zurueck auf die Lieferanten-
    Seite mit Status-Query.
    """
    code  = request.args.get('code', '')
    state = request.args.get('state', '')
    err   = request.args.get('error', '')
    expected_state = session.pop('einkauf_oauth_state', '')
    verifier       = session.pop('einkauf_oauth_verifier', '')

    if err:
        return redirect(url_for('einkauf_lieferanten_seite')
                        + f'?oauth_error={err}')
    if not code:
        return redirect(url_for('einkauf_lieferanten_seite')
                        + '?oauth_error=Kein+Code+empfangen')
    if not state or state != expected_state:
        return redirect(url_for('einkauf_lieferanten_seite')
                        + '?oauth_error=State-Mismatch')

    res = _einkauf.gmail_oauth_token_speichern(
        code, _gmail_redirect_uri(),
        code_verifier=verifier,
        ma_id=session.get('ma_id'))
    if not res.get('ok'):
        return redirect(url_for('einkauf_lieferanten_seite')
                        + f'?oauth_error={res.get("msg", "")[:120]}')
    return redirect(url_for('einkauf_lieferanten_seite')
                    + f'?oauth_ok=1&email={res.get("email", "")}')


@app.post('/api/einkauf/gmail/disconnect')
@_login_required
def api_einkauf_gmail_disconnect():
    return jsonify(**_einkauf.gmail_oauth_disconnect(
        ma_id=session.get('ma_id')))


@app.post('/api/einkauf/gmail/test')
@_login_required
def api_einkauf_gmail_test():
    res = _einkauf.gmail_verbindungstest()
    return jsonify(**res), 200 if res.get('ok') else 502


# ── Einkauf: eingegangene Bestellungen ──────────────────────────

@app.route('/einkauf/bestellungen')
@_login_required
def einkauf_bestellungen_seite():
    """Liste der eingegangenen Bestellbestaetigungen."""
    return render_template('einkauf_bestellungen.html')


@app.get('/api/einkauf/bestellungen')
@_login_required
def api_einkauf_bestellungen_liste():
    status = request.args.get('status') or None
    limit  = int(request.args.get('limit', 100))
    return jsonify(ok=True,
                   eintraege=_einkauf.bestellungen_liste(
                       status=status, limit=limit))


@app.get('/api/einkauf/bestellungen/<int:rec_id>')
@_login_required
def api_einkauf_bestellung_detail(rec_id):
    e = _einkauf.bestellung_holen(rec_id)
    if not e:
        return jsonify(ok=False, msg='Nicht gefunden.'), 404
    return jsonify(ok=True, eintrag=e)


@app.post('/api/einkauf/bestellungen/<int:rec_id>/sync-cao')
@_login_required
def api_einkauf_bestellung_sync_cao(rec_id):
    """Phase 5a: schreibt die Lieferantenpreis-Verknuepfungen einer
    Bestellung nach CAO. Body: {'dry_run': bool}.

    Sicherheitsmodell:
    * Stammartikel-Anlage NICHT enthalten (Phase 5b separat).
    * UPDATE/INSERT auf ARTIKEL_PREIS, kein _LOG (CAO macht hier
      auch keinen).
    * UNVERAENDERT-Positionen werden nur statusmaessig markiert.
    * Bei Fehler pro Position: Status='fehler', ANMERKUNG mit
      Fehlertext.
    """
    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get('dry_run', False))
    ma_name = (session.get('vname', '') + ' '
                + session.get('ma_name', '')).strip() \
              or session.get('login_name') or 'CAO-XT'
    res = _einkauf.cao_sync_artikel_preis(rec_id,
                                            dry_run=dry_run,
                                            ma_name=ma_name)
    return jsonify(**res), 200 if res.get('ok') else 502


@app.post('/api/einkauf/bestellungen/<int:rec_id>/sync-artikel')
@_login_required
def api_einkauf_bestellung_sync_artikel(rec_id):
    """Phase 5b: legt Stammartikel in CAO an + ARTIKEL_LOG-Snapshot
    + XT_ARTIKEL_VK_KONTROLLE-Eintrag fuer alle Positionen mit
    STATUS='neu_anlegen' und gesetzter WARENGRUPPE_ID.

    Body: {'dry_run': bool}.
    """
    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get('dry_run', False))
    ma_name = (session.get('vname', '') + ' '
                + session.get('ma_name', '')).strip() \
              or session.get('login_name') or 'CAO-XT'
    res = _einkauf.cao_sync_artikel(
        rec_id, dry_run=dry_run,
        ma_id=session.get('ma_id'), ma_name=ma_name,
    )
    return jsonify(**res), 200 if res.get('ok') else 502


@app.post('/api/einkauf/bestellungen/<int:rec_id>/sync-ekbestell')
@_login_required
def api_einkauf_bestellung_sync_ekbestell(rec_id):
    """Phase 6: legt eine Bestellung als CAO-EKBESTELL an + zugehoerige
    EKBESTELL_POS-Eintraege.

    Voraussetzung: alle Positionen STATUS='in_cao' (Phase 5a/b durch),
    CAO_EKBESTELL_REC_ID noch NULL. BELEGNUM wird aus REGISTRY-Counter
    'EK-BEST' vergeben.

    Body: {'dry_run': bool}. Dry-Run liefert Vorschau ohne INSERT.
    """
    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get('dry_run', False))
    ma_name = (session.get('vname', '') + ' '
                + session.get('ma_name', '')).strip() \
              or session.get('login_name') or 'CAO-XT'
    res = _einkauf.cao_sync_ekbestell(
        rec_id, dry_run=dry_run,
        ma_id=session.get('ma_id'), ma_name=ma_name,
    )
    return jsonify(**res), 200 if res.get('ok') else 502


@app.get('/api/einkauf/warengruppen')
@_login_required
def api_einkauf_warengruppen():
    """Liefert den CAO-WARENGRUPPEN-Baum + Flachliste fuer das UI.
    Cache: keiner (105 WGs sind gut so).
    """
    return jsonify(ok=True, **_einkauf.cao_warengruppen_baum())


@app.post('/api/einkauf/positionen/<int:pos_id>/warengruppe')
@_login_required
def api_einkauf_position_warengruppe(pos_id):
    """Setzt die WARENGRUPPE_ID einer Bestellposition (Phase 5b).
    Body: {'warengruppe_id': int|null}. ``null`` loescht die Auswahl."""
    body = request.get_json(silent=True) or {}
    raw = body.get('warengruppe_id')
    if raw in (None, '', 0):
        wg_id = None
    else:
        try:
            wg_id = int(raw)
        except (TypeError, ValueError):
            return jsonify(ok=False,
                           msg='warengruppe_id muss int sein'), 400
    res = _einkauf.position_warengruppe_setzen(pos_id, wg_id)
    return jsonify(**res), 200 if res.get('ok') else 400


@app.post('/api/einkauf/positionen/<int:pos_id>/ek-bezug')
@_login_required
def api_einkauf_position_ek_bezug(pos_id):
    """Setzt den EK-Bezug-Override fuer den Lief-Artikel hinter der
    Bestellposition (Phase 5b-Verbesserung).

    Body: {'ek_bezug': 'STK' | 'VPE_EK' | null}. ``null`` loescht den
    Override → Lieferanten-Default greift wieder.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get('ek_bezug')
    if raw in (None, '', 'null'):
        bezug = None
    elif str(raw).upper() in ('STK', 'VPE_EK'):
        bezug = str(raw).upper()
    else:
        return jsonify(ok=False,
                       msg="ek_bezug muss 'STK', 'VPE_EK' oder null sein"), 400
    # Lief-Artikel via Bestellposition aufloesen
    try:
        with _einkauf.get_db() as cur:
            cur.execute("""
                SELECT b.LIEF_REC_ID, p.ARTIKEL_NR_LIEF
                FROM XT_EINKAUF_BESTELLPOS p
                JOIN XT_EINKAUF_BESTELLUNG b ON b.REC_ID = p.BEST_REC_ID
                WHERE p.REC_ID = %s
            """, (pos_id,))
            row = cur.fetchone()
    except Exception as exc:
        return jsonify(ok=False, msg=str(exc)), 500
    if not row:
        return jsonify(ok=False, msg='Position nicht gefunden.'), 404
    res = _einkauf.lief_artikel_ek_bezug_setzen(
        row['LIEF_REC_ID'], row['ARTIKEL_NR_LIEF'], bezug)
    return jsonify(**res), 200 if res.get('ok') else 400


@app.post('/api/einkauf/positionen/<int:pos_id>/zuordnen')
@_login_required
def api_einkauf_position_zuordnen(pos_id):
    """Manuelle Zuordnung einer Bestellposition.

    Body:
        {cao_artikel_rec_id: int|null, neu_anlegen?: bool, anmerkung?: str}

    * ``cao_artikel_rec_id`` gesetzt → STATUS='matched', verlinkt
    * ``neu_anlegen=True``           → STATUS='neu_anlegen'
    * beides leer/false              → STATUS='neu' (Reset)
    Schreibt nur in XT-Tabellen, NICHT in CAO.
    """
    body = request.get_json(silent=True) or {}
    rec = body.get('cao_artikel_rec_id')
    rec_id = None
    if rec not in (None, '', 0):
        try:
            rec_id = int(rec)
        except (TypeError, ValueError):
            return jsonify(ok=False,
                           msg='cao_artikel_rec_id muss int sein'), 400
    res = _einkauf.position_zuordnen(
        pos_id,
        cao_artikel_rec_id=rec_id,
        neu_anlegen=bool(body.get('neu_anlegen')),
        manuell_klaeren=bool(body.get('manuell_klaeren')),
        anmerkung=body.get('anmerkung'),
        ma_id=session.get('ma_id'),
    )
    return jsonify(**res), 200 if res.get('ok') else 400


@app.post('/api/einkauf/bestellungen/<int:rec_id>/anreichern')
@_login_required
def api_einkauf_bestellung_anreichern(rec_id):
    """Reichert die Stammdaten aller Positionen einer Bestellung
    via Web-Treiber an (UTZ Mobile-API + HTML-Detail). Synchron –
    kann bei vielen Positionen einige Zehn-Sekunden dauern.
    Body: {ueberspringe_aktuelle?: bool} – default true, false = force.
    """
    body = request.get_json(silent=True) or {}
    skip = bool(body.get('ueberspringe_aktuelle', True))
    res = _einkauf.bestellung_anreichern(rec_id,
                                          ueberspringe_aktuelle=skip)
    return jsonify(**res), 200 if res.get('ok') else 502


@app.post('/api/einkauf/positionen/<int:pos_id>/anreichern')
@_login_required
def api_einkauf_position_anreichern(pos_id):
    """Reichert eine einzelne Position frisch an (force, ignoriert
    Cache-Alter) und liefert das Diagnose-Ergebnis zurueck – inkl.
    Detail-URL, HTTP-Status und HTML-Snippet, damit Parser-Probleme
    schnell erkennbar sind.
    """
    import time as _t
    from common import einkauf_lief_web as _web
    t_start = _t.monotonic()
    log.info('[pos-anreichern] start pos_id=%s', pos_id)
    # Position laden, um lief_rec_id + artnr zu bekommen
    try:
        from db import get_db
        with get_db() as cur:
            cur.execute("""
                SELECT bp.ARTIKEL_NR_LIEF, b.LIEF_REC_ID
                FROM XT_EINKAUF_BESTELLPOS bp
                JOIN XT_EINKAUF_BESTELLUNG b ON b.REC_ID = bp.BEST_REC_ID
                WHERE bp.REC_ID = %s
            """, (pos_id,))
            row = cur.fetchone()
    except Exception as e:
        log.exception('[pos-anreichern] db-error pos_id=%s', pos_id)
        return jsonify(ok=False, msg=str(e)), 500
    if not row:
        return jsonify(ok=False, msg='Position nicht gefunden.'), 404
    artnr = row.get('ARTIKEL_NR_LIEF') or ''
    lief_rec_id = row.get('LIEF_REC_ID')
    log.info('[pos-anreichern] pos_id=%s artnr=%s lief=%s -> web_artikel_diagnose',
             pos_id, artnr, lief_rec_id)

    diag = _web.web_artikel_diagnose(lief_rec_id, artnr)
    log.info('[pos-anreichern] pos_id=%s artnr=%s diagnose ok=%s msg=%s (%.1fs)',
             pos_id, artnr, diag.get('ok'), str(diag.get('msg'))[:80],
             _t.monotonic() - t_start)
    # Egal wie's lief: in den Cache schreiben (auch Fehler-Eintrag)
    parsed = ((diag.get('probe') or {}).get('parsed') or {}) \
              if diag.get('ok') else {}
    if diag.get('ok') and parsed:
        # Bild ggf. herunterladen
        bild_info = None
        if parsed.get('bild_url'):
            try:
                lief = _einkauf.holen(lief_rec_id) or {}
                bild_info = _einkauf._download_lief_bild(
                    parsed['bild_url'],
                    lief.get('KUERZEL') or '',
                    artnr)
                if bild_info:
                    parsed['bild_lokal'] = bild_info.get('rel_pfad') or ''
            except Exception:
                pass
        lief_art_rec_id = _einkauf.lief_artikel_speichern(
            lief_rec_id, artnr, parsed=parsed)
        if bild_info and lief_art_rec_id:
            try:
                binaer_id = _einkauf._bild_in_binaerdaten_speichern(
                    lief_art_rec_id, bild_info,
                    erst_name='Einkauf-UI')
                if binaer_id:
                    from common.db import get_db_transaction as _tx
                    with _tx() as cur:
                        cur.execute(
                            "UPDATE XT_EINKAUF_LIEF_ARTIKEL "
                            "SET BILD_BINAER_ID = %s WHERE REC_ID = %s",
                            (binaer_id, lief_art_rec_id))
            except Exception:
                pass
    elif not diag.get('ok'):
        _einkauf.lief_artikel_speichern(
            lief_rec_id, artnr, parsed=None,
            fehler=str(diag.get('msg') or 'unbekannt'))
    # diag hat bereits einen 'ok'-Key – nicht doppelt uebergeben
    # (sonst TypeError: multiple values for keyword argument).
    return jsonify(**diag)


@app.get('/api/einkauf/bestellungen/<int:rec_id>/cao-sync-plan')
@_login_required
def api_einkauf_bestellung_cao_sync_plan(rec_id):
    """Read-only-Vorschau: was wuerde der CAO-Sync (Phase 5/6) tun?
    KEIN Schreibvorgang in CAO-Tabellen."""
    res = _einkauf.cao_sync_plan(rec_id)
    return jsonify(**res), 200 if res.get('ok') else 404


@app.get('/api/einkauf/bestellungen/<int:rec_id>/cao-match')
@_login_required
def api_einkauf_bestellung_cao_match(rec_id):
    """Read-only-Vorschau: pro Position pruefen, ob in CAO ein Artikel
    existiert (per ARTIKEL_PREIS.PREIS_TYP=5, BESTNUM = UTZ-ArtNr).
    Gibt eine Liste von Match-Eintraegen zurueck (siehe
    common.einkauf.cao_match_positionen)."""
    e = _einkauf.bestellung_holen(rec_id)
    if not e:
        return jsonify(ok=False, msg='Nicht gefunden.'), 404
    matches = _einkauf.cao_match_positionen(rec_id)
    # Aggregat fuers UI: wie viele Matches/wie viele neu, EK-Diff-Summe
    n_total = len(matches)
    n_neu   = sum(1 for m in matches if m['match_quelle'] == 'kein')
    n_match = n_total - n_neu
    return jsonify(ok=True,
                   matches=matches,
                   summary={'total': n_total, 'match': n_match,
                            'neu': n_neu})


@app.route('/system/einkauf-poller')
@_login_required
def system_einkauf_poller_seite():
    """Status + Konfig-Uebersicht fuer den Einkauf-Poller-Daemon."""
    return render_template('system_einkauf_poller.html')


@app.get('/api/system/einkauf-poller')
@_login_required
def api_system_einkauf_poller():
    import system_einkauf_poller as _ep
    try:
        return jsonify(ok=True, **_ep.status())
    except Exception as e:
        log.exception('system_einkauf_poller status fehlgeschlagen')
        return jsonify(ok=False, msg=str(e)), 500


@app.post('/api/einkauf/bestellungen/abrufen')
@_login_required
def api_einkauf_bestellungen_abrufen():
    """Triggert manuelles Polling. Body optional:
       {'tage': 30, 'max_pro_lieferant': 30}.
    """
    body = request.get_json(silent=True) or {}
    try:
        tage = int(body.get('tage', 30))
        maxp = int(body.get('max_pro_lieferant', 30))
    except (TypeError, ValueError):
        return jsonify(ok=False, msg='tage/max muessen Zahlen sein'), 400
    res = _einkauf.gmail_fetch_neue_bestellungen(
        neuer_als_tage=tage,
        max_pro_lieferant=maxp,
        ma_id=session.get('ma_id'))
    return jsonify(**res), 200 if res.get('ok') else 502


# ── App starten ──────────────────────────────────────────────────

if __name__ == '__main__':
    log.info("Admin-App startet auf %s:%s (debug=%s)",
             config.HOST, config.PORT, config.DEBUG)
    if config.DEBUG:
        # Dev: Werkzeug-Dev-Server mit Auto-Reloader + Debugger
        app.run(host=config.HOST, port=config.PORT, debug=True)
    else:
        # Prod: Waitress (threaded WSGI, kein Reloader, stabil unter Last)
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT,
              threads=8, ident='cao-xt')
