"""
CAO-Stammdaten: Kontenrahmen (FIBU_KONTEN) – Read-only Data-Access.

Spiegelt die CAO-Tabelle ``FIBU_KONTEN``. Ein CAO-Mandant kann
mehrere Kontenrahmen halten (SKR03/SKR04/SKR42/…) – jeder Rahmen
hat seine eigene Kontenliste. Der zusammengesetzte PK ist
``(KONTORAHMEN, KONTO)``.

Schema::

    KONTORAHMEN   varchar(10)  Schluessel des Rahmens ('SKR03', 'SKR04')
    KONTO         int          Kontonummer (1000, 3400, 8400, ...)
    KONTONAME     varchar
    KONTOART      tinyint      Rohzahl (3=Kasse, 20=Bank, 99=sonst., ...)
    NEBENKONTO    int          verknuepftes Konto (0 = keins)
    STEUERSATZ    decimal      fester Steuersatz (0.00 wenn keiner)
    BILANZKONTO   Y/N          'Y' -> Bilanzkonto, 'N' -> GuV-Konto
    NK_AUSWAHL    Y/N          'Y' -> Nebenkonto-Auswahl bei Buchung
    USTVA_ZEILE   int          Zeilennummer in der UStVA
    BWA_GRUPPE    int          BWA-Kategorie
    BANK_BLZ/BANK_KONTO/BANK_NAME/KONTO_INHABER/IBAN/SWIFT
                               nur gesetzt bei Bankkonten (KONTOART=20)
    INFO          text         Freitext-Memo
    STANDARD      Y/N          'Y' -> Standard-Konto dieser Art
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

_PFLICHT = ('KONTORAHMEN', 'KONTO', 'KONTONAME')
_OPTIONAL = (
    'KONTOART', 'NEBENKONTO', 'STEUERSATZ',
    'BILANZKONTO', 'NK_AUSWAHL', 'USTVA_ZEILE', 'BWA_GRUPPE',
    'BANK_BLZ', 'BANK_KONTO', 'BANK_NAME', 'KONTO_INHABER',
    'IBAN', 'SWIFT', 'INFO', 'STANDARD',
)

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der FIBU_KONTEN-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'FIBU_KONTEN'
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


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def liste() -> dict[str, Any]:
    """Liefert alle Konten aller Rahmen plus Rahmen-Liste.

    Rueckgabe::

        {
          'rahmen': ['SKR03', 'SKR04', ...],   # alphabetisch
          'eintraege': [
            {
              'rahmen':       str,
              'konto':        int,
              'name':         str,
              'kontoart':     int | None,
              'nebenkonto':   int | None,      # 0 -> None
              'steuersatz':   float | None,    # 0 -> None
              'bilanzkonto':  bool,
              'nk_auswahl':   bool,
              'standard':     bool,
              'ustva_zeile':  int | None,      # 0 -> None
              'bwa_gruppe':   int | None,      # 0 -> None
              'info':         str,
              'bank': {                         # nur wenn irgendetwas gesetzt
                  'blz':     str,
                  'konto':   str,
                  'name':    str,
                  'inhaber': str,
                  'iban':    str,
                  'swift':   str,
              } | None,
            },
            ...
          ]
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        felder = list(_PFLICHT) + [f for f in _OPTIONAL if f in vorhanden]
        cur.execute(
            f"SELECT {', '.join(felder)} FROM FIBU_KONTEN "
            f"ORDER BY KONTORAHMEN, KONTO"
        )
        rows = cur.fetchall() or []

    eintraege: list[dict[str, Any]] = []
    rahmen: set[str] = set()
    for r in rows:
        rah = _str(r.get('KONTORAHMEN'))
        rahmen.add(rah)

        # 0 als "nicht gesetzt" behandeln, wo es semantisch passt
        neben = _int_oder_none(r.get('NEBENKONTO'))
        if neben == 0:
            neben = None
        ustva = _int_oder_none(r.get('USTVA_ZEILE'))
        if ustva == 0:
            ustva = None
        bwa = _int_oder_none(r.get('BWA_GRUPPE'))
        if bwa == 0:
            bwa = None

        steuer = _float_oder_none(r.get('STEUERSATZ'))
        if steuer == 0:
            steuer = None

        bank_fields = {
            'blz':     _str(r.get('BANK_BLZ')),
            'konto':   _str(r.get('BANK_KONTO')),
            'name':    _str(r.get('BANK_NAME')),
            'inhaber': _str(r.get('KONTO_INHABER')),
            'iban':    _str(r.get('IBAN')),
            'swift':   _str(r.get('SWIFT')),
        }
        bank = bank_fields if any(bank_fields.values()) else None

        eintraege.append({
            'rahmen':      rah,
            'konto':       _int_oder_none(r.get('KONTO')),
            'name':        _str(r.get('KONTONAME')),
            'kontoart':    _int_oder_none(r.get('KONTOART')),
            'nebenkonto':  neben,
            'steuersatz':  steuer,
            'bilanzkonto': _ja(r.get('BILANZKONTO')),
            'nk_auswahl':  _ja(r.get('NK_AUSWAHL')),
            'standard':    _ja(r.get('STANDARD')),
            'ustva_zeile': ustva,
            'bwa_gruppe':  bwa,
            'info':        _memo_text(r.get('INFO')),
            'bank':        bank,
        })

    return {
        'rahmen':    sorted(rahmen),
        'eintraege': eintraege,
    }
