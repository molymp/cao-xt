"""Kommandozeileninterface für den DATEV-Export."""

import argparse
import sys
from datetime import date

import pymysql
import pymysql.cursors

from .config import Kontenplan, load_db_config
from .export import write_csv
from .queries import execute_query


def parse_args(argv=None):
    today = date.today()
    parser = argparse.ArgumentParser(
        description='DATEV-Buchungsexport aus CAO-Faktura-Datenbank',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python -m datevexport --month 3 --year 2026
  python -m datevexport --month 3 --year 2026 --output /tmp/datev/
  python -m datevexport --config /etc/caoxt.ini --month 12 --year 2025
""",
    )
    parser.add_argument(
        '--config', default='config.ini',
        help='Pfad zur INI-Konfigurationsdatei (Standard: config.ini)',
    )
    parser.add_argument(
        '--month', type=int, default=today.month,
        metavar='MONAT',
        help=f'Exportmonat 1–12 (Standard: aktueller Monat = {today.month})',
    )
    parser.add_argument(
        '--year', type=int, default=today.year,
        metavar='JAHR',
        help=f'Exportjahr (Standard: aktuelles Jahr = {today.year})',
    )
    parser.add_argument(
        '--output', default='export',
        metavar='VERZEICHNIS',
        help='Ausgabeverzeichnis für die CSV-Datei (Standard: export/)',
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not 1 <= args.month <= 12:
        print(f'Fehler: --month muss zwischen 1 und 12 liegen, nicht {args.month}', file=sys.stderr)
        sys.exit(1)

    try:
        db_cfg = load_db_config(args.config)
    except (KeyError, FileNotFoundError) as e:
        print(f'Fehler beim Lesen der Konfiguration ({args.config}): {e}', file=sys.stderr)
        sys.exit(1)

    print(f'Verbinde mit {db_cfg.host}:{db_cfg.port} / {db_cfg.database} ...')
    try:
        connection = pymysql.connect(
            host=db_cfg.host,
            port=db_cfg.port,
            user=db_cfg.user,
            password=db_cfg.password,
            database=db_cfg.database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.Error as e:
        print(f'Datenbankverbindung fehlgeschlagen: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'Lese Buchungen {args.month:02d}/{args.year} ...')
    try:
        with connection:
            rows = execute_query(connection, args.year, args.month, Kontenplan())
    except pymysql.Error as e:
        print(f'Datenbankfehler bei der Abfrage: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'{len(rows)} Buchungszeilen gefunden.')

    if not rows:
        print('Keine Buchungen im gewählten Zeitraum – keine Datei erstellt.')
        sys.exit(0)

    outfile = write_csv(rows, args.year, args.month, args.output)
    print(f'CSV-Datei erstellt: {outfile}')


if __name__ == '__main__':
    main()
