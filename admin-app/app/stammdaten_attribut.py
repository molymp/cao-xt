"""
CAO-Stammdaten: Artikelattribute – Read-only Data-Access.

CAO haelt zusaetzliche Artikel-Eigenschaften (Farbe, Groesse, ...)
in drei zusammenhaengenden Tabellen::

    ARTIKEL_ATTRIBUT
      ATTRIBUT_ID   PK
      NAME          z.B. "Farbe"
      POS           Anzeige-Reihenfolge
      LISTTYP       1 Char, Default 'K' (Konfig-Liste)

    ARTIKEL_ATTRIBUT_OPTIONEN
      OPTIONS_ID    PK
      ATTRIBUT_ID   FK auf ARTIKEL_ATTRIBUT
      NAME          z.B. "Rot"
      PREIS         Aufpreis
      POS           Anzeige-Reihenfolge
      LISTTYP       1 Char, Default 'N'

    ARTIKEL_TO_ATTRIBUT
      OPTIONS_ID, ARTIKEL_ID, BEZEICHNUNG, PREIS
      -> eigentliche Zuweisung an Artikel

Die Admin-Seite zeigt Attribut + Optionen + Anzahl der Artikel, die
eine Option verwenden (aus ARTIKEL_TO_ATTRIBUT).
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_spalten_cache: dict[str, set[str]] = {}


def _spalten(cur, tabelle: str) -> set[str]:
    """Liest die Spaltennamen einer Tabelle (Cache pro Tabellenname)."""
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
    spalten = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    _spalten_cache[tabelle] = spalten
    return spalten


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _float_oder_none(wert: Any) -> float | None:
    if wert is None:
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def liste() -> list[dict[str, Any]]:
    """Liefert alle Attribute mit ihren Optionen und Nutzungszahlen.

    Rueckgabe::

        [
          {
            'id':       int,
            'name':     str,
            'pos':      int | None,
            'listtyp':  str,          # 1 Char
            'optionen': [
              {
                'id':         int,
                'name':       str,
                'preis':      float | None,  # 0.0 -> None
                'pos':        int | None,
                'listtyp':    str,
                'nutzungen': int,            # Anzahl ARTIKEL_TO_ATTRIBUT-Zeilen
              },
              ...
            ],
          },
          ...
        ]
    """
    with get_db() as cur:
        # Schemas pruefen – Tabelle kann in alten DBs fehlen
        attr_vorhanden = _spalten(cur, 'ARTIKEL_ATTRIBUT')
        opt_vorhanden  = _spalten(cur, 'ARTIKEL_ATTRIBUT_OPTIONEN')
        if not attr_vorhanden:
            return []

        cur.execute(
            "SELECT ATTRIBUT_ID, NAME, POS, LISTTYP "
            "FROM ARTIKEL_ATTRIBUT ORDER BY POS, NAME"
        )
        attr_rows = cur.fetchall() or []

        opt_rows: list[dict[str, Any]] = []
        if opt_vorhanden:
            cur.execute(
                "SELECT OPTIONS_ID, ATTRIBUT_ID, NAME, PREIS, POS, LISTTYP "
                "FROM ARTIKEL_ATTRIBUT_OPTIONEN "
                "ORDER BY ATTRIBUT_ID, POS, NAME"
            )
            opt_rows = cur.fetchall() or []

        # Nutzungszaehlung aus ARTIKEL_TO_ATTRIBUT
        nutzungen: dict[int, int] = {}
        ata_vorhanden = _spalten(cur, 'ARTIKEL_TO_ATTRIBUT')
        if ata_vorhanden:
            cur.execute(
                "SELECT OPTIONS_ID, COUNT(*) AS ANZ "
                "FROM ARTIKEL_TO_ATTRIBUT GROUP BY OPTIONS_ID"
            )
            for r in cur.fetchall() or []:
                oid = _int_oder_none(r.get('OPTIONS_ID'))
                if oid is not None:
                    nutzungen[oid] = _int_oder_none(r.get('ANZ')) or 0

    # Optionen pro Attribut gruppieren
    opt_by_attr: dict[int, list[dict[str, Any]]] = {}
    for r in opt_rows:
        aid = _int_oder_none(r.get('ATTRIBUT_ID'))
        oid = _int_oder_none(r.get('OPTIONS_ID'))
        if aid is None or oid is None:
            continue
        preis = _float_oder_none(r.get('PREIS'))
        if preis == 0:
            preis = None
        opt_by_attr.setdefault(aid, []).append({
            'id':        oid,
            'name':      _str(r.get('NAME')),
            'preis':     preis,
            'pos':       _int_oder_none(r.get('POS')),
            'listtyp':   _str(r.get('LISTTYP')),
            'nutzungen': nutzungen.get(oid, 0),
        })

    ergebnis: list[dict[str, Any]] = []
    for r in attr_rows:
        aid = _int_oder_none(r.get('ATTRIBUT_ID'))
        ergebnis.append({
            'id':       aid,
            'name':     _str(r.get('NAME')),
            'pos':      _int_oder_none(r.get('POS')),
            'listtyp':  _str(r.get('LISTTYP')),
            'optionen': opt_by_attr.get(aid, []),
        })
    return ergebnis
