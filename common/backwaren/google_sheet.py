"""
Google-Sheets-Adapter fuer Backwaren.

Stub-Implementierung. Der produktive Einsatz erfordert ein Service-
Account-JSON + Sheet-ID und folgt in v3. Das Interface ist festgelegt,
damit Konfiguration und Admin-UI in v2 bereits vorbereitet werden
koennen.
"""
from __future__ import annotations

from .datenquelle import Artikel, BackwarenDatenquelle


class GoogleSheetQuelle(BackwarenDatenquelle):
    """Liest Artikel aus einem Google Sheet. (v3-Feature – Stub in v2.)"""
    TYP = 'GOOGLE_SHEET'

    def __init__(self,
                 sheet_id: str,
                 blatt: str = 'Artikel',
                 service_account_json: str = '') -> None:
        self.sheet_id = sheet_id
        self.blatt = blatt
        self.service_account_json = service_account_json

    def artikel_liste(self) -> list[Artikel]:
        raise NotImplementedError(
            'GoogleSheetQuelle ist in v2 ein Stub; Implementierung folgt '
            'in v3 (gspread/service-account-basiert).')
