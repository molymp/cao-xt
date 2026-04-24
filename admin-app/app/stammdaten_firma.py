"""
CAO-Stammdaten: Firmendaten (FIRMA) – Read-only Data-Access.

Die FIRMA-Tabelle ist der Mandantenstammsatz fuer Formulare
(Briefkopf, Rechnungsfuss, SEPA-GID usw.). cao_admin.exe selektiert
immer den zuletzt angelegten Datensatz::

    SELECT * FROM FIRMA ORDER BY REC_ID DESC LIMIT 0,1

Aufgeteilt in logische Gruppen fuer die Anzeige::

    basis        NAME1/2/3, ANREDE, GESCHAEFTSFUEHRER,
                 GERICHT, HRANUMMER, HRBNUMMER, WID, EORI, UID
    adresse      STRASSE, HAUSNR, ADRESSZUSATZ, PLZ, ORT, LAND
    kontakt      VORWAHL, TELEFON1/2, MOBILFUNK, FAX, EMAIL, WEBSEITE
    steuern      STEUERNUMMER, UST_ID, SEPA_GID
    banken       [BANK1_*, BANK2_*] – jeweils BLZ/KONTONR/IBAN/SWIFT/
                 NAME/INHABER. ACHTUNG: laut cao_admin-Hinweis werden
                 diese Felder NUR in Formularen verwendet, nicht fuer
                 SEPA-Buchungen (dafuer: Firmen-Bankkonten).
    formular     KOPFTEXT, FUSSTEXT, ABSENDER
    freitexte    FREITEXT1, FREITEXT2
    logos        IMAGE1/2/3 – BLOBs, wir melden nur Vorhandensein
                 und Groesse in Bytes (kein Datenabfluss)
"""
from __future__ import annotations

import logging
from typing import Any

from db import get_db

log = logging.getLogger(__name__)

# Spalten, die wir aus FIRMA lesen. IMAGE1/2/3 werden separat
# ueber LENGTH() abgefragt, damit wir nicht mehrere Megabytes an
# BLOB-Daten ins Response ziehen.
_FELDER = (
    'REC_ID',
    # basis
    'ANREDE', 'NAME1', 'NAME2', 'NAME3',
    'GESCHAEFTSFUEHRER', 'GERICHT',
    'HRANUMMER', 'HRBNUMMER', 'WID', 'EORI', 'UID',
    # adresse
    'STRASSE', 'HAUSNR', 'ADRESSZUSATZ', 'LAND', 'PLZ', 'ORT',
    # kontakt
    'VORWAHL', 'TELEFON1', 'TELEFON2', 'MOBILFUNK', 'FAX',
    'EMAIL', 'WEBSEITE',
    # steuern
    'STEUERNUMMER', 'UST_ID', 'SEPA_GID',
    # banken
    'BANK1_BLZ', 'BANK1_KONTONR', 'BANK1_NAME', 'BANK1_IBAN',
    'BANK1_SWIFT', 'BANK1_KONTOINHABER',
    'BANK2_BLZ', 'BANK2_KONTONR', 'BANK2_NAME', 'BANK2_IBAN',
    'BANK2_SWIFT', 'BANK2_KONTOINHABER',
    # formular
    'KOPFTEXT', 'FUSSTEXT', 'ABSENDER',
    'FREITEXT1', 'FREITEXT2',
)
_IMAGE_FELDER = ('IMAGE1', 'IMAGE2', 'IMAGE3')

_spalten_cache: set[str] | None = None


def _spalten(cur) -> set[str]:
    """Liest einmalig die Spaltennamen der FIRMA-Tabelle."""
    global _spalten_cache
    if _spalten_cache is not None:
        return _spalten_cache
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'FIRMA'
        """
    )
    _spalten_cache = {r['COLUMN_NAME'].upper() for r in cur.fetchall()}
    return _spalten_cache


def _str(wert: Any) -> str:
    return (wert or '').strip() if wert is not None else ''


def _memo_text(roh: Any) -> str:
    if roh is None:
        return ''
    if isinstance(roh, (bytes, bytearray)):
        try:
            return roh.decode('utf-8', errors='replace').strip()
        except Exception:
            return ''
    return str(roh).strip()


def _int_oder_none(wert: Any) -> int | None:
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _bank(row: dict[str, Any], n: int) -> dict[str, str] | None:
    """Baut ein Bank-Dict fuer BANK{n}_*-Felder. None wenn alles leer."""
    felder = {
        'blz':     _str(row.get(f'BANK{n}_BLZ')),
        'kontonr': _str(row.get(f'BANK{n}_KONTONR')),
        'name':    _str(row.get(f'BANK{n}_NAME')),
        'iban':    _str(row.get(f'BANK{n}_IBAN')),
        'swift':   _str(row.get(f'BANK{n}_SWIFT')),
        'inhaber': _str(row.get(f'BANK{n}_KONTOINHABER')),
    }
    return felder if any(felder.values()) else None


def firma() -> dict[str, Any] | None:
    """Liefert den (einzigen) FIRMA-Datensatz strukturiert oder None.

    Rueckgabe (None wenn die Tabelle leer ist)::

        {
          'id':      int,
          'basis':   {...},
          'adresse': {...},
          'kontakt': {...},
          'steuern': {...},
          'banken':  [bank1 | None, bank2 | None],
          'formular':  {'kopftext': str, 'fusstext': str, 'absender': str},
          'freitexte': [str, str],
          'logos':   [{'name': 'IMAGE1', 'vorhanden': bool, 'bytes': int},
                      ..., 'IMAGE3'],
        }
    """
    with get_db() as cur:
        vorhanden = _spalten(cur)
        felder = [f for f in _FELDER if f in vorhanden]
        if not felder:
            return None

        cur.execute(
            f"SELECT {', '.join(felder)} FROM FIRMA "
            f"ORDER BY REC_ID DESC LIMIT 1"
        )
        rows = cur.fetchall() or []
        if not rows:
            return None
        r = rows[0]

        # Logos: nur Vorhandensein + Groesse, keine BLOB-Daten
        logos: list[dict[str, Any]] = []
        img_spalten = [f for f in _IMAGE_FELDER if f in vorhanden]
        if img_spalten:
            laengen = ', '.join(
                f"OCTET_LENGTH({f}) AS {f}_LEN" for f in img_spalten)
            cur.execute(
                f"SELECT {laengen} FROM FIRMA "
                f"WHERE REC_ID = %s LIMIT 1",
                (r.get('REC_ID'),),
            )
            lrows = cur.fetchall() or []
            laengen_map = lrows[0] if lrows else {}
            for f in _IMAGE_FELDER:
                b = _int_oder_none(laengen_map.get(f'{f}_LEN')) \
                    if f in vorhanden else None
                logos.append({
                    'name': f,
                    'vorhanden': bool(b),
                    'bytes': b or 0,
                })
        else:
            for f in _IMAGE_FELDER:
                logos.append({'name': f, 'vorhanden': False, 'bytes': 0})

    return {
        'id': _int_oder_none(r.get('REC_ID')),
        'basis': {
            'anrede':            _str(r.get('ANREDE')),
            'name1':             _str(r.get('NAME1')),
            'name2':             _str(r.get('NAME2')),
            'name3':             _str(r.get('NAME3')),
            'geschaeftsfuehrer': _str(r.get('GESCHAEFTSFUEHRER')),
            'gericht':           _str(r.get('GERICHT')),
            'hranummer':         _str(r.get('HRANUMMER')),
            'hrbnummer':         _str(r.get('HRBNUMMER')),
            'wid':               _str(r.get('WID')),
            'eori':              _str(r.get('EORI')),
            'uid':               _str(r.get('UID')),
        },
        'adresse': {
            'strasse':      _str(r.get('STRASSE')),
            'hausnr':       _str(r.get('HAUSNR')),
            'adresszusatz': _str(r.get('ADRESSZUSATZ')),
            'plz':          _str(r.get('PLZ')),
            'ort':          _str(r.get('ORT')),
            'land':         _str(r.get('LAND')),
        },
        'kontakt': {
            'vorwahl':   _str(r.get('VORWAHL')),
            'telefon1':  _str(r.get('TELEFON1')),
            'telefon2':  _str(r.get('TELEFON2')),
            'mobilfunk': _str(r.get('MOBILFUNK')),
            'fax':       _str(r.get('FAX')),
            'email':     _str(r.get('EMAIL')),
            'webseite':  _str(r.get('WEBSEITE')),
        },
        'steuern': {
            'steuernummer': _str(r.get('STEUERNUMMER')),
            'ust_id':       _str(r.get('UST_ID')),
            'sepa_gid':     _str(r.get('SEPA_GID')),
        },
        'banken': [_bank(r, 1), _bank(r, 2)],
        'formular': {
            'kopftext': _memo_text(r.get('KOPFTEXT')),
            'fusstext': _memo_text(r.get('FUSSTEXT')),
            'absender': _str(r.get('ABSENDER')),
        },
        'freitexte': [
            _str(r.get('FREITEXT1')),
            _str(r.get('FREITEXT2')),
        ],
        'logos': logos,
    }
