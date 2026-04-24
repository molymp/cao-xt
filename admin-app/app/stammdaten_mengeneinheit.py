"""
CAO-Stammdaten: Mengeneinheit – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``MENGENEINHEIT`` fuer die Admin-Ansicht. In
cao_admin.exe findet sich dieselbe Liste unter
*Einstellungen → Mengeneinheiten*.

Schema (CAO-Faktura 1.5)::

    REC_ID        int          PK, ID
    BEZEICHNUNG   varchar(16)  angezeigter Name ('Stueck', 'Kg', 'Liter')
    ME_CODE       varchar(8)   EN16931-UNECE-Code (H87=Stueck, KGM=kg, LTR=l)
    KURZ_NAME     varchar(8)   (optional, nicht immer gepflegt)

Der EN16931-Code wird fuer Pflicht-Rechnungen nach ZUGFeRD/XRechnung
benoetigt; leere Codes markieren wir in der UI als ``(fehlt)``.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)


# Kurzreferenz der wichtigsten UNECE-Codes – rein kosmetisch, damit die
# Anzeige ``H87 (Stueck)`` zeigen kann statt nur ``H87``. Eine
# vollstaendige Pflege ist Sache von CAO.
_UNECE_KLARNAMEN: dict[str, str] = {
    'H87': 'Stueck',
    'KGM': 'Kilogramm',
    'GRM': 'Gramm',
    'LTR': 'Liter',
    'MLT': 'Milliliter',
    'MTR': 'Meter',
    'MTK': 'Quadratmeter',
    'MTQ': 'Kubikmeter',
    'HUR': 'Stunde',
    'MON': 'Monat',
    'TNE': 'Tonne (metrisch)',
    'XCT': 'Karton',
    'XBH': 'Gebinde/Bund',
    'XPX': 'Palette',
    'XRO': 'Rolle',
    'NAR': 'Anzahl Artikel',
}


def liste() -> list[dict[str, Any]]:
    """Liefert alle MENGENEINHEIT-Zeilen, sortiert nach BEZEICHNUNG.

    Rueckgabe-Format (pro Eintrag)::

        {
          'id':             int,      # REC_ID
          'bezeichnung':    str,      # BEZEICHNUNG
          'me_code':        str | '', # ME_CODE (kann leer sein)
          'me_code_label':  str,      # 'H87 (Stueck)' oder nur Code,
                                      # oder '' wenn leer
        }
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, BEZEICHNUNG, ME_CODE
            FROM MENGENEINHEIT
            ORDER BY BEZEICHNUNG
            """
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        code = (r.get('ME_CODE') or '').strip()
        if code:
            klar = _UNECE_KLARNAMEN.get(code.upper())
            label = f'{code} ({klar})' if klar else code
        else:
            label = ''
        eintraege.append({
            'id':            r.get('REC_ID'),
            'bezeichnung':   (r.get('BEZEICHNUNG') or '').strip(),
            'me_code':       code,
            'me_code_label': label,
        })
    return eintraege
