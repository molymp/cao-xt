"""One-Shot-Migration: Filesystem-Lieferantenbilder -> CAO BINAERDATEN.

Liest jede ``XT_EINKAUF_LIEF_ARTIKEL``-Zeile mit ``BILD_LOKAL is not
NULL`` und ``BILD_BINAER_ID is NULL`` ein, laedt das File von
``kiosk-app/app/produktbilder/<rel_pfad>`` und schreibt es als BLOB
in ``BINAERDATEN`` (XT-Cache MODUL_ID 91020). Der zugehoerige
``BILD_BINAER_ID`` wird zurueckgeschrieben.

Idempotent: Re-Runs ueberspringen Eintraege mit gesetztem
``BILD_BINAER_ID``.

Usage::

    python3 tools/migrate_lief_bilder_zu_binaerdaten.py            # echte Ausfuehrung
    python3 tools/migrate_lief_bilder_zu_binaerdaten.py --dry-run  # nur Analyse
    python3 tools/migrate_lief_bilder_zu_binaerdaten.py --limit 50 # nur 50 Eintraege

Filesystem-Bilder werden NICHT geloescht — sie bleiben als Cache
liegen, bis wir den Filesystem-Pfad endgueltig retiren.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from common.config import load_db_config  # noqa: E402
from common.db import init_pool, get_db, get_db_transaction  # noqa: E402
from common import binaerdaten as bd  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger(__name__)


def _bild_basis() -> str:
    """Filesystem-Wurzel der Lieferantenbilder."""
    return os.environ.get('PRODUKTBILDER_DIR') or os.path.join(
        _REPO_ROOT, 'kiosk-app', 'app', 'produktbilder')


def _migriere(*, dry_run: bool, limit: int | None) -> dict:
    bild_basis = _bild_basis()
    log.info("Filesystem-Wurzel: %s", bild_basis)

    # BINAER_TYPEN ggf. initial befuellen (idempotent).
    if not dry_run:
        bd.run_migration()

    sql = ("SELECT REC_ID, LIEF_REC_ID, ARTIKEL_NR_LIEF, BILD_LOKAL, "
           "BILD_URL "
           "FROM XT_EINKAUF_LIEF_ARTIKEL "
           "WHERE BILD_LOKAL IS NOT NULL AND TRIM(BILD_LOKAL) <> '' "
           "  AND (BILD_BINAER_ID IS NULL OR BILD_BINAER_ID = 0) "
           "ORDER BY REC_ID")
    if limit:
        sql += f" LIMIT {int(limit)}"

    erfolg, fehlt, fehler = 0, 0, 0
    with get_db() as cur:
        cur.execute(sql)
        rows = cur.fetchall() or []
    log.info("Kandidaten: %d", len(rows))

    typ_id = bd.typ_id_holen(bd.TYP_NAME_PRODUKTBILD) if not dry_run else 0

    for r in rows:
        rec_id = int(r['REC_ID'])
        rel = (r.get('BILD_LOKAL') or '').lstrip('/')
        absolut = os.path.join(bild_basis, rel)
        if not os.path.isfile(absolut):
            log.warning("LIEF_ART %s: Datei fehlt: %s", rec_id, absolut)
            fehlt += 1
            continue
        try:
            with open(absolut, 'rb') as fh:
                daten = fh.read()
        except OSError as exc:
            log.warning("LIEF_ART %s: Lesefehler %s: %s",
                        rec_id, absolut, exc)
            fehler += 1
            continue

        datei = os.path.basename(rel)
        log.info("LIEF_ART %s: %s (%d Bytes) -> BINAERDATEN",
                 rec_id, datei, len(daten))

        if dry_run:
            erfolg += 1
            continue

        try:
            binaer_id = bd.binaer_speichern_oder_ersetzen(
                modul_id=bd.MODUL_ID_XT_LIEF_ARTIKEL_CACHE,
                referenz_id=rec_id,
                binaer_typ=typ_id,
                pfad=r.get('BILD_URL') or rel,
                datei=datei,
                daten=daten,
                primaer=True,
                erst_name='migrate-script',
            )
            with get_db_transaction() as cur:
                cur.execute(
                    "UPDATE XT_EINKAUF_LIEF_ARTIKEL "
                    "SET BILD_BINAER_ID = %s WHERE REC_ID = %s",
                    (binaer_id, rec_id))
            erfolg += 1
        except Exception as exc:
            log.exception("LIEF_ART %s: Migration fehlgeschlagen: %s",
                          rec_id, exc)
            fehler += 1

    return {'kandidaten': len(rows), 'erfolg': erfolg,
            'datei_fehlt': fehlt, 'fehler': fehler,
            'dry_run': dry_run}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run', action='store_true',
                   help='Nur analysieren, keine Schreibvorgaenge.')
    p.add_argument('--limit', type=int, default=None,
                   help='Maximal so viele Eintraege migrieren.')
    args = p.parse_args()

    cfg = load_db_config('XT')
    init_pool('migrate_pool', db_config=cfg)
    log.info("DB: %s@%s:%s/%s", cfg['user'], cfg['host'],
             cfg['port'], cfg['name'])

    res = _migriere(dry_run=args.dry_run, limit=args.limit)
    log.info("Ergebnis: %s", res)
    return 0 if res['fehler'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
