"""
CSV-Adapter fuer Backwaren.

Liest eine CSV-Datei mit Kopfzeile. Erwartete Spalten (alle Pflicht,
ausser wo angegeben):

    artikel_id   int
    artnum       str
    name         str
    preis_cent   int
    bestand      float   (optional – leer/fehlend → None)
    einheit      str     (optional – leer/fehlend → 'Stk')
    aktiv        int     (optional – 0/1; fehlend → 1)

Trennzeichen und Encoding sind konfigurierbar.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from .datenquelle import Artikel, BackwarenDatenquelle

log = logging.getLogger(__name__)


class CsvQuelle(BackwarenDatenquelle):
    """Datenquelle aus lokaler CSV-Datei."""
    TYP = 'CSV'

    def __init__(self,
                 pfad: str,
                 delimiter: str = ',',
                 encoding: str = 'utf-8') -> None:
        self.pfad = Path(pfad)
        self.delimiter = delimiter
        self.encoding = encoding

    def artikel_liste(self) -> list[Artikel]:
        if not self.pfad.exists():
            log.warning("CsvQuelle: Datei %s nicht gefunden.", self.pfad)
            return []
        ergebnisse: list[Artikel] = []
        with self.pfad.open('r', encoding=self.encoding, newline='') as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            for i, row in enumerate(reader, start=2):  # +1 Header, +1 1-basiert
                art = self._row_zu_artikel(row, zeile=i)
                if art is not None:
                    ergebnisse.append(art)
        return ergebnisse

    @staticmethod
    def _row_zu_artikel(row: dict, zeile: int) -> Optional[Artikel]:
        try:
            artikel_id = int(str(row['artikel_id']).strip())
            name = str(row['name']).strip()
            preis_cent = int(str(row['preis_cent']).strip())
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("CsvQuelle: Zeile %d uebersprungen (%s)", zeile, exc)
            return None
        bestand_raw = (row.get('bestand') or '').strip()
        bestand: Optional[float] = None
        if bestand_raw:
            try:
                bestand = float(bestand_raw)
            except ValueError:
                log.warning("CsvQuelle: Zeile %d ungueltiger Bestand %r",
                            zeile, bestand_raw)
        aktiv_raw = str(row.get('aktiv', '1')).strip()
        aktiv = aktiv_raw not in ('0', 'false', 'False', '')
        return Artikel(
            artikel_id=artikel_id,
            artnum=str(row.get('artnum') or '').strip(),
            name=name,
            preis_cent=preis_cent,
            bestand=bestand,
            einheit=(str(row.get('einheit') or '').strip() or 'Stk'),
            aktiv=aktiv,
        )
