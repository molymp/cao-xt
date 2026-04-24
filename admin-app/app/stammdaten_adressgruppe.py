"""
CAO-Stammdaten: Adressgruppen – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``ADRESSGRUPPEN`` fuer die Admin-Ansicht. In
cao_admin.exe ist das *Einstellungen → Adressgruppen* (mit Baum-
Darstellung fuer Unter-Gruppen).

Reale Spalten (variieren, wir introspekten)::

    REC_ID        int         PK
    NAME          varchar     Bezeichnung (in Delphi-DFM als LANGBEZ aliased)
    DURCHSUCHEN   char(1)     'Y' = Gruppe in Lookups sichtbar
    TOP_ID        int         Parent-ID fuer Baum (0/NULL = Wurzel);
                              in manchen DBs PARENT_ID
    RABATT        float       Standard-Rabatt %
    SORT          int         Sortier-Reihenfolge
    VORGABEN      memo        Vorgaben-INI/JSON (nicht angezeigt)
    SQL_STATEMENT memo        dynamische Gruppe per SQL (selten genutzt)

Rueckgabe enthaelt sowohl die flache Liste (mit ``parent_id`` als
Koordinate) als auch die Anzahl direkter Kinder pro Knoten – den
eigentlichen Baum baut das Frontend.
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_PFLICHT = ('REC_ID', 'NAME')
_OPTIONAL = (
    'DURCHSUCHEN', 'RABATT', 'SORT', 'VORGABEN', 'SQL_STATEMENT',
)
# Kandidaten fuer die Parent-Spalte (erste vorhandene gewinnt)
_PARENT_KANDIDATEN = ('TOP_ID', 'PARENT_ID', 'PARENT', 'UP_ID', 'ROOT_ID')

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der ADRESSGRUPPEN-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'ADRESSGRUPPEN'
        """
    )
    _spalten_cache = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache


def _ja(wert: Any) -> bool:
    return str(wert or '').strip().upper() == 'Y'


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def liste() -> dict[str, Any]:
    """Liefert die flache Liste der Adressgruppen plus Tree-Metadaten.

    Rueckgabe::

        {
          'parent_spalte': 'TOP_ID' | None,   # Name der Parent-Spalte
          'eintraege': [
            {
              'id':          int,
              'parent_id':   int | None,   # None = Wurzel
              'name':        str,
              'durchsuchen': bool,
              'rabatt':      float | None,
              'sort':        int | None,
              'hat_sql':     bool,
              'kinder':      int,          # Anzahl direkter Kinder
            },
            ...
          ]
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        parent_spalte = next(
            (p for p in _PARENT_KANDIDATEN if p in vorhanden), None)

        felder = list(_PFLICHT) + [f for f in _OPTIONAL if f in vorhanden]
        if parent_spalte:
            felder.append(parent_spalte)

        sort_spalte = 'SORT' if 'SORT' in vorhanden else 'NAME'
        cur.execute(
            f"SELECT {', '.join(felder)} FROM ADRESSGRUPPEN "
            f"ORDER BY {sort_spalte}, NAME"
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        parent_id = (
            _int_oder_none(r.get(parent_spalte)) if parent_spalte else None
        )
        # 0/-1 gelten als "kein Parent"
        if parent_id in (0, -1):
            parent_id = None

        rabatt_roh = r.get('RABATT')
        try:
            rabatt = float(rabatt_roh) if rabatt_roh is not None else None
        except (TypeError, ValueError):
            rabatt = None

        sql_roh = r.get('SQL_STATEMENT')
        if isinstance(sql_roh, (bytes, bytearray)):
            try:
                sql_text = sql_roh.decode('utf-8', errors='replace').strip()
            except Exception:
                sql_text = ''
        else:
            sql_text = (sql_roh or '').strip() if sql_roh is not None else ''

        eintraege.append({
            'id':          _int_oder_none(r.get('REC_ID')),
            'parent_id':   parent_id,
            'name':        (r.get('NAME') or '').strip(),
            'durchsuchen': _ja(r.get('DURCHSUCHEN')),
            'rabatt':      rabatt,
            'sort':        _int_oder_none(r.get('SORT')),
            'hat_sql':     bool(sql_text),
        })

    # Anzahl direkter Kinder pro Knoten zaehlen
    kinder_zaehlung: dict[int, int] = {}
    for e in eintraege:
        pid = e['parent_id']
        if pid is not None:
            kinder_zaehlung[pid] = kinder_zaehlung.get(pid, 0) + 1
    for e in eintraege:
        e['kinder'] = kinder_zaehlung.get(e['id'], 0)

    return {
        'parent_spalte': parent_spalte,
        'eintraege':     eintraege,
    }
