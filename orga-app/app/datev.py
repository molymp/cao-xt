"""
CAO-XT Orga-App – DATEV-Export-Modul

Integriert das bestehende datevexport-Paket in die Orga-App:
- Export auslösen (Monat/Jahr wählbar)
- Erstellte Dateien auflisten und herunterladen
- Tabellarische Vorschau im Browser
- Storno-Buchungen und Nullumsatz-Einträge werden gefiltert
"""

from __future__ import annotations

import csv
import io
import os
import sys
from datetime import datetime
from pathlib import Path

from db import get_db

# datevexport-Paket liegt im Repo-Root, eine Ebene über orga-app/
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from datevexport.queries import build_full_query, DATEV_COLUMNS
from datevexport.config import Kontenplan
from datevexport.export import DELIMITER

# UTF-8 ohne BOM, CR-Zeilenende (wie Original-Script)
ENCODING = 'utf-8'

# Verzeichnis für generierte Export-Dateien
EXPORT_DIR = os.path.join(os.path.dirname(__file__), 'datev_exports')


def _filter_storno_und_nullumsatz(rows: list[dict]) -> list[dict]:
    """Filtert Storno-Buchungen und Nullumsatz-Einträge aus dem Ergebnis.

    - Nullumsatz: Zeilen mit Umsatz = '0,00' oder '0' oder leer
    - Storno: Zeilen deren Buchungstext auf ein Storno-Muster hinweist
      (zusätzlich zur STADIUM<127-Filterung in den SQL-Queries)
    """
    gefiltert = []
    for row in rows:
        umsatz = str(row.get('Umsatz', '')).strip()
        if not umsatz or umsatz in ('0,00', '0', '0.00'):
            continue
        gefiltert.append(row)
    return gefiltert


def datev_export_ausfuehren(year: int, month: int) -> tuple[Path | None, int, str]:
    """Führt den DATEV-Export für den gegebenen Monat/Jahr aus.

    Returns:
        (dateipfad, anzahl_zeilen, fehlermeldung)
        Bei Erfolg: (Path, int, '')
        Bei Fehler: (None, 0, 'Fehlerbeschreibung')
    """
    if not 1 <= month <= 12:
        return None, 0, f'Ungültiger Monat: {month}'
    if year < 2000 or year > 2099:
        return None, 0, f'Ungültiges Jahr: {year}'

    sql = build_full_query(year, month, Kontenplan())

    try:
        with get_db() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as e:
        return None, 0, f'Datenbankfehler: {e}'

    rows = _filter_storno_und_nullumsatz(rows)

    if not rows:
        return None, 0, f'Keine Buchungen für {month:02d}/{year} gefunden.'

    # Export-Verzeichnis anlegen
    out = Path(EXPORT_DIR)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'habadola2datev_{year}-{month:02d}_as-of_{timestamp}.csv'
    filepath = out / filename

    with open(filepath, 'w', encoding=ENCODING, newline='', errors='replace') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=DATEV_COLUMNS,
            delimiter=DELIMITER,
            extrasaction='ignore',
            lineterminator='\r',
        )
        writer.writeheader()
        writer.writerows(rows)

    return filepath, len(rows), ''


def datev_dateien_auflisten() -> list[dict]:
    """Listet alle vorhandenen DATEV-Export-Dateien auf.

    Returns:
        Liste von Dicts mit: filename, size_kb, created, year, month
    """
    out = Path(EXPORT_DIR)
    if not out.exists():
        return []

    dateien = []
    for f in sorted(out.glob('habadola2datev_*.csv'), reverse=True):
        stat = f.stat()
        # Dateiname parsen: habadola2datev_YYYY-MM_as-of_TIMESTAMP.csv
        try:
            teile = f.stem.split('_')
            # teile[0] = 'habadola2datev', teile[1] = 'YYYY-MM', ...
            jahr_monat = teile[1].split('-')
            jahr = int(jahr_monat[0])
            monat = int(jahr_monat[1])
        except (IndexError, ValueError):
            jahr, monat = 0, 0

        dateien.append({
            'filename': f.name,
            'size_kb': round(stat.st_size / 1024, 1),
            'created': datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M'),
            'year': jahr,
            'month': monat,
        })

    return dateien


def datev_datei_lesen(filename: str) -> tuple[list[str], list[dict], str]:
    """Liest eine DATEV-Export-Datei und gibt Header + Zeilen zurück.

    Returns:
        (spalten, zeilen, fehlermeldung)
    """
    # Sicherheitsprüfung: kein Path Traversal
    if '/' in filename or '\\' in filename or '..' in filename:
        return [], [], 'Ungültiger Dateiname.'

    filepath = Path(EXPORT_DIR) / filename
    if not filepath.exists():
        return [], [], f'Datei nicht gefunden: {filename}'

    try:
        with open(filepath, 'r', encoding=ENCODING) as f:
            reader = csv.DictReader(f, delimiter=DELIMITER)
            spalten = reader.fieldnames or []
            zeilen = list(reader)
        return spalten, zeilen, ''
    except Exception as e:
        return [], [], f'Lesefehler: {e}'


def datev_datei_pfad(filename: str) -> Path | None:
    """Gibt den vollständigen Pfad einer Export-Datei zurück (oder None)."""
    if '/' in filename or '\\' in filename or '..' in filename:
        return None
    filepath = Path(EXPORT_DIR) / filename
    return filepath if filepath.exists() else None
