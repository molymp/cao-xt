"""
CAO-XT – Rechtemodell (Dorfkern v2, Phase 6)

Granulares Zugriffsmodell aus 4 Rollen x N Permission-Objekten. Die
Rolle kommt aus der CAO-Tabelle ``BENUTZERRECHTE`` (Gruppenname per
MITARBEITER); die Zuordnung Rolle -> Objekt-Recht liegt in den
Dorfkern-eigenen Tabellen ``DORFKERN_PERMISSION_OBJEKT`` und
``DORFKERN_ROLLE_PERMISSION``.

Rollen (Stand v2): ``Administratoren``, ``Geschäftsführung``,
``Ladenleitung``, ``Mitarbeiter``. ``Administratoren`` sind implizit
auf allen Objekten berechtigt – **keine Eintraege in
DORFKERN_ROLLE_PERMISSION noetig**.

Beispiele::

    from common import permission
    if permission.hat_recht(ma_id, 'kiosk.backwaren'):
        ...
    if permission.hat_recht(ma_id, 'orga.schichtplan', recht='PFLEGEN'):
        ...

Fail-closed: Bei DB-Fehlern / unbekannter Rolle / nicht-existentem
Objekt gibt :func:`hat_recht` ``False`` zurueck.
"""
from __future__ import annotations

import logging
from typing import Optional

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────────────────────

_VALID_APPS = ('KIOSK', 'KASSE', 'ORGA', 'ADMIN')
_VALID_UNTERSCHEIDUNG = ('KEINE', 'LESE_PFLEGE')
_VALID_RECHTE = ('LESEN', 'PFLEGEN', 'BEIDES')

ROLLE_ADMIN = 'Administratoren'

# DB-RECHT -> Menge der Anfrage-RECHT, die damit abgedeckt sind.
# Strikt: ``PFLEGEN`` impliziert NICHT ``LESEN`` (zwei unabhaengige Bits
# zusammengefasst im Enum-Wert ``BEIDES``).
_DECKT_AB: dict[str, frozenset[str]] = {
    'LESEN':   frozenset({'LESEN'}),
    'PFLEGEN': frozenset({'PFLEGEN'}),
    'BEIDES':  frozenset({'LESEN', 'PFLEGEN', 'BEIDES'}),
}


# ── Schema ────────────────────────────────────────────────────────────────────

def run_migration() -> None:
    """Legt die beiden Permission-Tabellen an. Idempotent."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_PERMISSION_OBJEKT (
                  OBJEKT_KEY      VARCHAR(64) NOT NULL PRIMARY KEY,
                  APP             ENUM('KIOSK','KASSE','ORGA','ADMIN') NOT NULL,
                  BEZEICHNUNG     VARCHAR(128) NOT NULL,
                  BESCHREIBUNG    TEXT,
                  UNTERSCHEIDUNG  ENUM('KEINE','LESE_PFLEGE') NOT NULL
                                  DEFAULT 'KEINE',
                  INDEX idx_app (APP)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Permission-Objekte (Dorfkern v2, Phase 6)'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_ROLLE_PERMISSION (
                  ROLLE      VARCHAR(64) NOT NULL,
                  OBJEKT_KEY VARCHAR(64) NOT NULL,
                  RECHT      ENUM('LESEN','PFLEGEN','BEIDES') NOT NULL
                             DEFAULT 'BEIDES',
                  PRIMARY KEY (ROLLE, OBJEKT_KEY),
                  FOREIGN KEY (OBJEKT_KEY)
                    REFERENCES DORFKERN_PERMISSION_OBJEKT(OBJEKT_KEY)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                  INDEX idx_rolle (ROLLE)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Rolle-zu-Objekt-Zuordnung (Dorfkern v2, Phase 6)'
            """)
        log.info("Migration: DORFKERN_PERMISSION_* geprueft/erstellt.")
    except Exception as exc:
        log.warning("Permission-Migration fehlgeschlagen: %s", exc)


# Initialer Objekt-Katalog laut Release-Plan §5.4.
# Weitere Orga-Objekte werden pro Sidebar-Eintrag ergaenzt (TODO, Phase 7).
_SEED_OBJEKTE: list[tuple[str, str, str, str, str]] = [
    # (OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG, UNTERSCHEIDUNG)
    ('kiosk.zugriff',          'KIOSK',
     'Kiosk – Zugriff',
     'Grund-Zugriff auf die Kiosk-App.', 'KEINE'),
    ('kiosk.backwaren',        'KIOSK',
     'Kiosk – Backwaren',
     'Backwaren-Bestellung und -Liste im Kiosk.', 'KEINE'),
    ('kiosk.bestellverwaltung','KIOSK',
     'Kiosk – Bestellverwaltung',
     'Bestellverwaltung (anlegen, stornieren).', 'KEINE'),
    ('kiosk.mittagstisch',     'KIOSK',
     'Kiosk – Mittagstisch',
     'Mittagstisch-Ansicht und -Bestellung.', 'KEINE'),
    ('kiosk.stempeluhr',       'KIOSK',
     'Kiosk – Stempeluhr',
     'Zeiterfassungs-Stempeluhr am Kiosk.', 'KEINE'),

    ('kasse.zugriff',          'KASSE',
     'Kasse – Zugriff',
     'Grund-Zugriff auf die Kassen-App.', 'KEINE'),
    ('kasse.storno',           'KASSE',
     'Kasse – Storno',
     'Storno-Buchungen in der Kasse.', 'KEINE'),
    ('kasse.einstellungen',    'KASSE',
     'Kasse – Einstellungen',
     'Kasse-Einstellungen (Drucker, Terminal).', 'KEINE'),

    ('orga.zugriff',           'ORGA',
     'Orga – Zugriff',
     'Grund-Zugriff auf die Orga-App.', 'KEINE'),
    ('orga.schichtplan',       'ORGA',
     'Orga – Schichtplan',
     'Schichtplanung. Lese-/Pflege-Trennung.', 'LESE_PFLEGE'),
]


def seed_objekte() -> int:
    """Uebernimmt den Start-Katalog in ``DORFKERN_PERMISSION_OBJEKT``.

    ``INSERT IGNORE`` – Eintraege, die bereits existieren (etwa durch
    Admin-UI angepasst), werden nicht ueberschrieben.

    Returns: Anzahl neu angelegter Zeilen.
    """
    anzahl = 0
    for key, app, bez, beschr, unt in _SEED_OBJEKTE:
        try:
            with get_db_transaction() as cur:
                cur.execute("""
                    INSERT IGNORE INTO DORFKERN_PERMISSION_OBJEKT
                      (OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG,
                       UNTERSCHEIDUNG)
                    VALUES (%s, %s, %s, %s, %s)
                """, (key, app, bez, beschr, unt))
                anzahl += cur.rowcount
        except Exception as exc:
            log.warning("seed_objekte: %s fehlgeschlagen: %s", key, exc)
    if anzahl:
        log.info("seed_objekte: %d Permission-Objekte neu angelegt.", anzahl)
    return anzahl


# ── CAO-Rollen-Lookup ─────────────────────────────────────────────────────────

def rolle_von(ma_id: int) -> Optional[str]:
    """Ermittelt die CAO-Gruppe eines Mitarbeiters.

    Nutzt das gleiche Schema wie ``modules/orga/personal/auth.py``:
    ``BENUTZERRECHTE`` fuer den User (MODUL_ID=0, SUBMODUL_ID=0)
    joinen mit der Gruppen-Definitionszeile (USER_ID=-1) und dort
    den Gruppen-Namen aus ``MODUL_NAME`` lesen.

    Returns:
        Gruppenname (z.B. ``'Administratoren'``) oder ``None``, wenn
        Mitarbeiter nicht gefunden oder DB-Fehler.
    """
    if not ma_id:
        return None
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT br_grp.MODUL_NAME AS rolle
                  FROM BENUTZERRECHTE AS br_user
                  JOIN BENUTZERRECHTE AS br_grp
                    ON br_grp.GRUPPEN_ID  = br_user.GRUPPEN_ID
                   AND br_grp.USER_ID     = -1
                   AND br_grp.MODUL_ID    = 0
                   AND br_grp.SUBMODUL_ID = 0
                 WHERE br_user.USER_ID     = %s
                   AND br_user.MODUL_ID    = 0
                   AND br_user.SUBMODUL_ID = 0
                 LIMIT 1
            """, (int(ma_id),))
            row = cur.fetchone()
            if row and row.get('rolle'):
                return str(row['rolle']).strip()
    except Exception as exc:
        log.warning("rolle_von(%s): DB-Fehler: %s", ma_id, exc)
    return None


# ── Rechtepruefung ────────────────────────────────────────────────────────────

def hat_recht(ma_id: int, objekt_key: str,
              recht: str = 'BEIDES') -> bool:
    """Prueft, ob der Mitarbeiter das geforderte Recht auf ``objekt_key`` hat.

    Args:
        ma_id:       CAO-Mitarbeiter-ID.
        objekt_key:  Permission-Objekt (z.B. ``'kasse.storno'``).
        recht:       Gefordertes Recht (``'LESEN'``, ``'PFLEGEN'`` oder
                     ``'BEIDES'``). Default ``'BEIDES'`` – passt fuer
                     ``UNTERSCHEIDUNG='KEINE'``-Objekte.

    Returns:
        ``True``, wenn erlaubt; sonst ``False`` (fail-closed).
    """
    if recht not in _VALID_RECHTE:
        log.warning("hat_recht: ungueltiges Recht %r", recht)
        return False
    rolle = rolle_von(ma_id)
    if rolle is None:
        return False
    # Admin-Wildcard: keine DB-Lookup noetig
    if rolle == ROLLE_ADMIN:
        return True
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT RECHT FROM DORFKERN_ROLLE_PERMISSION "
                "WHERE ROLLE = %s AND OBJEKT_KEY = %s",
                (rolle, objekt_key))
            row = cur.fetchone()
    except Exception as exc:
        log.warning("hat_recht(%s, %s): DB-Fehler: %s",
                    ma_id, objekt_key, exc)
        return False
    if row is None:
        return False
    gewaehrt = str(row.get('RECHT') or '').upper()
    return recht in _DECKT_AB.get(gewaehrt, frozenset())


def erlaubte_objekte(ma_id: int,
                     app: Optional[str] = None) -> list[str]:
    """Listet alle OBJEKT_KEYs, auf die der Mitarbeiter Zugriff hat.

    Fuer ``Administratoren`` werden alle Objekte geliefert; sonst nur
    die, fuer die ein Eintrag in ``DORFKERN_ROLLE_PERMISSION`` existiert
    (egal mit welchem RECHT-Wert).

    Args:
        ma_id: CAO-Mitarbeiter-ID.
        app:   Optional auf ``KIOSK|KASSE|ORGA|ADMIN`` filtern.
    """
    rolle = rolle_von(ma_id)
    if rolle is None:
        return []
    try:
        with get_db() as cur:
            if rolle == ROLLE_ADMIN:
                sql = ("SELECT OBJEKT_KEY FROM DORFKERN_PERMISSION_OBJEKT")
                params: tuple = ()
                if app is not None:
                    sql += " WHERE APP = %s"
                    params = (app,)
            else:
                sql = ("SELECT rp.OBJEKT_KEY "
                       "FROM DORFKERN_ROLLE_PERMISSION rp "
                       "JOIN DORFKERN_PERMISSION_OBJEKT po "
                       "  ON po.OBJEKT_KEY = rp.OBJEKT_KEY "
                       "WHERE rp.ROLLE = %s")
                params = (rolle,)
                if app is not None:
                    sql += " AND po.APP = %s"
                    params = (rolle, app)
            sql += " ORDER BY OBJEKT_KEY"
            cur.execute(sql, params)
            return [r['OBJEKT_KEY'] for r in (cur.fetchall() or [])]
    except Exception as exc:
        log.warning("erlaubte_objekte(%s): DB-Fehler: %s", ma_id, exc)
        return []


# ── Admin-UI-Helfer ───────────────────────────────────────────────────────────

def objekte_alle(app: Optional[str] = None) -> list[dict]:
    """Alle Permission-Objekte (fuer die Admin-Matrix-UI)."""
    sql = ("SELECT OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG, "
           "UNTERSCHEIDUNG FROM DORFKERN_PERMISSION_OBJEKT")
    params: tuple = ()
    if app is not None:
        sql += " WHERE APP = %s"
        params = (app,)
    sql += " ORDER BY APP, OBJEKT_KEY"
    try:
        with get_db() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("objekte_alle(): DB-Fehler: %s", exc)
        return []


def rolle_permissions(rolle: str) -> dict[str, str]:
    """Liefert ``{OBJEKT_KEY: RECHT}`` fuer eine Rolle. Leer fuer Admin."""
    if rolle == ROLLE_ADMIN:
        return {}
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT OBJEKT_KEY, RECHT FROM DORFKERN_ROLLE_PERMISSION "
                "WHERE ROLLE = %s", (rolle,))
            return {r['OBJEKT_KEY']: str(r['RECHT'])
                    for r in (cur.fetchall() or [])}
    except Exception as exc:
        log.warning("rolle_permissions(%s): DB-Fehler: %s", rolle, exc)
        return {}


def set_rolle_permission(rolle: str, objekt_key: str, recht: str) -> None:
    """UPSERT eines Rolle-Objekt-Rechts (Admin-UI).

    Raises:
        ValueError: bei ungueltigem RECHT.
    """
    if recht not in _VALID_RECHTE:
        raise ValueError(
            f'RECHT muss {_VALID_RECHTE} sein, war {recht!r}')
    if rolle == ROLLE_ADMIN:
        # Admin-Permissions sind implizit – Schreibversuche sind ein Bug.
        log.info("set_rolle_permission: Admin-Zuweisung ignoriert (%s)",
                 objekt_key)
        return
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO DORFKERN_ROLLE_PERMISSION (ROLLE, OBJEKT_KEY, RECHT)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE RECHT = VALUES(RECHT)
        """, (rolle, objekt_key, recht))


def loesche_rolle_permission(rolle: str, objekt_key: str) -> None:
    """Entfernt eine Rolle-Objekt-Zuweisung (Entzug)."""
    with get_db_transaction() as cur:
        cur.execute(
            "DELETE FROM DORFKERN_ROLLE_PERMISSION "
            "WHERE ROLLE = %s AND OBJEKT_KEY = %s",
            (rolle, objekt_key))
