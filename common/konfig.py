"""
CAO-XT – Konfigurations-API (DORFKERN_KONFIG-Tabelle)

Zentrale Key-Value-Konfiguration fuer Infrastruktur-Parameter
(DB, E-Mail, HACCP, Google-Integration, App-Feature-Flags etc.).

Phase-3-Scope (Dorfkern v2):
  * Schema-Anlage (:func:`run_migration`)
  * TTL-gecachter Lesezugriff (:func:`get`)
  * UPSERT-Schreibzugriff (:func:`set`)
  * Einmalige Uebernahme von caoxt.ini in die Tabelle (:func:`seed_aus_ini`)

Die Apps lesen spaeter (ab Phase 5/6) primaer ueber dieses Modul
statt ueber Env-Vars/ini. ENV bleibt als Notfall-Override im Bootstrap
(siehe ``common/config.py``).

Hinweis: ``TYP='SECRET'`` speichert aktuell Klartext. Die in Release-
Plan §5.1 vorgesehene symmetrische Verschluesselung mit Master-Key
aus ``caoxt.ini`` ist separate Arbeit (Phase 5 / Admin-UI).
"""
from __future__ import annotations

import configparser
import json
import logging
import os
import threading
import time
from typing import Any, Optional

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)

# Cache-TTL in Sekunden. 60 s = Admin-UI-Aenderung wird binnen 1 min
# auf allen Terminals sichtbar; DB-Last bei haeufigen Lesezugriffen bleibt niedrig.
_CACHE_TTL_S = 60.0

_cache: dict[str, tuple[Any, float]] = {}
_cache_lock = threading.Lock()

_VALID_TYPEN = ('STRING', 'INT', 'BOOL', 'JSON', 'SECRET')


def run_migration() -> None:
    """Legt ``DORFKERN_KONFIG`` an, falls nicht vorhanden. Idempotent.

    Wird vom App-Startup (Admin-App ist Eigentuemer) genau einmal aufgerufen.
    Fehler werden geloggt, nicht geworfen – App-Start bricht damit nicht ab,
    falls die DB voruebergehend unerreichbar ist.
    """
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_KONFIG (
                  SCHLUESSEL     VARCHAR(128) NOT NULL PRIMARY KEY,
                  WERT           TEXT,
                  TYP            ENUM('STRING','INT','BOOL','JSON','SECRET')
                                 NOT NULL DEFAULT 'STRING',
                  KATEGORIE      VARCHAR(64) NOT NULL,
                  BESCHREIBUNG   TEXT,
                  GEAENDERT_AM   DATETIME DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
                  GEAENDERT_VON  INT NULL,
                  INDEX idx_kategorie (KATEGORIE)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Zentrale Konfiguration (Dorfkern v2, Phase 3)'
            """)
        log.info("Migration: DORFKERN_KONFIG geprueft/erstellt.")
    except Exception as exc:
        log.warning("DORFKERN_KONFIG-Migration fehlgeschlagen: %s", exc)


def _cast(wert: Optional[str], typ: str) -> Any:
    """Wandelt einen DB-String gemaess ``TYP`` in einen Python-Wert.

    Robuster Cast: bei kaputtem JSON / nicht-parsebarem INT wird
    ``None`` geliefert statt zu werfen. So bleibt ein einzelner
    korrupter Config-Eintrag lokal und reisst nicht die ganze App mit.
    """
    if wert is None:
        return None
    if typ == 'INT':
        try:
            return int(wert)
        except (TypeError, ValueError):
            return None
    if typ == 'BOOL':
        return str(wert).strip().lower() in ('1', 'true', 'yes', 'ja', 'on')
    if typ == 'JSON':
        try:
            return json.loads(wert)
        except (TypeError, ValueError):
            return None
    # STRING, SECRET → Klartext
    return str(wert)


def _serialize(wert: Any, typ: str) -> str:
    """Wandelt einen Python-Wert in die DB-Repraesentation (TEXT)."""
    if wert is None:
        return ''
    if typ == 'BOOL':
        # Akzeptiert echte bool, '1'/'0', 'true'/'false' etc.
        if isinstance(wert, bool):
            return '1' if wert else '0'
        return '1' if str(wert).strip().lower() in (
            '1', 'true', 'yes', 'ja', 'on') else '0'
    if typ == 'INT':
        return str(int(wert))
    if typ == 'JSON':
        return json.dumps(wert, ensure_ascii=False)
    return str(wert)


def get(schluessel: str, default: Any = None) -> Any:
    """Liest einen Konfig-Wert – TTL-gecacht.

    Args:
        schluessel: Config-Key (z.B. ``'db.host'``, ``'email.smtp_user'``).
        default:    Rueckgabe, wenn der Key nicht existiert oder die
                    DB unerreichbar ist.

    Returns:
        Der typ-gecastete Wert, oder ``default``.
    """
    now = time.monotonic()
    with _cache_lock:
        eintrag = _cache.get(schluessel)
        if eintrag is not None and eintrag[1] > now:
            return eintrag[0]

    wert = default
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT WERT, TYP FROM DORFKERN_KONFIG WHERE SCHLUESSEL = %s",
                (schluessel,),
            )
            row = cur.fetchone()
    except Exception as exc:
        log.warning("konfig.get(%r): DB-Fehler: %s", schluessel, exc)
        return default

    if row is not None:
        wert = _cast(row.get('WERT'), row.get('TYP', 'STRING'))

    with _cache_lock:
        _cache[schluessel] = (wert, now + _CACHE_TTL_S)
    return wert


def set(schluessel: str, wert: Any, typ: str = 'STRING',
        kategorie: str = 'ALLGEMEIN',
        beschreibung: Optional[str] = None,
        ma_id: Optional[int] = None) -> None:
    """Schreibt einen Konfig-Wert (UPSERT) und invalidiert den Cache.

    Args:
        schluessel:   Config-Key.
        wert:         Python-Wert (wird gemaess ``typ`` serialisiert).
        typ:          ``'STRING' | 'INT' | 'BOOL' | 'JSON' | 'SECRET'``.
        kategorie:    Gruppierung fuer Admin-UI.
        beschreibung: Freitext fuer Admin-UI. Wird bei UPDATE nur gesetzt,
                      wenn der Aufruf einen Wert liefert (COALESCE).
        ma_id:        Wer hat's geaendert (``MITARBEITER.MA_ID``).
    """
    if typ not in _VALID_TYPEN:
        raise ValueError(
            f'Ungueltiger TYP {typ!r}. Erlaubt: {", ".join(_VALID_TYPEN)}')
    serialisiert = _serialize(wert, typ)
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO DORFKERN_KONFIG
              (SCHLUESSEL, WERT, TYP, KATEGORIE, BESCHREIBUNG, GEAENDERT_VON)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              WERT          = VALUES(WERT),
              TYP           = VALUES(TYP),
              KATEGORIE     = VALUES(KATEGORIE),
              BESCHREIBUNG  = COALESCE(VALUES(BESCHREIBUNG), BESCHREIBUNG),
              GEAENDERT_VON = VALUES(GEAENDERT_VON)
        """, (schluessel, serialisiert, typ, kategorie, beschreibung, ma_id))
    with _cache_lock:
        _cache.pop(schluessel, None)


def invalidate(schluessel: Optional[str] = None) -> None:
    """Verwirft einen einzelnen Eintrag oder den gesamten Cache.

    Aufruf-Muster: nach externen DB-Aenderungen (z.B. direkter SQL-Fix
    ausserhalb der App), oder wenn die App einen Config-Bulk-Import
    gemacht hat.
    """
    with _cache_lock:
        if schluessel is None:
            _cache.clear()
        else:
            _cache.pop(schluessel, None)


def alle(kategorie: Optional[str] = None) -> list[dict]:
    """Liefert alle Config-Eintraege (fuer Admin-UI).

    Args:
        kategorie: Optional auf eine Kategorie filtern.

    Returns:
        Liste von dicts mit ``SCHLUESSEL, WERT, TYP, KATEGORIE,
        BESCHREIBUNG, GEAENDERT_AM, GEAENDERT_VON``. ``SECRET``-Werte
        werden NICHT maskiert – der Aufrufer ist fuer die Anzeige
        verantwortlich.
    """
    sql = ("SELECT SCHLUESSEL, WERT, TYP, KATEGORIE, BESCHREIBUNG, "
           "GEAENDERT_AM, GEAENDERT_VON FROM DORFKERN_KONFIG")
    params: tuple = ()
    if kategorie is not None:
        sql += " WHERE KATEGORIE = %s"
        params = (kategorie,)
    sql += " ORDER BY KATEGORIE, SCHLUESSEL"
    try:
        with get_db() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("konfig.alle(%r): DB-Fehler: %s", kategorie, exc)
        return []


# ── Seed aus caoxt.ini ────────────────────────────────────────────────────────

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_INI_PATH = os.path.join(_REPO_ROOT, 'caoxt', 'caoxt.ini')

# Sektion → (KATEGORIE,
#            {ini_key: 'INT'|'BOOL'|...},
#            {ini_key: 'alternativer.schluessel'})
# Wird ein ini_key nicht im rename-Dict gelistet, ist der DB-Schluessel
# '<kategorie.lower()>.<ini_key>'.
_SEED_MAPPING: dict[str, tuple[str, dict[str, str], dict[str, str]]] = {
    'Datenbank': ('DB', {
        'db_port': 'INT',
    }, {
        'db_loc':  'db.host',
        'db_port': 'db.port',
        'db_name': 'db.name',
        'db_user': 'db.user',
        'db_pass': 'db.password',  # Typ wird automatisch SECRET
        'db_pref': 'db.prefix',
    }),
    'Email': ('EMAIL', {
        'smtp_port': 'INT',
        'smtp_tls':  'BOOL',
        'dev_mode':  'BOOL',
    }, {}),
    'Umgebung': ('UMGEBUNG', {}, {
        'xt_environment': 'umgebung.modus',
    }),
    'Installation': ('INSTALLATION', {}, {}),
}


def seed_aus_ini(ini_path: str = _INI_PATH) -> int:
    """Uebertraegt Werte aus ``caoxt.ini`` einmalig in ``DORFKERN_KONFIG``.

    Verwendet ``INSERT IGNORE`` – bereits existierende Schluessel werden
    NICHT ueberschrieben, Admin-UI-Aenderungen bleiben erhalten.

    Args:
        ini_path: Pfad zur ini-Datei. Default: ``caoxt/caoxt.ini`` im Repo.

    Returns:
        Anzahl neu eingefuegter Zeilen (0 bei leer/nicht-vorhanden).
    """
    ini = configparser.ConfigParser()
    gelesen = ini.read(ini_path)
    if not gelesen:
        log.info("seed_aus_ini: keine ini unter %s gefunden.", ini_path)
        return 0

    anzahl = 0
    for sektion, (kategorie, typ_map, rename) in _SEED_MAPPING.items():
        if not ini.has_section(sektion):
            continue
        for key, raw in ini.items(sektion):
            if raw is None or str(raw).strip() == '':
                continue
            schluessel = rename.get(key, f'{kategorie.lower()}.{key}')
            typ = typ_map.get(key, 'STRING')
            # Pass/Secret-Heuristik: alles mit 'pass' oder 'secret' im
            # Schluessel als SECRET speichern (auch wenn noch nicht verschluesselt).
            if 'pass' in key.lower() or 'secret' in key.lower():
                typ = 'SECRET'
            try:
                with get_db_transaction() as cur:
                    cur.execute("""
                        INSERT IGNORE INTO DORFKERN_KONFIG
                          (SCHLUESSEL, WERT, TYP, KATEGORIE, BESCHREIBUNG)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (schluessel, str(raw).strip(), typ, kategorie,
                          f'Uebernommen aus caoxt.ini [{sektion}] {key}'))
                    anzahl += cur.rowcount
            except Exception as exc:
                log.warning("seed_aus_ini: %s fehlgeschlagen: %s",
                            schluessel, exc)
    if anzahl:
        log.info("seed_aus_ini: %d Eintraege neu angelegt.", anzahl)
    return anzahl
