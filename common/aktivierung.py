"""
CAO-XT – App-Aktivierungen (Dorfkern v2, Phase 7)

Feature-Gating auf App-Ebene. Die Tabelle ``DORFKERN_APP_AKTIVIERUNG``
enthaelt pro App (KIOSK/KASSE/ORGA/ADMIN) einen Eintrag mit
``AKTIV``-Flag und optionaler ``LIZENZ_BIS``-Angabe.

Primary use cases:
    * ``ist_aktiv(app)`` – schnelle Pruefung im App-Switcher und in
      Kontext-Processoren (wird aktiv gecached).
    * ``alle()``, ``set_aktiv()`` – fuer die Admin-UI.

Admin ist IMMER aktiv (nicht abschaltbar): Wer die Admin-App
deaktiviert, kann sie nicht mehr reaktivieren. Der Service erzwingt
das beim ``set_aktiv``-Aufruf.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import Any, Optional

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────────────────────

_VALID_APPS = ('KIOSK', 'KASSE', 'ORGA', 'ADMIN')
_IMMER_AKTIV = ('ADMIN',)     # nicht abschaltbar
_CACHE_TTL_S = 30.0

# Cache: app -> (aktiv_bool, expires_at)
_cache: dict[str, tuple[bool, float]] = {}
_cache_lock = threading.Lock()


# ── Schema ────────────────────────────────────────────────────────────────────

def run_migration() -> None:
    """Legt die Tabelle an. Idempotent."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_APP_AKTIVIERUNG (
                  APP         VARCHAR(32) NOT NULL PRIMARY KEY,
                  AKTIV       TINYINT(1)  NOT NULL DEFAULT 1,
                  LIZENZ_BIS  DATE        NULL,
                  HINWEIS     VARCHAR(255) NULL,
                  GEAENDERT_AM TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='App-Aktivierungen (Dorfkern v2, Phase 7)'
            """)
        log.info("Migration: DORFKERN_APP_AKTIVIERUNG geprueft/erstellt.")
    except Exception as exc:
        log.warning("Aktivierung-Migration fehlgeschlagen: %s", exc)


def seed_defaults() -> int:
    """Setzt Default-Eintraege (alle 4 Apps aktiv). ``INSERT IGNORE``.

    Returns: Anzahl neu angelegter Zeilen.
    """
    anzahl = 0
    for app in _VALID_APPS:
        try:
            with get_db_transaction() as cur:
                cur.execute(
                    "INSERT IGNORE INTO DORFKERN_APP_AKTIVIERUNG "
                    "(APP, AKTIV) VALUES (%s, 1)", (app,))
                anzahl += cur.rowcount
        except Exception as exc:
            log.warning("seed_defaults: %s fehlgeschlagen: %s", app, exc)
    if anzahl:
        log.info("seed_defaults: %d App-Aktivierungen angelegt.", anzahl)
    return anzahl


# ── Lese-Pfad (gecached) ──────────────────────────────────────────────────────

def _cache_put(app: str, aktiv: bool) -> None:
    with _cache_lock:
        _cache[app] = (aktiv, time.monotonic() + _CACHE_TTL_S)


def _cache_get(app: str) -> Optional[bool]:
    with _cache_lock:
        hit = _cache.get(app)
    if hit is None:
        return None
    aktiv, exp = hit
    if time.monotonic() >= exp:
        return None
    return aktiv


def invalidate(app: Optional[str] = None) -> None:
    """Verwirft den Cache (komplett oder fuer eine App)."""
    with _cache_lock:
        if app is None:
            _cache.clear()
        else:
            _cache.pop(app, None)


def ist_aktiv(app: str) -> bool:
    """Ist die App freigeschaltet? Beruecksichtigt ``LIZENZ_BIS``.

    - Admin ist immer aktiv (nicht abschaltbar).
    - Unbekannte App: ``False`` (fail-closed).
    - Bei DB-Fehler: ``False`` (fail-closed).
    - ``LIZENZ_BIS < heute``: ``False``.
    """
    if not app:
        return False
    app = app.upper()
    if app in _IMMER_AKTIV:
        return True
    if app not in _VALID_APPS:
        return False
    cached = _cache_get(app)
    if cached is not None:
        return cached
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT AKTIV, LIZENZ_BIS FROM DORFKERN_APP_AKTIVIERUNG "
                "WHERE APP = %s", (app,))
            row = cur.fetchone()
    except Exception as exc:
        log.warning("ist_aktiv(%s): DB-Fehler: %s", app, exc)
        return False
    if row is None:
        _cache_put(app, False)
        return False
    aktiv = bool(row.get('AKTIV'))
    lizenz_bis = row.get('LIZENZ_BIS')
    if aktiv and lizenz_bis is not None:
        if isinstance(lizenz_bis, date) and lizenz_bis < date.today():
            aktiv = False
    _cache_put(app, aktiv)
    return aktiv


# ── Admin-UI-Helfer ───────────────────────────────────────────────────────────

def alle() -> list[dict]:
    """Alle Eintraege (inkl. ADMIN). Stabile Reihenfolge."""
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT APP, AKTIV, LIZENZ_BIS, HINWEIS, GEAENDERT_AM "
                "FROM DORFKERN_APP_AKTIVIERUNG "
                "ORDER BY FIELD(APP, 'KIOSK','KASSE','ORGA','ADMIN')")
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("alle(): DB-Fehler: %s", exc)
        return []


def set_aktiv(app: str,
              aktiv: bool,
              lizenz_bis: Optional[Any] = None,
              hinweis: Optional[str] = None) -> None:
    """UPSERT eines App-Eintrags.

    - ADMIN kann nicht deaktiviert werden (Schutz vor Selbst-Aussperrung).
    - Cache fuer die betroffene App wird invalidiert.
    """
    app = (app or '').upper()
    if app not in _VALID_APPS:
        raise ValueError(f'APP muss {_VALID_APPS} sein, war {app!r}')
    if app in _IMMER_AKTIV and not aktiv:
        raise ValueError(f'{app} kann nicht deaktiviert werden.')
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO DORFKERN_APP_AKTIVIERUNG
              (APP, AKTIV, LIZENZ_BIS, HINWEIS)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              AKTIV       = VALUES(AKTIV),
              LIZENZ_BIS  = VALUES(LIZENZ_BIS),
              HINWEIS     = VALUES(HINWEIS)
        """, (app, 1 if aktiv else 0, lizenz_bis, hinweis))
    invalidate(app)
