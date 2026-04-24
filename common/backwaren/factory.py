"""
Factory fuer Backwaren-Datenquellen.

:func:`get_quelle` liest den konfigurierten Adapter-Typ aus
``DORFKERN_KONFIG`` (Schluessel ``backwaren.quelle.typ``) und erzeugt
die passende Instanz. Fallback: :class:`CaoMysqlQuelle`.

Konfigurations-Keys (alle in Kategorie ``BACKWAREN``)::

    backwaren.quelle.typ         'CAO' | 'CSV' | 'EXCEL' | 'GOOGLE_SHEET'
    backwaren.cao.warengruppe    z.B. '101'
    backwaren.csv.pfad           /pfad/zu/backwaren.csv
    backwaren.csv.delimiter      Default ','
    backwaren.csv.encoding       Default 'utf-8'
    backwaren.excel.pfad         /pfad/zu/backwaren.xlsx
    backwaren.excel.blatt        Default 'Artikel'
    backwaren.google_sheet.id    Sheet-ID
    backwaren.google_sheet.blatt Default 'Artikel'
    backwaren.google_sheet.sa    Pfad zum Service-Account-JSON (SECRET)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .cao_mysql import CaoMysqlQuelle
from .csv_quelle import CsvQuelle
from .datenquelle import BackwarenDatenquelle
from .excel import ExcelQuelle
from .google_sheet import GoogleSheetQuelle

log = logging.getLogger(__name__)

ADAPTER_TYPEN: tuple[str, ...] = ('CAO', 'CSV', 'EXCEL', 'GOOGLE_SHEET')


def _konfig_get(key: str, default: Any = None) -> Any:
    try:
        from common import konfig
    except Exception:
        return default
    try:
        return konfig.get(key, default)
    except Exception as exc:
        log.debug("konfig.get(%s) fehlgeschlagen: %s", key, exc)
        return default


def get_quelle(typ: Optional[str] = None) -> BackwarenDatenquelle:
    """Liefert den konfigurierten Adapter.

    Args:
        typ: Optional explizit setzen (fuer Tests). None → aus
             ``DORFKERN_KONFIG['backwaren.quelle.typ']`` lesen.

    Fallback bei unbekanntem/leerem Typ: :class:`CaoMysqlQuelle`.
    """
    if typ is None:
        typ = _konfig_get('backwaren.quelle.typ', 'CAO')
    typ = str(typ or 'CAO').upper()

    if typ == 'CSV':
        return CsvQuelle(
            pfad=_konfig_get('backwaren.csv.pfad', ''),
            delimiter=_konfig_get('backwaren.csv.delimiter', ',') or ',',
            encoding=_konfig_get('backwaren.csv.encoding', 'utf-8') or 'utf-8',
        )
    if typ == 'EXCEL':
        return ExcelQuelle(
            pfad=_konfig_get('backwaren.excel.pfad', ''),
            blatt=_konfig_get('backwaren.excel.blatt', 'Artikel') or 'Artikel',
        )
    if typ == 'GOOGLE_SHEET':
        return GoogleSheetQuelle(
            sheet_id=_konfig_get('backwaren.google_sheet.id', ''),
            blatt=_konfig_get('backwaren.google_sheet.blatt',
                              'Artikel') or 'Artikel',
            service_account_json=_konfig_get(
                'backwaren.google_sheet.sa', '') or '',
        )
    # Default / 'CAO'
    if typ != 'CAO':
        log.warning(
            "Unbekannter Backwaren-Adapter-Typ %r – verwende CAO.", typ)
    return CaoMysqlQuelle(
        warengruppe=_konfig_get('backwaren.cao.warengruppe', '101') or '101')
