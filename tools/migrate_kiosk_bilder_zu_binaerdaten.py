"""One-Shot-Migration: Filesystem-Kiosk-Produktbilder -> CAO BINAERDATEN.

Migriert die Bilder unter ``kiosk-app/app/produktbilder/<id>.<ext>``
nach ``BINAERDATEN`` mit ``MODUL_ID=1020`` (Artikel) +
``REFERENZ_ID=<artikel_id>`` und ``PRIMAER=1``. Damit erscheinen sie
sofort im CAO-Faktura-Artikelstamm-Reiter "Dateilinks".

Die ``XT_KIOSK_PRODUKTE.bild_pfad``-Spalte wird auf
``/binaer/<binaer_rec_id>`` umgestellt, sodass alle Templates
(``a.bild_pfad`` direkt im ``<img src>``) sofort umschalten.

Idempotent: Re-Runs ueberspringen Eintraege, deren ``bild_pfad``
bereits auf ``/binaer/`` zeigt UND deren BLOB schon vorliegt.

Usage::

    python3 tools/migrate_kiosk_bilder_zu_binaerdaten.py            # echte Ausfuehrung
    python3 tools/migrate_kiosk_bilder_zu_binaerdaten.py --dry-run  # nur Analyse
    python3 tools/migrate_kiosk_bilder_zu_binaerdaten.py --limit 10
"""
from __future__ import annotations

import argparse
import logging
import os
import re
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

# Erlaubte Endungen — gleich wie in admin-app (ERLAUBTE_BILD_ENDUNGEN).
_ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp'}
_FNAME_RE = re.compile(r'^(\d+)\.([a-zA-Z]+)$')


def _bild_basis() -> str:
    return os.environ.get('PRODUKTBILDER_DIR') or os.path.join(
        _REPO_ROOT, 'kiosk-app', 'app', 'produktbilder')


def _migriere(*, dry_run: bool, limit: int | None) -> dict:
    bild_basis = _bild_basis()
    log.info("Filesystem-Wurzel: %s", bild_basis)
    if not os.path.isdir(bild_basis):
        log.error("Wurzel existiert nicht: %s", bild_basis)
        return {'fehler': 1, 'erfolg': 0, 'ueberspr': 0}

    if not dry_run:
        bd.run_migration()
        typ_id = bd.typ_id_holen(bd.TYP_NAME_PRODUKTBILD)
    else:
        typ_id = 0

    # Liste aller <id>.<ext>-Dateien direkt im produktbilder-Ordner.
    kandidaten: list[tuple[int, str, str]] = []
    for entry in sorted(os.listdir(bild_basis)):
        m = _FNAME_RE.match(entry)
        if not m:
            continue
        ext = m.group(2).lower()
        if ext not in _ALLOWED_EXT:
            continue
        full = os.path.join(bild_basis, entry)
        if not os.path.isfile(full):
            continue
        kandidaten.append((int(m.group(1)), entry, full))

    log.info("Kandidaten: %d", len(kandidaten))

    if limit:
        kandidaten = kandidaten[:int(limit)]

    erfolg, ueberspr, fehler = 0, 0, 0
    for artikel_id, dateiname, pfad in kandidaten:
        # Schon migriert? Pruefen via XT_KIOSK_PRODUKTE.bild_pfad
        # UND BINAERDATEN-PRIMAER-Existenz.
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT bild_pfad FROM XT_KIOSK_PRODUKTE WHERE id=%s
                """, (artikel_id,))
                row = cur.fetchone()
        except Exception as exc:
            log.warning("ID %s: DB-Lookup fehlgeschlagen: %s",
                        artikel_id, exc)
            fehler += 1
            continue

        bp = (row or {}).get('bild_pfad') or ''
        existing = bd.binaer_primaer_holen(
            bd.MODUL_ID_ARTIKEL, artikel_id) if not dry_run else None
        if bp.startswith('/binaer/') and existing:
            log.info("ID %s: bereits migriert (bild_pfad=%s) — skip",
                     artikel_id, bp)
            ueberspr += 1
            continue

        try:
            with open(pfad, 'rb') as fh:
                daten = fh.read()
        except OSError as exc:
            log.warning("ID %s: Lesefehler %s: %s",
                        artikel_id, pfad, exc)
            fehler += 1
            continue

        log.info("ID %s: %s (%d Bytes) -> BINAERDATEN MODUL_ID=1020",
                 artikel_id, dateiname, len(daten))
        if dry_run:
            erfolg += 1
            continue

        try:
            binaer_id = bd.binaer_primaer_ersetzen(
                modul_id=bd.MODUL_ID_ARTIKEL,
                referenz_id=artikel_id,
                binaer_typ=typ_id,
                pfad=f'/produktbilder/{dateiname}',
                datei=dateiname,
                daten=daten,
                erst_name='migrate-script',
            )
            with get_db_transaction() as cur:
                # bild_pfad auf /binaer/<id> setzen. INSERT, falls
                # XT_KIOSK_PRODUKTE-Zeile fehlt (defensive).
                cur.execute("""
                    SELECT id FROM XT_KIOSK_PRODUKTE WHERE id=%s
                """, (artikel_id,))
                if cur.fetchone():
                    cur.execute("""
                        UPDATE XT_KIOSK_PRODUKTE
                           SET bild_pfad = %s
                         WHERE id = %s
                    """, (f'/binaer/{binaer_id}', artikel_id))
                else:
                    cur.execute("""
                        INSERT INTO XT_KIOSK_PRODUKTE
                          (id, bild_pfad, aktiv)
                        VALUES (%s, %s, 1)
                    """, (artikel_id, f'/binaer/{binaer_id}'))
            erfolg += 1
        except Exception as exc:
            log.exception("ID %s: Migration fehlgeschlagen: %s",
                          artikel_id, exc)
            fehler += 1

    return {'kandidaten': len(kandidaten), 'erfolg': erfolg,
            'uebersprungen': ueberspr, 'fehler': fehler,
            'dry_run': dry_run}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run', action='store_true',
                   help='Nur analysieren, keine Schreibvorgaenge.')
    p.add_argument('--limit', type=int, default=None,
                   help='Maximal so viele Eintraege migrieren.')
    args = p.parse_args()

    cfg = load_db_config('XT')
    init_pool('migrate_kiosk_pool', db_config=cfg)
    log.info("DB: %s@%s:%s/%s", cfg['user'], cfg['host'],
             cfg['port'], cfg['name'])

    res = _migriere(dry_run=args.dry_run, limit=args.limit)
    log.info("Ergebnis: %s", res)
    return 0 if res['fehler'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
