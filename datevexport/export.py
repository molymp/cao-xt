"""CSV-Export im DATEV-Format (tab-delimitiert, ISO-8859-1)."""

import csv
import os
from datetime import datetime
from pathlib import Path

from .queries import DATEV_COLUMNS

ENCODING = 'utf-8'  # UTF-8 ohne BOM
DELIMITER = '\t'


def generate_filename(year: int, month: int) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return f'habadola2datev_{year}-{month}_as-of_{timestamp}.csv'


def write_csv(rows: list[dict], year: int, month: int, output_dir: str = 'export') -> Path:
    """Schreibt die Buchungszeilen als DATEV-CSV-Datei.

    Args:
        rows:       Ergebnisliste aus execute_query()
        year:       Export-Jahr
        month:      Export-Monat
        output_dir: Zielverzeichnis (wird angelegt falls nicht vorhanden)

    Returns:
        Pfad zur erzeugten Datei
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    filename = out / generate_filename(year, month)

    with open(filename, 'w', encoding=ENCODING, newline='', errors='replace') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=DATEV_COLUMNS,
            delimiter=DELIMITER,
            extrasaction='ignore',
            lineterminator='\r',
        )
        writer.writeheader()
        writer.writerows(rows)

    return filename
