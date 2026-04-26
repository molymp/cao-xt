"""
CAO-XT – RFID-Tags fuer Mitarbeiter (Dorfkern v2)

Viele Mitarbeiter haben bereits einen RFID-Tag fuer die Alarmanlage. Diese
Tags werden hier als ALTERNATIVE zur klassischen Mitarbeiterkarte
(``KARTEN.GUID`` mit ``TYP='M'``) gespeichert. Beim Karten-Scan-Login
fragt ``common.auth.mitarbeiter_login_karte`` zuerst die KARTEN-Tabelle
ab und faellt dann auf ``XT_MITARBEITER_RFID`` zurueck. So funktioniert
ein Scan transparent egal ob Mitarbeiterkarte oder RFID-Tag.

Tabelle ``XT_MITARBEITER_RFID``:
    MA_ID                INT PK   – Verweis auf MITARBEITER.MA_ID (1:1)
    RFID_TAG             VARCHAR(64) NOT NULL UNIQUE
    GEAENDERT_AM         TIMESTAMP
    GEAENDERT_VON_MA_ID  INT NULL – wer hat den Tag eingetragen

Bewusst KEINE FOREIGN-KEY-Constraints auf MITARBEITER (CAO-Kompat:
CAO-Wartungs-Skripte mit MyISAM/Locks haben in der Vergangenheit FKs
auf CAO-Tabellen ueberrascht). Stattdessen pruefen wir die MA_ID
fachlich.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


_RFID_PATTERN = re.compile(r'^[A-Za-z0-9:\-]{4,64}$')


def _rfid_normalisieren(rfid: str) -> str:
    """Normalisiert einen RFID-Tag: trim + Großbuchstaben (Hex-Strings).

    Akzeptiert ``A:B:C:D``, ``ABCDEF12``, ``ab-cd-ef-12`` etc.
    """
    return (rfid or '').strip().upper()


def is_gueltig(rfid: str) -> bool:
    """Pruefe Format eines RFID-Tags (4–64 Zeichen aus [A-Z0-9:-])."""
    return bool(_RFID_PATTERN.match(_rfid_normalisieren(rfid)))


def run_migration() -> None:
    """Legt die Tabelle ``XT_MITARBEITER_RFID`` an. Idempotent."""
    from common.db import get_db
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS XT_MITARBEITER_RFID (
                    MA_ID                INT NOT NULL PRIMARY KEY,
                    RFID_TAG             VARCHAR(64) NOT NULL,
                    GEAENDERT_AM         TIMESTAMP NOT NULL
                                          DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
                    GEAENDERT_VON_MA_ID  INT NULL,
                    UNIQUE KEY uk_rfid (RFID_TAG)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='RFID-Tags fuer Mitarbeiter (Dorfkern XT)'
            """)
        log.info("Migration: XT_MITARBEITER_RFID geprueft/erstellt.")
    except Exception as exc:
        log.warning("RFID-Migration fehlgeschlagen: %s", exc)


def get_for_ma(ma_id: int) -> Optional[str]:
    """Liefert den eingetragenen RFID-Tag fuer einen Mitarbeiter (oder None)."""
    if not ma_id:
        return None
    from common.db import get_db
    with get_db() as cur:
        cur.execute(
            "SELECT RFID_TAG FROM XT_MITARBEITER_RFID WHERE MA_ID = %s",
            (int(ma_id),)
        )
        row = cur.fetchone()
    return row['RFID_TAG'] if row else None


def set_for_ma(ma_id: int, rfid: Optional[str],
               geaendert_von_ma_id: Optional[int] = None) -> None:
    """Setzt oder entfernt den RFID-Tag eines Mitarbeiters.

    - ``rfid=None`` oder leerer String: bestehender Eintrag wird geloescht.
    - Sonst: UPSERT (Format-Check vorher).

    Raises ``ValueError`` bei ungueltigem Format oder Tag-Kollision mit
    einem anderen Mitarbeiter.
    """
    from common.db import get_db_transaction
    if not ma_id:
        raise ValueError('MA_ID fehlt')
    if rfid is None or not rfid.strip():
        with get_db_transaction() as cur:
            cur.execute(
                "DELETE FROM XT_MITARBEITER_RFID WHERE MA_ID = %s",
                (int(ma_id),)
            )
        return
    norm = _rfid_normalisieren(rfid)
    if not is_gueltig(norm):
        raise ValueError(
            f'Ungueltiges RFID-Format: {rfid!r} (4–64 Zeichen, '
            f'erlaubt sind A–Z, 0–9, ":" und "-")')
    with get_db_transaction() as cur:
        # Auf Kollision pruefen (anderer MA hat denselben Tag)
        cur.execute(
            "SELECT MA_ID FROM XT_MITARBEITER_RFID WHERE RFID_TAG = %s",
            (norm,)
        )
        row = cur.fetchone()
        if row and int(row['MA_ID']) != int(ma_id):
            raise ValueError(
                f'RFID-Tag ist bereits einem anderen Mitarbeiter '
                f'zugeordnet (MA_ID={row["MA_ID"]}).')
        cur.execute(
            """INSERT INTO XT_MITARBEITER_RFID
                 (MA_ID, RFID_TAG, GEAENDERT_VON_MA_ID)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 RFID_TAG = VALUES(RFID_TAG),
                 GEAENDERT_VON_MA_ID = VALUES(GEAENDERT_VON_MA_ID)""",
            (int(ma_id), norm,
             int(geaendert_von_ma_id) if geaendert_von_ma_id else None)
        )


def finde_ma_per_rfid(rfid: str) -> Optional[dict]:
    """Sucht einen Mitarbeiter anhand seines RFID-Tags.

    Joinet ``MITARBEITER`` ueber ``MA_ID`` und liefert ein dict mit
    ``MA_ID``, ``LOGIN_NAME``, ``VNAME``, ``NAME`` zurueck (analog zu
    ``mitarbeiter_login_karte``). Returns ``None`` wenn nicht gefunden.

    Beruecksichtigt ``GUELTIG_BIS`` (ausgetretene Mitarbeiter werden
    ignoriert).
    """
    if not rfid:
        return None
    norm = _rfid_normalisieren(rfid)
    if not is_gueltig(norm):
        return None
    from common.db import get_db
    with get_db() as cur:
        cur.execute(
            """SELECT m.MA_ID, m.LOGIN_NAME, m.VNAME, m.NAME
               FROM XT_MITARBEITER_RFID r
               JOIN MITARBEITER m ON m.MA_ID = r.MA_ID
               WHERE r.RFID_TAG = %s
                 AND (m.GUELTIG_BIS IS NULL OR m.GUELTIG_BIS > NOW())""",
            (norm,)
        )
        return cur.fetchone()
