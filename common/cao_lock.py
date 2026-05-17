"""
CAO-Record-Lock — exakt wie cao_faktura.exe.

CAO Faktura nimmt beim Bearbeiten eines Datensatzes einen MySQL-
Advisory-Lock::

    GET_LOCK('<dbname>_MOD_<MODUL_ID>_RECID_<REC_ID>', <timeout>)
    … schreiben …
    RELEASE_LOCK('<dbname>_MOD_<MODUL_ID>_RECID_<REC_ID>')

(belegt im SQL-Trace 2026-05-17: ``cao_XT_DEV_MOD_1010_RECID_432``;
``<dbname>`` = das verbundene Schema, z. B. ``cao_XT_DEV``).

Damit Dorfkern-Schreibvorgänge sich gegen ein gleichzeitiges
CAO-Faktura-Speichern **und** gegen sich selbst (zwei Tabs/User,
Poller + UI) gegenseitig ausschließen, MUSS derselbe Lockname mit
derselben ``MODUL_ID`` benutzt werden — ein falscher Name = gar
keine Sperre.

Wichtig: ``GET_LOCK``/``RELEASE_LOCK`` sind **connection-scoped**.
Der Lock MUSS auf demselben Cursor/derselben Connection genommen
und freigegeben werden, auf der auch geschrieben wird.
"""
from __future__ import annotations

from contextlib import contextmanager

from common.db import effektive_db_config


# ── Lock-MODUL_IDs je Vorgang (aus echten cao_faktura.exe-SQL-Traces,
# 2026-05-17 — NICHT geraten). Achtung: dies sind *Lock*-MODUL_IDs;
# sie sind NICHT zwingend identisch mit dem BINAERDATEN/Rechte-Enum
# (EKBESTELL=2060 existiert in keinem Enum). Daher hier eigene
# Konstanten statt Re-Use von common.binaerdaten.
LOCK_MOD_ADRESSEN     = 1010   # ADRESSEN.REC_ID
LOCK_MOD_ARTIKEL      = 1020   # ARTIKEL.REC_ID
LOCK_MOD_LIEFERSCHEIN = 2030   # LIEFERSCHEIN.REC_ID
LOCK_MOD_RECHNUNG     = 2040   # JOURNAL.REC_ID (QUELLE=13)
LOCK_MOD_EINKAUF      = 2050   # JOURNAL.REC_ID (QUELLE=15)
LOCK_MOD_EKBESTELL    = 2060   # EKBESTELL.REC_ID (nicht im Enum!)
LOCK_MOD_WARENEINGANG = 2065   # EKEINGANG.REC_ID

# ── Dorfkern-INTERNE Lock-MODUL_IDs (>=90000, analog zum XT-Bereich
# in reference_cao_binaerdaten). NICHT CAO-kompatibel: CAO Faktura
# kennt diese XT-Tabellen nicht und nimmt darauf keinen Lock. Zweck:
# Dorfkern-vs-Dorfkern (zwei Clients/Poller) — z. B. Schutz von
# Sync-Create-Pfaden mit Check-then-Act-Guard gegen Doppel-Anlage.
LOCK_MOD_XT_EK_SYNC = 92050    # XT_EINKAUF_BESTELLUNG.REC_ID (Quelle
                               # des cao_sync_ekbestell-Creates)

# CAO Faktura nimmt den Lock durchgängig mit Timeout 3 s
# (``GET_LOCK(name, 3)`` in allen Traces). Default daran ausrichten.
DEFAULT_TIMEOUT = 3


class CaoLockBelegt(RuntimeError):
    """Der Datensatz wird gerade (von CAO Faktura oder Dorfkern)
    bearbeitet — Lock nicht erhalten."""


def _dbname() -> str:
    try:
        cfg = effektive_db_config()
        return (cfg.get('name') or cfg.get('database')
                or cfg.get('db') or 'cao')
    except Exception:
        return 'cao'


def lock_name(modul_id: int, rec_id: int) -> str:
    """CAO-kompatibler Lockname ``<db>_MOD_<modul>_RECID_<id>``."""
    return f'{_dbname()}_MOD_{int(modul_id)}_RECID_{int(rec_id)}'


@contextmanager
def cao_record_lock(cur, modul_id: int, rec_id: int,
                    *, timeout: int = DEFAULT_TIMEOUT):
    """Hält den CAO-Record-Lock auf ``cur`` (= dieselbe Connection,
    auf der geschrieben wird) für die Dauer des ``with``-Blocks.

    Raises :class:`CaoLockBelegt`, wenn der Lock nicht innerhalb
    ``timeout`` Sekunden frei wird (anderer Bearbeiter).
    """
    name = lock_name(modul_id, rec_id)
    cur.execute("SELECT GET_LOCK(%s, %s) AS L", (name, int(timeout)))
    row = cur.fetchone()
    got = row.get('L') if isinstance(row, dict) else (row or [None])[0]
    if int(got or 0) != 1:
        raise CaoLockBelegt(
            f'Datensatz {modul_id}/{rec_id} ist gesperrt '
            f'(anderer Bearbeiter in CAO Faktura oder Dorfkern).')
    try:
        yield name
    finally:
        try:
            cur.execute("SELECT RELEASE_LOCK(%s)", (name,))
            cur.fetchone()
        except Exception:
            pass
