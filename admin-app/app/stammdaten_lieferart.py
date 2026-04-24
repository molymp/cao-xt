"""
CAO-Stammdaten: Lieferarten – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``LIEFERARTEN`` fuer die Admin-Ansicht. In
cao_admin.exe findet sich dieselbe Liste unter
*Einstellungen → Lieferarten*.

Schema (variiert zwischen CAO-Versionen)::

    REC_ID     int         PK
    NAME       varchar     Bezeichnung ('DHL', 'Abholung', 'Spedition')
    TEXT       memo/blob   Standard-Belegtext (nicht in allen CAO-Builds)

cao_admin.exe referenziert intern ``LIEF_ID`` und ``LANGBEZ`` als Feld-
Aliasse; in der realen DB heissen die Spalten jedoch ``REC_ID`` und
``NAME``. Die ``TEXT``-Spalte existiert nicht in jeder Installation –
wir introspekten das Schema vor dem SELECT.

Die IDs 1, 4, 5 sind laut cao_admin.exe-Hinweis CAO-Standardwerte
(Selbstabholung etc.) und sollten nicht umbenannt werden.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

# Kandidaten fuer Langtext-Spalten, falls vorhanden
_TEXT_KANDIDATEN = ('TEXT', 'LANGTEXT', 'BESCHREIBUNG', 'LANGBEZ')

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der LIEFERARTEN-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'LIEFERARTEN'
        """
    )
    _spalten_cache = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache


def liste() -> list[dict[str, Any]]:
    """Liefert alle LIEFERARTEN-Zeilen, sortiert nach REC_ID.

    Rueckgabe-Format (pro Eintrag)::

        {
          'id':        int,       # REC_ID
          'name':      str,       # NAME
          'text':      str,       # Langtext (leer, wenn Spalte fehlt)
          'has_text':  bool,      # True wenn Langtext nicht leer
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        text_spalte = next(
            (k for k in _TEXT_KANDIDATEN if k in vorhanden), None)

        felder = ['REC_ID', 'NAME']
        if text_spalte:
            felder.append(text_spalte)

        cur.execute(
            f"SELECT {', '.join(felder)} FROM LIEFERARTEN ORDER BY REC_ID"
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        roh_text = r.get(text_spalte) if text_spalte else ''
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
