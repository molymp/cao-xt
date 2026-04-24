"""
CAO-Stammdaten: Warengruppen – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``WARENGRUPPEN`` fuer die Admin-Ansicht. In
cao_admin.exe ist das *Einstellungen → Warengruppen* (Baum mit
Kalkulation, Steuercode und Default-Konten).

Schema (CAO-Faktura 1.5)::

    ID            int        PK (Achtung: nicht REC_ID)
    TOP_ID        int        Parent-ID (-1 = Wurzel, CAO-Konvention)
    NAME          varchar
    BESCHREIBUNG  text       Langtext-Memo
    DEF_EKTO      int        Default-Einkaufskonto (FIRMEN_KONTO, -1 = ohne)
    DEF_AKTO      int        Default-Erloeskonto  (FIRMEN_KONTO, -1 = ohne)
    STEUER_CODE   tinyint    0 = ohne, 1 = voll (19%), 2 = erm (7%), 3 = Res
                             (siehe REGISTRY 'MAIN\\MWST')
    VK1_FAKTOR    float      5 Kalkulationsfaktoren fuer VK1..VK5
    VK2_FAKTOR    float
    VK3_FAKTOR    float
    VK4_FAKTOR    float
    VK5_FAKTOR    float
    VORGABEN      text       INI-artig (derzeit nicht gezielt ausgewertet)
    SORT          int
    DURCHSUCHEN   Y/N        sichtbar in Artikel-Lookup
    WGR_RABATT    decimal    Warengruppen-Rabatt %
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_PFLICHT = ('ID', 'NAME')
_OPTIONAL = (
    'TOP_ID', 'BESCHREIBUNG', 'DEF_EKTO', 'DEF_AKTO', 'STEUER_CODE',
    'VK1_FAKTOR', 'VK2_FAKTOR', 'VK3_FAKTOR', 'VK4_FAKTOR', 'VK5_FAKTOR',
    'SORT', 'DURCHSUCHEN', 'WGR_RABATT', 'VORGABEN',
)

# Statische Steuercode-Labels – entsprechen REGISTRY['MAIN\\MWST'].
# Fuer die Admin-Uebersicht reicht die Default-Belegung; echte Prozent-
# Werte kommen pro Land aus LAND.MWST_1/2/3 und werden hier nicht
# aufgeloest.
_STEUER_CODE_LABEL = {
    0: 'ohne MwSt',
    1: 'voll (19%)',
    2: 'erm. (7%)',
    3: 'Reserve',
}

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der WARENGRUPPEN-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'WARENGRUPPEN'
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


def _float_oder_none(wert: Any) -> float | None:
    if wert is None:
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _memo_text(roh: Any) -> str:
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def _konto(wert: Any) -> int | None:
    """CAO nutzt -1 als 'nicht gesetzt' fuer Default-Konten."""
    v = _int_oder_none(wert)
    if v is None or v <= 0:
        return None
    return v


def liste() -> dict[str, Any]:
    """Liefert alle WARENGRUPPEN-Zeilen plus Tree-Metadaten.

    Rueckgabe::

        {
          'eintraege': [
            {
              'id':            int,
              'parent_id':     int | None,   # None = Wurzel (TOP_ID = -1/0)
              'name':          str,
              'beschreibung':  str,
              'def_ekto':      int | None,   # None = nicht gesetzt (-1)
              'def_akto':      int | None,
              'steuer_code':   int | None,
              'steuer_label':  str,          # 'voll (19%)' etc.
              'kalk':          [f1..f5],     # floats | None
              'hat_kalk':      bool,         # irgendein Faktor > 0
              'wgr_rabatt':    float | None,
              'durchsuchen':   bool,
              'sort':          int | None,
              'kinder':        int,          # Anzahl direkter Kinder
            },
            ...
          ]
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)

        felder = list(_PFLICHT) + [f for f in _OPTIONAL if f in vorhanden]
        sort_spalte = 'SORT' if 'SORT' in vorhanden else 'NAME'
        cur.execute(
            f"SELECT {', '.join(felder)} FROM WARENGRUPPEN "
            f"ORDER BY {sort_spalte}, NAME"
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    for r in rows:
        parent_id = _int_oder_none(r.get('TOP_ID'))
        # CAO-Konvention: -1 und 0 sind 'keine Parent'
        if parent_id in (0, -1):
            parent_id = None

        kalk = [
            _float_oder_none(r.get(f'VK{i}_FAKTOR')) for i in range(1, 6)
        ]
        hat_kalk = any(f is not None and f > 0 for f in kalk)

        stcode = _int_oder_none(r.get('STEUER_CODE'))
        stlabel = _STEUER_CODE_LABEL.get(stcode, '') if stcode is not None \
            else ''

        eintraege.append({
            'id':           _int_oder_none(r.get('ID')),
            'parent_id':    parent_id,
            'name':         (r.get('NAME') or '').strip(),
            'beschreibung': _memo_text(r.get('BESCHREIBUNG')),
            'def_ekto':     _konto(r.get('DEF_EKTO')),
            'def_akto':     _konto(r.get('DEF_AKTO')),
            'steuer_code':  stcode,
            'steuer_label': stlabel,
            'kalk':         kalk,
            'hat_kalk':     hat_kalk,
            'wgr_rabatt':   _float_oder_none(r.get('WGR_RABATT')),
            'durchsuchen':  _ja(r.get('DURCHSUCHEN')),
            'sort':         _int_oder_none(r.get('SORT')),
        })

    # Anzahl direkter Kinder pro Knoten zaehlen
    kinder_zaehlung: dict[int, int] = {}
    for e in eintraege:
        pid = e['parent_id']
        if pid is not None:
            kinder_zaehlung[pid] = kinder_zaehlung.get(pid, 0) + 1
    for e in eintraege:
        e['kinder'] = kinder_zaehlung.get(e['id'], 0)

    return {'eintraege': eintraege}
