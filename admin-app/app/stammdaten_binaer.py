"""
CAO-Stammdaten: Binaerdaten-Typen – Read-only Data-Access.

CAO haelt Datei-Anhaenge (PDFs, Bilder, ...) in der Tabelle
BINAERDATEN – mit MODUL_ID/REFERENZ_ID als Bezug zum Besitzer
(Artikel, Adresse, Journal, ...) und BINAER_TYP als Kategorie.
Die Stammdaten-Typen stehen in BINAER_KATEGORIE.

Diese Admin-Seite zeigt pro Typ die Konfiguration + Statistiken
(Anzahl Dateien, Gesamt-Bytes, groesste Datei). **BLOB-Inhalte
werden nicht ausgeliefert** – nur Metadaten.

Schema::

    BINAER_KATEGORIE
      REC_ID     PK
      NAME       Kategorie-Name
      JSONDATEN  freie Konfig

    BINAERDATEN
      REC_ID, MODUL_ID, REFERENZ_ID, BINAER_TYP,
      KURZTEXT, PFAD, DATEI, DATEIGROESSE, BYTEGROESSE, DATEN(BLOB),
      PRIMAER, SHOP_*, ERSTELLT, ERST_NAME
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_spalten_cache: dict[str, set[str]] = {}


def _spalten(cur, tabelle: str) -> set[str]:
    if tabelle in _spalten_cache:
        return _spalten_cache[tabelle]
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
        """,
        (tabelle,),
    )
    _spalten_cache[tabelle] = {
        r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache[tabelle]


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def _memo(roh: Any) -> str:
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def liste() -> dict[str, Any]:
    """Liefert Kategorien + Aggregat-Statistiken.

    Rueckgabe::

        {
          'kategorien': [
            {
              'id':            int,
              'name':          str,
              'jsondaten':     str,  # erster Teil, gekuerzt auf ~500
              'anzahl':        int,  # Dateien mit diesem Typ
              'gesamt_bytes':  int,
              'groesste_byte': int,
            },
            ...
          ],
          'total_anzahl':  int,
          'total_bytes':   int,
        }
    """
    with get_db() as cur:
        kat_vorhanden = _spalten(cur, 'BINAER_KATEGORIE')
        bd_vorhanden  = _spalten(cur, 'BINAERDATEN')

        kat_rows = []
        if kat_vorhanden:
            cur.execute(
                "SELECT REC_ID, NAME, JSONDATEN "
                "FROM BINAER_KATEGORIE ORDER BY REC_ID"
            )
            kat_rows = cur.fetchall() or []

        # Statistiken: BYTEGROESSE falls vorhanden, sonst OCTET_LENGTH
        stats_rows: list[dict[str, Any]] = []
        total_anzahl = 0
        total_bytes  = 0
        if bd_vorhanden:
            byte_expr = (
                'SUM(BYTEGROESSE)' if 'BYTEGROESSE' in bd_vorhanden
                else 'SUM(OCTET_LENGTH(DATEN))'
            )
            max_expr = (
                'MAX(BYTEGROESSE)' if 'BYTEGROESSE' in bd_vorhanden
                else 'MAX(OCTET_LENGTH(DATEN))'
            )
            cur.execute(
                f"SELECT BINAER_TYP, COUNT(*) AS ANZ, "
                f"{byte_expr} AS SUM_B, {max_expr} AS MAX_B "
                f"FROM BINAERDATEN GROUP BY BINAER_TYP"
            )
            stats_rows = cur.fetchall() or []
            for r in stats_rows:
                total_anzahl += _int_oder_none(r.get('ANZ')) or 0
                total_bytes  += _int_oder_none(r.get('SUM_B')) or 0

    # Statistiken pro Typ-ID indexieren
    by_typ = {}
    for r in stats_rows:
        by_typ[_int_oder_none(r.get('BINAER_TYP'))] = {
            'anzahl':        _int_oder_none(r.get('ANZ')) or 0,
            'gesamt_bytes':  _int_oder_none(r.get('SUM_B')) or 0,
            'groesste_byte': _int_oder_none(r.get('MAX_B')) or 0,
        }

    kategorien = []
    seen_ids: set[int] = set()
    for k in kat_rows:
        kid = _int_oder_none(k.get('REC_ID'))
        if kid is None:
            continue
        seen_ids.add(kid)
        st = by_typ.get(kid, {'anzahl': 0, 'gesamt_bytes': 0,
                              'groesste_byte': 0})
        jd = _memo(k.get('JSONDATEN'))
        if len(jd) > 500:
            jd = jd[:500].rstrip() + ' …'
        kategorien.append({
            'id':            kid,
            'name':          _str(k.get('NAME')),
            'jsondaten':     jd,
            'anzahl':        st['anzahl'],
            'gesamt_bytes':  st['gesamt_bytes'],
            'groesste_byte': st['groesste_byte'],
        })

    # Dateien mit unbekanntem Typ -> virtuelle Sammelkategorie
    verwaiste_anz = 0
    verwaiste_bytes = 0
    verwaiste_max = 0
    for r in stats_rows:
        tid = _int_oder_none(r.get('BINAER_TYP'))
        if tid not in seen_ids:
            verwaiste_anz += _int_oder_none(r.get('ANZ')) or 0
            verwaiste_bytes += _int_oder_none(r.get('SUM_B')) or 0
            mb = _int_oder_none(r.get('MAX_B')) or 0
            if mb > verwaiste_max:
                verwaiste_max = mb
    if verwaiste_anz:
        kategorien.append({
            'id':            None,
            'name':          '(ohne / unbekannt)',
            'jsondaten':     '',
            'anzahl':        verwaiste_anz,
            'gesamt_bytes':  verwaiste_bytes,
            'groesste_byte': verwaiste_max,
        })

    return {
        'kategorien':   kategorien,
        'total_anzahl': total_anzahl,
        'total_bytes':  total_bytes,
    }
