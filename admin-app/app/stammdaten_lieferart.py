"""
CAO-Stammdaten: Lieferarten – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``LIEFERARTEN`` fuer die Admin-Ansicht. In
cao_admin.exe findet sich dieselbe Liste unter
*Einstellungen → Lieferarten*.

Schema (CAO-Faktura 1.5)::

    REC_ID     int         PK (in cao_admin.exe als LIEF_ID aliased)
    NAME       varchar     Bezeichnung ('DHL', 'Abholung', 'Spedition')
    TEXT       memo/blob   Standard-Belegtext (oft leer)

Die IDs 1, 4, 5 sind laut cao_admin.exe-Hinweis CAO-Standardwerte
(Selbstabholung etc.) und sollten nicht umbenannt werden.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)


def liste() -> list[dict[str, Any]]:
    """Liefert alle LIEFERARTEN-Zeilen, sortiert nach REC_ID.

    Rueckgabe-Format (pro Eintrag)::

        {
          'id':        int,       # REC_ID
          'name':      str,       # NAME
          'text':      str,       # Langtext (leer, wenn nicht gepflegt)
          'has_text':  bool,      # True wenn text.strip() nicht leer
        }
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT REC_ID, NAME, TEXT
            FROM LIEFERARTEN
            ORDER BY REC_ID
            """
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        # TEXT kann Bytes (BLOB) oder String sein – beides abfangen
        roh_text = r.get('TEXT')
        if isinstance(roh_text, (bytes, bytearray)):
            try:
                text = roh_text.decode('utf-8', errors='replace')
            except Exception:
                text = ''
        else:
            text = roh_text or ''
        text = str(text).strip()

        eintraege.append({
            'id':       r.get('REC_ID'),
            'name':     (r.get('NAME') or '').strip(),
            'text':     text,
            'has_text': bool(text),
        })
    return eintraege
