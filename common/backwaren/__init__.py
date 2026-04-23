"""
CAO-XT – Backwaren-Datenquellen (Dorfkern v2, Phase 8)

Abstrakte Adapter-Schicht fuer Kiosk/Backwaren. In v2 **nur lesend**
(siehe Release-Entscheidung #7); Schreiben frueheste v3.

Verwendung::

    from common.backwaren import get_quelle
    quelle = get_quelle()
    for art in quelle.artikel_liste():
        print(art.name, art.preis_cent)

Adapter-Auswahl laest sich ueber den ``DORFKERN_KONFIG``-Schluessel
``backwaren.quelle.typ`` steuern (Werte: ``CAO`` (Default), ``CSV``,
``EXCEL``, ``GOOGLE_SHEET``).
"""
from __future__ import annotations

from .datenquelle import Artikel, BackwarenDatenquelle
from .cao_mysql import CaoMysqlQuelle
from .csv_quelle import CsvQuelle
from .excel import ExcelQuelle
from .google_sheet import GoogleSheetQuelle
from .factory import get_quelle, ADAPTER_TYPEN

__all__ = [
    'Artikel',
    'BackwarenDatenquelle',
    'CaoMysqlQuelle',
    'CsvQuelle',
    'ExcelQuelle',
    'GoogleSheetQuelle',
    'get_quelle',
    'ADAPTER_TYPEN',
]
