"""
Import von Personalstammdaten aus einer ShiftJuggler-Export-CSV in
``XT_PERSONAL_MA`` + ``XT_PERSONAL_STUNDENSATZ_HIST``.

Nur fuer lokale Entwicklungs-/Testumgebung gedacht. Die CSV enthaelt
personenbezogene Daten und darf nicht im Repo eingecheckt werden
(siehe ``.gitignore``). Default-Pfad: ``modules/wawi/personal/_seed_local/``.

Aufruf (aus Repo-Root)::

    # Bootstrap aus dem Default-Verzeichnis (erste gefundene .csv):
    python3 -m modules.wawi.personal.tools.import_csv

    # Explizite Datei:
    python3 -m modules.wawi.personal.tools.import_csv \\
        --csv /absoluter/pfad/zur/export.csv

    # Als ausfuehrender Backoffice-User (default: 2 = Marc):
    python3 -m modules.wawi.personal.tools.import_csv --user 2

CSV-Spalten (ShiftJuggler-Export, Pflicht ist nur ``firstname``/``lastname``):
    externalEmployeeID → PERSONALNUMMER
    firstname, lastname, shorthand, birthday, email, alternativeEmail
    hourlyRate, dateEntry, dateLeave
    Strasse, PLZ, Stadt, "Telefon (privat)", "Mobil (privat)"
"""
from __future__ import annotations

import argparse
import csv
import glob
import logging
import os
import sys
from datetime import date, datetime


log = logging.getLogger(__name__)

_SEED_DIR_DEFAULT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '_seed_local')
)

# Hilfsfunktion: ShiftJuggler liefert '' oder YYYY-MM-DD.
def _parse_date(s: str | None) -> date | None:
    s = (s or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        log.warning('Unparsbares Datum: %r – uebersprungen', s)
        return None


def _parse_eur_to_ct(s: str | None) -> int | None:
    s = (s or '').strip()
    if not s:
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        log.warning('Unparsbarer Betrag: %r – uebersprungen', s)
        return None


def _find_default_csv() -> str | None:
    candidates = sorted(glob.glob(os.path.join(_SEED_DIR_DEFAULT, '*.csv')))
    return candidates[0] if candidates else None


def _row_zu_werte(row: dict) -> tuple[dict, int | None, date | None]:
    """Mappt eine CSV-Zeile auf (MA-Werte, Stundensatz_CT, Gueltig_ab)."""
    werte = {
        'PERSONALNUMMER': (row.get('externalEmployeeID') or row.get('id') or '').strip(),
        'VNAME':          row.get('firstname', '').strip(),
        'NAME':           row.get('lastname', '').strip(),
        'KUERZEL':        (row.get('shorthand') or '').strip().upper() or None,
        'GEBDATUM':       _parse_date(row.get('birthday')),
        'EMAIL':          row.get('email', '').strip() or None,
        'EMAIL_ALT':      row.get('alternativeEmail', '').strip() or None,
        'STRASSE':        row.get('Strasse', '').strip() or None,
        'PLZ':            row.get('PLZ', '').strip() or None,
        'ORT':            row.get('Stadt', '').strip() or None,
        'TELEFON':        (row.get('Telefon (privat)') or '').strip() or None,
        'MOBIL':          (row.get('Mobil (privat)') or '').strip() or None,
        'EINTRITT':       _parse_date(row.get('dateEntry')),
        'AUSTRITT':       _parse_date(row.get('dateLeave')),
        'BEMERKUNG':      None,
        'CAO_MA_ID':      None,
    }
    stundensatz_ct = _parse_eur_to_ct(row.get('hourlyRate'))
    gueltig_ab = werte['EINTRITT'] or date.today()
    return werte, stundensatz_ct, gueltig_ab


def importiere_csv(csv_path: str, benutzer_ma_id: int) -> tuple[int, int]:
    """Liest die CSV und legt MAs an. Gibt (angelegt, uebersprungen) zurueck."""
    # Erst nach Aufruf-Zeitpunkt importieren: common.db.init_pool
    # muss vorher konfiguriert sein.
    from modules.wawi.personal import models as m

    angelegt = 0
    uebersprungen = 0
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        for zeile, row in enumerate(reader, start=2):
            werte, satz_ct, gueltig_ab = _row_zu_werte(row)
            if not werte['VNAME'] or not werte['NAME']:
                log.info('Zeile %d: kein Name – uebersprungen', zeile)
                uebersprungen += 1
                continue
            if not werte['PERSONALNUMMER']:
                log.info('Zeile %d: keine Personalnummer – uebersprungen', zeile)
                uebersprungen += 1
                continue
            try:
                pers_id = m.ma_insert(werte, benutzer_ma_id)
            except Exception as e:
                log.warning('Zeile %d (%s %s): %s',
                            zeile, werte['VNAME'], werte['NAME'], e)
                uebersprungen += 1
                continue
            if satz_ct is not None and satz_ct > 0:
                m.stundensatz_setzen(pers_id, gueltig_ab, satz_ct,
                                     'Import ShiftJuggler', benutzer_ma_id)
            angelegt += 1
            log.info('Angelegt: PERS_ID=%d  %s %s (%s)',
                     pers_id, werte['VNAME'], werte['NAME'],
                     werte['PERSONALNUMMER'])
    return angelegt, uebersprungen


def _init_wawi_pool() -> None:
    """Initialisiert den common.db-Pool mit WaWi-Konfiguration.

    Wir emulieren, was wawi-app/app/db.py beim Start der Flask-App macht –
    ohne die App selbst zu booten."""
    repo_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')
    )
    sys.path.insert(0, repo_root)
    sys.path.insert(0, os.path.join(repo_root, 'wawi-app', 'app'))

    import config  # type: ignore
    from common.db import init_pool

    init_pool('wawi_import_pool', db_config={
        'host':     config.DB_HOST,
        'port':     config.DB_PORT,
        'name':     config.DB_NAME,
        'user':     config.DB_USER,
        'password': config.DB_PASSWORD,
    })


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', help='Pfad zur ShiftJuggler-Export-CSV')
    p.add_argument('--user', type=int, default=2,
                   help='CAO-MA_ID des ausfuehrenden Backoffice-Users (default: 2)')
    p.add_argument('--verbose', '-v', action='store_true')
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s  %(message)s',
    )

    csv_path = args.csv or _find_default_csv()
    if not csv_path:
        log.error('Keine CSV gefunden. Lege sie in %s ab oder nutze --csv.',
                  _SEED_DIR_DEFAULT)
        return 2
    if not os.path.isfile(csv_path):
        log.error('Datei nicht gefunden: %s', csv_path)
        return 2

    _init_wawi_pool()

    log.info('Importiere %s  (User MA_ID=%d)', csv_path, args.user)
    angelegt, uebersprungen = importiere_csv(csv_path, args.user)
    log.info('Fertig: %d angelegt, %d uebersprungen', angelegt, uebersprungen)
    return 0


if __name__ == '__main__':
    sys.exit(main())
