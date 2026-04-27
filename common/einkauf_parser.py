"""
CAO-XT – Einkauf: Email-Parser pro Lieferant (Phase 2/3).

Reine Funktionen ohne DB- oder Netzwerk-Zugriff. Aufrufer:

    from common.einkauf_parser import parse_email
    daten = parse_email('utz_v1', plain_text=text)

Rueckgabe ist ein dict mit den Schluesseln::

    {
      'best_nr':           str,
      'datum':             str,           # ISO 'YYYY-MM-DD'
      'kunden_nr':         str | None,
      'gesamtsumme_netto': float | None,
      'positionen': [
          {'pos_nr', 'artikel_nr_lief', 'bezeichnung_lief',
           'menge', 'preis_netto', 'zeilen_betrag'},
          ...
      ],
      'parser_key':        str,           # zum Audit
      'fehler':            str | None,    # bei nicht erkennbarem Format
    }

Neue Lieferanten kommen als zusaetzlicher ``parser_key``-Pfad rein
(``utz_v1`` ist hier der erste). Die Routing-Funktion
``parse_email`` waehlt anhand des keys den richtigen Sub-Parser aus.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


def _zu_float_de(s: str) -> Optional[float]:
    """Wandelt deutschen Dezimal-String (Komma) in float.
    ``'3,499'`` → ``3.499``. Tausenderpunkte werden entfernt.
    Liefert ``None`` bei nicht parsebar."""
    if s is None:
        return None
    s = str(s).strip().replace('\xa0', '').replace(' ', '')
    # Faelle: '3,499' / '1.234,56' / '371,434' / '1234'
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ── Utz (utz24.online) ───────────────────────────────────────────────────────
#
# Format der Bestellbestaetigung (Stand 2026):
#   Header-Block:  "Bestellung: <NR>, DD.MM.YYYY"
#                  "Kunden-Nr.: <NR>"
#   Positionen:    5-Zeilen-Block je Position (nach Whitespace-Strip):
#                    1. Artikel-Nr (rein numerisch, 1–7 Stellen)
#                    2. Bezeichnung (Freitext, evtl. mit Umlauten)
#                    3. Einzelpreis netto: "<komma>,<3-stellig> €"
#                    4. Menge (Integer oder Dezimal)
#                    5. Zeilenbetrag: "<komma>,<3-stellig> €"
#   Footer:        "Gesamtsumme  <betrag> €"
#
# Plain-Text aus PHPMailer (iso-8859-1) enthaelt &euro; statt €. Wir
# nehmen html.unescape() als sanfte Normalisierung und akzeptieren
# beide Varianten.

_UTZ_BEST_NR  = re.compile(
    r'Bestellung\s*:\s*(\d+)\s*,?\s*(\d{2}\.\d{2}\.\d{4})',
    re.IGNORECASE,
)
_UTZ_KUNDE    = re.compile(r'Kunden-?Nr\.?\s*:\s*(\d+)', re.IGNORECASE)
_UTZ_SUMME    = re.compile(
    r'Gesamtsumme[\s\S]{0,400}?([\d.\,]+)\s*(?:€|€|EUR)',
    re.IGNORECASE,
)

# Eine Zeile mit reinem Preis: "28,859 €" oder "28,859 &euro;" oder "28,859 EUR"
_PREIS_LINE   = re.compile(
    r'^([\d.\,]+)\s*(?:€|€|EUR)\s*$',
    re.IGNORECASE,
)
# Eine Zeile mit reiner Menge: "1", "28", "0.5", "0,5"
_MENGE_LINE   = re.compile(r'^\d+(?:[.,]\d+)?$')
# Artikel-Nr: 1–7 Ziffern (UTZ-intern)
_ARTNR_LINE   = re.compile(r'^\d{1,7}$')


def _utz_parse(plain_text: str) -> dict:
    daten: dict = {
        'best_nr':           '',
        'datum':             '',
        'kunden_nr':         None,
        'gesamtsumme_netto': None,
        'positionen':        [],
        'parser_key':        'utz_v1',
        'fehler':            None,
    }

    if not plain_text:
        daten['fehler'] = 'Leerer Mail-Text.'
        return daten

    # &euro; / &nbsp; / &uuml; usw. aufloesen
    text = html.unescape(plain_text).replace('\xa0', ' ')

    # Header
    m = _UTZ_BEST_NR.search(text)
    if m:
        daten['best_nr'] = m.group(1)
        # 'DD.MM.YYYY' → 'YYYY-MM-DD'
        d, mo, y = m.group(2).split('.')
        daten['datum'] = f'{y}-{mo}-{d}'
    else:
        daten['fehler'] = 'Bestellnummer nicht erkannt.'
        return daten

    m = _UTZ_KUNDE.search(text)
    if m:
        daten['kunden_nr'] = m.group(1)

    m = _UTZ_SUMME.search(text)
    if m:
        daten['gesamtsumme_netto'] = _zu_float_de(m.group(1))

    # Positionen via 5-Zeilen-State-Machine
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]   # Leerzeilen raus

    positionen: list[dict] = []
    i = 0
    pos_nr = 1
    while i < len(lines):
        line = lines[i]
        if _ARTNR_LINE.match(line) and i + 4 < len(lines):
            artnr  = line
            bez    = lines[i + 1]
            preis  = lines[i + 2]
            menge  = lines[i + 3]
            betrag = lines[i + 4]

            mp = _PREIS_LINE.match(preis)
            mm = _MENGE_LINE.match(menge)
            mb = _PREIS_LINE.match(betrag)

            # Heuristik: Bezeichnung darf nicht selbst wie Preis/Menge aussehen,
            # sonst war's eher ein anderer Zahl-Block.
            if (mp and mm and mb
                    and not _PREIS_LINE.match(bez)
                    and not _MENGE_LINE.match(bez)):
                positionen.append({
                    'pos_nr':           pos_nr,
                    'artikel_nr_lief':  artnr,
                    'bezeichnung_lief': bez[:255],
                    'preis_netto':      _zu_float_de(mp.group(1)),
                    'menge':            _zu_float_de(menge),
                    'zeilen_betrag':    _zu_float_de(mb.group(1)),
                })
                pos_nr += 1
                i += 5
                continue
        i += 1

    daten['positionen'] = positionen
    if not positionen:
        daten['fehler'] = 'Keine Positionen erkannt.'
    return daten


# ── Routing ──────────────────────────────────────────────────────────────────

_PARSER = {
    'utz_v1': _utz_parse,
}


def parse_email(parser_key: str, plain_text: str) -> dict:
    """Routet auf den passenden Lieferanten-Parser. Unbekannte Keys
    liefern ein dict mit ``fehler`` statt zu werfen."""
    fn = _PARSER.get((parser_key or '').strip())
    if not fn:
        return {
            'best_nr': '', 'datum': '', 'kunden_nr': None,
            'gesamtsumme_netto': None, 'positionen': [],
            'parser_key': parser_key,
            'fehler': f'Kein Parser fuer {parser_key!r} hinterlegt.',
        }
    try:
        return fn(plain_text)
    except Exception as exc:
        log.exception("Parser %s ist abgestuerzt", parser_key)
        return {
            'best_nr': '', 'datum': '', 'kunden_nr': None,
            'gesamtsumme_netto': None, 'positionen': [],
            'parser_key': parser_key,
            'fehler': f'Parser-Crash: {exc}',
        }
