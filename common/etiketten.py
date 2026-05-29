"""Artikel-Etiketten als SVG (Dorfkern-Reports, PoC).

Vektor-SVG = druckbar (→ PDF via Headless-Chromium möglich) UND direkt als
Bild im Browser anzeigbar. Layout hier in Python erzeugt (Barcode-Geometrie);
kann später in ein Jinja-SVG-Template ausgelagert werden.

Erzeugt ein Preis-Etikett mit Name, VK5-Brutto, Art-Nr und EAN-13-Barcode.
"""
from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

from common.db import get_db
from common import cao_artikel as _art

# STEUER_CODE → MwSt-Satz (CAO-Default; Code 2=7% bestätigt).
_RATE = {0: 0.0, 1: 0.19, 2: 0.07, 3: 0.0}

# ── EAN-13 ─────────────────────────────────────────────────────────────
_L = ['0001101', '0011001', '0010011', '0111101', '0100011',
      '0110001', '0101111', '0111011', '0110111', '0001011']
_G = ['0100111', '0110011', '0011011', '0100001', '0011101',
      '0111001', '0000101', '0010001', '0001001', '0010111']
_R = ['1110010', '1100110', '1101100', '1000010', '1011100',
      '1001110', '1010000', '1000100', '1001000', '1110100']
_PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
           'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL']


def _ean13_modules(code: str) -> str | None:
    """95-Modul-Bitmuster eines 13-stelligen EAN-Codes (oder None)."""
    if not (code and len(code) == 13 and code.isdigit()):
        return None
    d = [int(c) for c in code]
    bits = '101'  # Start-Guard
    for i, dig in enumerate(d[1:7]):
        bits += (_L if _PARITY[d[0]][i] == 'L' else _G)[dig]
    bits += '01010'  # Center-Guard
    for dig in d[7:]:
        bits += _R[dig]
    bits += '101'  # End-Guard
    return bits


def _ean13_svg(code: str, x: float, y: float, w: float, h: float) -> str:
    """EAN-13-Barcode als SVG-Fragment (Balken + Klartextziffern)."""
    bits = _ean13_modules(code)
    if not bits:
        # Kein valider EAN-13 → Code als Text
        return (f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
                f'font-family="monospace" font-size="9">{escape(code or "")}</text>')
    mod = w / 95.0
    # Guard-Balken etwas länger (klassisches EAN-Aussehen).
    guard = {*range(0, 3), *range(45, 50), *range(92, 95)}
    rects = []
    for i, b in enumerate(bits):
        if b == '1':
            bh = h + (4 if i in guard else 0)
            rects.append(f'<rect x="{x + i*mod:.2f}" y="{y:.2f}" '
                         f'width="{mod:.2f}" height="{bh:.2f}"/>')
    bars = f'<g fill="#000">{"".join(rects)}</g>'
    # Klartext: 1. Ziffer links, 6+6 unter den Hälften.
    ty = y + h + 11
    txt = (f'<g font-family="monospace" font-size="10" fill="#000">'
           f'<text x="{x-2:.1f}" y="{ty}" text-anchor="end">{code[0]}</text>'
           f'<text x="{x + 3*mod + 21*mod:.1f}" y="{ty}" text-anchor="middle">{code[1:7]}</text>'
           f'<text x="{x + 50*mod + 21*mod:.1f}" y="{ty}" text-anchor="middle">{code[7:]}</text></g>')
    return bars + txt


# ── Artikel-Etikett ────────────────────────────────────────────────────

def _artikel(rec_id: int) -> dict[str, Any] | None:
    sql = """SELECT a.REC_ID, a.ARTNUM, a.BARCODE, a.STEUER_CODE,
                    COALESCE(NULLIF(a.KAS_NAME,''),a.KURZNAME,a.MATCHCODE) AS NAME,
                    a.VK5B, a.GEWICHT, a.BASISPR_FAKTOR,
                    me.BEZEICHNUNG AS ME, bme.BEZEICHNUNG AS BASIS_ME
               FROM ARTIKEL a
               LEFT JOIN MENGENEINHEIT me ON me.REC_ID=a.ME_ID
               LEFT JOIN MENGENEINHEIT bme ON bme.REC_ID=a.BASISPR_ME_ID
              WHERE a.REC_ID=%s"""
    with get_db() as cur:
        cur.execute(sql, (int(rec_id),))
        return cur.fetchone()


def grundpreis(a: dict[str, Any], preis_brutto: float | None = None) -> str:
    """Grundpreis-Angabe (PAngV): Preis-Brutto × Basispreis-Faktor / Gewicht,
    je Basispreis-Einheit. ``preis_brutto`` überschreibt VK5B (→ bei aktivem
    Angebot auf Angebotsbasis). Leer, wenn keine Füllmenge/Einheit."""
    g = float(a.get('GEWICHT') or 0)
    f = float(a.get('BASISPR_FAKTOR') or 0)
    vk = float(preis_brutto if preis_brutto is not None else (a.get('VK5B') or 0))
    einheit = a.get('BASIS_ME')
    if g <= 0 or f <= 0 or not einheit or vk <= 0:
        return ''
    cent = f'{vk * f / g:.2f} €'.replace('.', ',')
    return cent + (f' / {einheit}' if f == 1 else f' / {f:g} {einheit}')


def _eur(v: float) -> str:
    return f'{v:.2f} €'.replace('.', ',')


def aktiver_angebotspreis_brutto(rec_id: int, rate: float) -> float | None:
    """Brutto-Angebotspreis (VK5), falls heute ein CAO-Aktionspreis aktiv ist."""
    akt = _art.aktionspreis(rec_id)
    if not akt or not akt.get('PREIS5'):
        return None
    heute = date.today()
    von, bis = akt.get('GUELTIG_VON'), akt.get('GUELTIG_BIS')
    if (von is None or von <= heute) and (bis is None or heute <= bis):
        return round(float(akt['PREIS5']) * (1 + rate), 2)
    return None


def artikel_etikett_svg(rec_id: int, *, laden: str = 'Habacher Dorfladen') -> str:
    """Preis-Etikett (~50x30 mm) als SVG. Bei aktivem Angebot wird der
    Originalpreis durchgestrichen, der Angebotspreis hervorgehoben und der
    Grundpreis auf Angebotsbasis gerechnet."""
    a = _artikel(rec_id) or {}
    name = (a.get('NAME') or '-')
    regular = float(a.get('VK5B') or 0)
    artnum = a.get('ARTNUM') or ''
    barcode = (a.get('BARCODE') or '').strip()
    rate = _RATE.get(int(a.get('STEUER_CODE') or 0), 0.0)
    angebot = aktiver_angebotspreis_brutto(rec_id, rate)
    eff = angebot if angebot is not None else regular
    if len(name) > 24:
        cut = name.rfind(' ', 0, 24) or 24
        z1, z2 = escape(name[:cut]), escape(name[cut:].strip()[:24])
    else:
        z1, z2 = escape(name), ''
    gp = grundpreis(a, eff)
    gp_svg = (f'<text x="238" y="106" text-anchor="end" font-family="sans-serif" '
              f'font-size="11" fill="#5a7a3a">Grundpreis {escape(gp)}</text>'
              if gp else '')
    if angebot is not None:
        preis_svg = (
            '<rect x="150" y="6" width="88" height="18" rx="9" fill="#b30000"/>'
            '<text x="194" y="19" text-anchor="middle" font-family="sans-serif" '
            'font-size="11" font-weight="800" fill="#fff">ANGEBOT</text>'
            f'<text x="238" y="58" text-anchor="end" font-family="sans-serif" '
            f'font-size="16" fill="#999" text-decoration="line-through">{_eur(regular)}</text>'
            f'<text x="238" y="92" text-anchor="end" font-family="sans-serif" '
            f'font-size="34" font-weight="800" fill="#b30000">{_eur(angebot)}</text>')
    else:
        preis_svg = (f'<text x="238" y="86" text-anchor="end" font-family="sans-serif" '
                     f'font-size="32" font-weight="800" fill="#2e6e1a">{_eur(regular)}</text>')
    bc = _ean13_svg(barcode, 18, 118, 214, 24)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 170" width="250" height="170">
<rect x="1" y="1" width="248" height="168" rx="6" fill="#fff" stroke="#cdd5c0"/>
<text x="12" y="18" font-family="sans-serif" font-size="9" fill="#5a7a3a">{escape(laden)}</text>
<text x="12" y="40" font-family="sans-serif" font-size="15" font-weight="700" fill="#1c1c12">{z1}</text>
<text x="12" y="57" font-family="sans-serif" font-size="13" fill="#33321b">{z2}</text>
{preis_svg}
{gp_svg}
<text x="12" y="94" font-family="monospace" font-size="9" fill="#5a7a3a">Art-Nr {escape(artnum)}</text>
{bc}
</svg>'''
