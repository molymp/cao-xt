"""
CAO-Stammdaten: Adressgruppen – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``ADRESSGRUPPEN`` fuer die Admin-Ansicht. In
cao_admin.exe ist das *Einstellungen → Adressgruppen* (mit Baum-
Darstellung fuer Unter-Gruppen).

Reale Spalten (variieren, wir introspekten)::

    REC_ID         int         PK
    TOP_ID         int         Parent-ID fuer Baum (-1/0/NULL = Wurzel);
                               in manchen DBs PARENT_ID
    NAME           varchar     Bezeichnung (in Delphi-DFM als LANGBEZ aliased)
    TEXT_KURZ      varchar
    TEXT_LANG      longtext
    DURCHSUCHEN    char(1)     'Y' = Gruppe in Lookups sichtbar
    GLOBALRABATT   float       Standard-Rabatt % (Delphi-Alias: RABATT)
    SORT           int         Sortier-Reihenfolge
    VORGABEN       memo        INI-artig; enthaelt u.a. ``erechnung_typ``
                               (deaktiviert/xrechnung/zugferd)
    SQL_TEXT       memo        dynamische Gruppe per SQL
                               (Delphi-Alias: SQL_STATEMENT)

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
    'DURCHSUCHEN', 'GLOBALRABATT', 'SORT', 'VORGABEN', 'SQL_TEXT',
    'TEXT_KURZ', 'TEXT_LANG',
)
# Kandidaten fuer die Parent-Spalte (erste vorhandene gewinnt)
_PARENT_KANDIDATEN = ('TOP_ID', 'PARENT_ID', 'PARENT', 'UP_ID', 'ROOT_ID')

# Gueltige Werte fuer den E-Rechnung-Typ (cbRechnungstyp in cao_admin)
_ERECHNUNG_TYPEN = {'deaktiviert', 'xrechnung', 'zugferd'}

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


def _memo_text(roh: Any) -> str:
    """Dekodiert Memo-/BLOB-Felder zu einem getrimmten String."""
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def _parse_vorgaben_ini(text: str) -> dict[str, str]:
    """Parst das VORGABEN-Memo (INI-artig) in ein flaches Dict.

    Sektionen werden ignoriert – CAO nutzt meist nur einen einfachen
    ``key=value``-Block pro Zeile. Schluessel werden case-insensitive
    gespeichert.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    for zeile in text.splitlines():
        s = zeile.strip()
        if not s or s.startswith(';') or s.startswith('#'):
            continue
        if s.startswith('[') and s.endswith(']'):
            continue
        if '=' not in s:
            continue
        k, _, v = s.partition('=')
        out[k.strip().lower()] = v.strip()
    return out


def _erechnung_typ(vorgaben: dict[str, str]) -> str | None:
    roh = (vorgaben.get('erechnung_typ') or '').strip().lower()
    if not roh:
        return None
    return roh if roh in _ERECHNUNG_TYPEN else None


def liste() -> dict[str, Any]:
    """Liefert die flache Liste der Adressgruppen plus Tree-Metadaten.

    Rueckgabe::

        {
          'parent_spalte': 'TOP_ID' | None,   # Name der Parent-Spalte
          'eintraege': [
            {
              'id':            int,
              'parent_id':     int | None,   # None = Wurzel
              'name':          str,
              'durchsuchen':   bool,
              'globalrabatt':  float | None, # Standard-Rabatt %
              'sort':          int | None,
              'hat_sql':       bool,
              'erechnung_typ': str | None,   # deaktiviert/xrechnung/zugferd
              'kinder':        int,          # Anzahl direkter Kinder
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

        rabatt_roh = r.get('GLOBALRABATT')
        try:
            globalrabatt = (
                float(rabatt_roh) if rabatt_roh is not None else None
            )
        except (TypeError, ValueError):
            globalrabatt = None

        sql_text = _memo_text(r.get('SQL_TEXT'))

        vorgaben_text = _memo_text(r.get('VORGABEN'))
        vorgaben = _parse_vorgaben_ini(vorgaben_text)

        eintraege.append({
            'id':            _int_oder_none(r.get('REC_ID')),
            'parent_id':     parent_id,
            'name':          (r.get('NAME') or '').strip(),
            'durchsuchen':   _ja(r.get('DURCHSUCHEN')),
            'globalrabatt':  globalrabatt,
            'sort':          _int_oder_none(r.get('SORT')),
            'hat_sql':       bool(sql_text),
            'erechnung_typ': _erechnung_typ(vorgaben),
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
