"""
Excel-Adapter fuer Backwaren (.xlsx).

Stub-Implementierung. Die Integration mit ``openpyxl`` folgt in v3.
Das Interface ist festgelegt, damit Adapter-konfigurierter Code in
v2 bereits auf die spaetere Erweiterung vorbereitet werden kann.
"""
from __future__ import annotations

from .datenquelle import Artikel, BackwarenDatenquelle


class ExcelQuelle(BackwarenDatenquelle):
    """Liest Artikel aus einer .xlsx-Datei. (v3-Feature – Stub in v2.)"""
    TYP = 'EXCEL'

    def __init__(self, pfad: str, blatt: str = 'Artikel') -> None:
        self.pfad = pfad
        self.blatt = blatt

    def artikel_liste(self) -> list[Artikel]:
        raise NotImplementedError(
            'ExcelQuelle ist in v2 ein Stub; Implementierung folgt in v3 '
            '(openpyxl-basiert).')
