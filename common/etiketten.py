"""Artikel-Etiketten als SVG (Dorfkern-Reports, PoC).

Vektor-SVG = druckbar (→ PDF via Headless-Chromium möglich) UND direkt als
Bild im Browser anzeigbar. Layout hier in Python erzeugt (Barcode-Geometrie);
kann später in ein Jinja-SVG-Template ausgelagert werden.

Erzeugt ein Preis-Etikett mit Name, VK5-Brutto, Art-Nr und EAN-13-Barcode.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
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


def _ean13_svg(code: str, x: float, y: float, w: float, h: float,
               font_size: float | None = None) -> str:
    """EAN-13-Barcode als SVG-Fragment (Balken + Klartextziffern).
    Schriftgröße proportional zur Balkenhöhe (für mm- und px-Einheiten ok)."""
    fs = font_size if font_size is not None else max(h * 0.32, 1.5)
    bits = _ean13_modules(code)
    if not bits:
        return (f'<text x="{x + w/2}" y="{y + h/2}" text-anchor="middle" '
                f'font-family="monospace" font-size="{fs:.2f}">{escape(code or "")}</text>')
    mod = w / 95.0
    guard_ext = h * 0.18
    guard = {*range(0, 3), *range(45, 50), *range(92, 95)}
    rects = []
    for i, b in enumerate(bits):
        if b == '1':
            bh = h + (guard_ext if i in guard else 0)
            rects.append(f'<rect x="{x + i*mod:.3f}" y="{y:.3f}" '
                         f'width="{mod:.3f}" height="{bh:.3f}"/>')
    bars = f'<g fill="#000">{"".join(rects)}</g>'
    ty = y + h + fs * 0.95 + 0.4
    txt = (f'<g font-family="monospace" font-size="{fs:.2f}" fill="#000">'
           f'<text x="{x - fs*0.2:.2f}" y="{ty:.2f}" text-anchor="end">{code[0]}</text>'
           f'<text x="{x + 24*mod:.2f}" y="{ty:.2f}" text-anchor="middle">{code[1:7]}</text>'
           f'<text x="{x + 71*mod:.2f}" y="{ty:.2f}" text-anchor="middle">{code[7:]}</text></g>')
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


def verpackungsmenge(a: dict[str, Any]) -> str:
    """Verpackungsgröße als Klartext: <1 kg → 'X g', sonst 'X,X kg'."""
    g = float(a.get('GEWICHT') or 0)
    if g <= 0:
        return ''
    if g < 1:
        return f'{int(round(g * 1000))} g'
    s = f'{g:g}'.replace('.', ',')
    return f'{s} kg'


def niedrigster_preis_30tage(rec_id: int, vor: date) -> float | None:
    """§ 11 PAngV: niedrigster Brutto-VK5 in den 30 Tagen vor ``vor``.

    Quellen: aktueller VK5B + ARTIKEL_LOG (VK5 und AKTION_VK5 mit
    Gültigkeit im Fenster) + angewendete XT-Aktionen
    (XT_ARTIKEL_PREISPLAN, art='aktion'). Gibt None zurück, wenn keine.
    """
    von_d = vor - timedelta(days=30)
    bis_d = vor - timedelta(days=1)
    von_ts = datetime.combine(von_d, datetime.min.time())
    bis_ts = datetime.combine(bis_d, datetime.max.time())
    cands: list[float] = []
    with get_db() as cur:
        cur.execute("SELECT VK5B, STEUER_CODE FROM ARTIKEL WHERE REC_ID=%s",
                    (int(rec_id),))
        a = cur.fetchone() or {}
    if a.get('VK5B') is not None and float(a['VK5B']) > 0:
        cands.append(float(a['VK5B']))
    fb = _RATE.get(int(a.get('STEUER_CODE') or 0), 0.0)
    with get_db() as cur:
        cur.execute("""SELECT VK5, AKTION_VK5, AKTION_VON, AKTION_BIS,
                              STEUER_SATZ
                       FROM ARTIKEL_LOG
                       WHERE ARTIKEL_ID=%s AND GEAEND>=%s AND GEAEND<=%s""",
                    (int(rec_id), von_ts, bis_ts))
        log_rows = list(cur.fetchall() or [])
    for r in log_rows:
        rate = (float(r['STEUER_SATZ']) / 100
                if r.get('STEUER_SATZ') is not None else fb)
        if r.get('VK5') and float(r['VK5']) > 0:
            cands.append(round(float(r['VK5']) * (1 + rate), 2))
        akt5 = r.get('AKTION_VK5')
        if akt5 and float(akt5) > 0:
            av, ab = r.get('AKTION_VON'), r.get('AKTION_BIS')
            if isinstance(av, datetime):
                av = av.date()
            if isinstance(ab, datetime):
                ab = ab.date()
            if ((av is None or av <= bis_d)
                    and (ab is None or ab >= von_d)):
                cands.append(round(float(akt5) * (1 + rate), 2))
    with get_db() as cur:
        cur.execute("""SELECT vk5 FROM XT_ARTIKEL_PREISPLAN
                       WHERE artikel_id=%s AND art='aktion'
                         AND status IN ('aktiv','beendet')
                         AND angewendet_am IS NOT NULL
                         AND gueltig_ab<=%s
                         AND (gueltig_bis IS NULL OR gueltig_bis>=%s)""",
                    (int(rec_id), bis_d, von_d))
        for r in cur.fetchall() or []:
            if r['vk5'] and float(r['vk5']) > 0:
                cands.append(round(float(r['vk5']) * (1 + fb), 2))
    return min(cands) if cands else None


def artikel_etikett_svg(rec_id: int, *, laden: str = '') -> str:
    """Regaletikett 70x38 mm, monochrom (thermodrucker-tauglich), PAngV-konform:
    Endpreis (>= 6 mm), Grundpreis (~ 3 mm) auf Angebotsbasis, Verpackungs-
    menge, Streichpreis = niedrigster Preis der letzten 30 Tage (§ 11 PAngV).
    Barcode + Nummer oben links, Druckdatum oben rechts.
    """
    a = _artikel(rec_id) or {}
    name = (a.get('NAME') or '-')
    regular = float(a.get('VK5B') or 0)
    artnum = a.get('ARTNUM') or ''
    barcode = (a.get('BARCODE') or '').strip()
    rate = _RATE.get(int(a.get('STEUER_CODE') or 0), 0.0)
    angebot = aktiver_angebotspreis_brutto(rec_id, rate)
    eff = angebot if angebot is not None else regular
    heute = date.today().strftime('%d.%m.%Y')
    verp = verpackungsmenge(a)
    # Streichpreis = niedrigster Brutto-VK5 der 30 Tage vor Aktions-Start.
    streich = None
    if angebot is not None:
        akt = _art.aktionspreis(rec_id) or {}
        vor = akt.get('GUELTIG_VON') or date.today()
        if isinstance(vor, datetime):
            vor = vor.date()
        n30 = niedrigster_preis_30tage(rec_id, vor)
        if n30 is not None and n30 > angebot + 0.005:
            streich = n30
    # Name ggf. 2 Zeilen (~ 30 Zeichen je Zeile bei 66 mm Breite).
    if len(name) > 30:
        cut = name.rfind(' ', 0, 30) or 30
        z1, z2 = escape(name[:cut]), escape(name[cut:].strip()[:34])
    else:
        z1, z2 = escape(name), ''
    gp = grundpreis(a, eff)
    bc = _ean13_svg(barcode, 2, 2, 30, 7)
    verp_svg = (f'<text x="2" y="22.5" font-family="sans-serif" font-size="2.7"'
                f' fill="#000">{escape(verp)}</text>' if verp else '')
    if angebot is not None:
        strike_svg = (
            f'<text x="68" y="23" text-anchor="end" font-family="sans-serif"'
            f' font-size="3" fill="#000" text-decoration="line-through">'
            f'{_eur(streich)}</text>' if streich is not None else '')
        preis_svg = (
            '<rect x="34" y="2.4" width="14" height="4.4" fill="#000"/>'
            '<text x="41" y="5.8" text-anchor="middle" font-family="sans-serif"'
            ' font-size="2.7" font-weight="800" fill="#fff">ANGEBOT</text>'
            + strike_svg +
            f'<text x="68" y="31" text-anchor="end" font-family="sans-serif"'
            f' font-size="9" font-weight="800" fill="#000">{_eur(angebot)}</text>')
    else:
        preis_svg = (f'<text x="68" y="30" text-anchor="end" font-family="sans-serif"'
                     f' font-size="8" font-weight="800" fill="#000">{_eur(regular)}</text>')
    gp_svg = (f'<text x="2" y="36.5" font-family="sans-serif" font-size="3" fill="#000">'
              f'Grundpreis {escape(gp)}</text>' if gp else '')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 70 38" width="70mm" height="38mm">
<rect x="0.1" y="0.1" width="69.8" height="37.8" fill="#fff" stroke="#000" stroke-width="0.1"/>
{bc}
<text x="68" y="4" text-anchor="end" font-family="sans-serif" font-size="2.2" fill="#000">{heute}</text>
<text x="2" y="16" font-family="sans-serif" font-size="3.5" font-weight="700" fill="#000">{z1}</text>
<text x="2" y="20" font-family="sans-serif" font-size="2.8" fill="#000">{z2}</text>
{verp_svg}
{preis_svg}
{gp_svg}
<text x="68" y="36.5" text-anchor="end" font-family="sans-serif" font-size="2.5" fill="#000">Art-Nr {escape(artnum)}</text>
</svg>'''
