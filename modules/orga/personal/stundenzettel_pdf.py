"""
Stundenzettel-PDF-Generator (monatlich, pro Mitarbeiter).

Erzeugt ein A4-Hochformat-PDF mit einer Tabelle pro Tag und einer
Summenzeile unter der Tabelle. Ablage gedacht fuer Google Drive –
keine Unterschriftenzeile.

Datenquelle: :func:`modules.orga.personal.models.stundenzettel_monat_daten`.
"""
from __future__ import annotations

import io
from datetime import datetime


def _hstr(minuten: int | None) -> str:
    """'325' → '5:25'. Negative Werte mit '-', 0 → ''."""
    if minuten is None or minuten == 0:
        return ''
    neg = minuten < 0
    m = abs(int(minuten))
    h, rest = divmod(m, 60)
    return f'{"-" if neg else ""}{h}:{rest:02d}'


def _hstr_immer(minuten: int | None) -> str:
    """Wie :func:`_hstr`, aber 0 wird als '0:00' ausgegeben (fuer Summenzeile)."""
    if minuten is None:
        return '0:00'
    neg = minuten < 0
    m = abs(int(minuten))
    h, rest = divmod(m, 60)
    return f'{"-" if neg else ""}{h}:{rest:02d}'


def _tage_str(tage: float) -> str:
    if tage is None:
        return ''
    return f'{float(tage):.1f}'.replace('.', ',')


def stundenzettel_als_pdf(daten: dict, firma_name: str = '') -> bytes:
    """Erzeugt PDF-Bytes fuer einen monatlichen Stundenzettel.

    ``daten`` ist das Dict aus
    :func:`modules.orga.personal.models.stundenzettel_monat_daten`.
    ``firma_name`` erscheint als Untertitel (optional).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 1.5 * cm

    ma = daten['ma']
    ma_name = f"{ma.get('NAME', '')}, {ma.get('VNAME', '')}".strip(', ')
    pers_nr = ma.get('PERSONALNUMMER') or ''
    kuerzel = ma.get('KUERZEL') or ''
    titel = f"Stundenzettel {daten['monats_name']} {daten['jahr']}"
    jetzt = datetime.now().strftime('%d.%m.%Y %H:%M')

    # Styles
    normal     = ParagraphStyle('n',  fontName='Helvetica',      fontSize=8,  leading=10)
    bold       = ParagraphStyle('b',  fontName='Helvetica-Bold',  fontSize=8,  leading=10)
    small      = ParagraphStyle('s',  fontName='Helvetica',      fontSize=7,  leading=9, textColor=colors.grey)
    header_s   = ParagraphStyle('h',  fontName='Helvetica-Bold',  fontSize=13, leading=16)

    HDR_COLOR  = colors.HexColor('#e8f4e8')
    ALT_COLOR  = colors.HexColor('#f9f9f9')
    WE_COLOR   = colors.HexColor('#f4f1e3')
    FT_COLOR   = colors.HexColor('#fdf5d9')
    LINE_COLOR = colors.HexColor('#cccccc')

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=3.0 * cm, bottomMargin=2.2 * cm,
        title=titel, author='CAO-XT Orga-Personal',
    )

    # ── Tages-Tabelle ───────────────────────────────────────────────────────
    # Spalten: Datum (mit Wochentag) | Arbeit | Abwes. | Urlaub | Krank
    #        | Abbau Überst. | Feiertag
    kopf = [
        'Datum',
        'Arbeits-\nzeit',
        'Abwesenh.\n(betriebl.)',
        'Urlaub',
        'Krank-\nmeldung',
        'Abbau\nÜberstd.',
        'Feiertag',
    ]
    tabellen_daten: list[list] = [kopf]
    tag_styles: list[tuple] = []  # (row_index, style-tuple) fuer Hintergrund

    # Spalten-Summen fuer die Summenzeile unten in der Tabelle.
    sum_arbeit = sum_abwes = sum_urlaub = sum_krank = sum_abbau = sum_feiertag = 0

    for idx, t in enumerate(daten['tage'], start=1):
        d = t['datum']
        datum_str = f"{t['wochentag']}  {d.strftime('%d.%m.%Y')}"
        if t['feiertag_name']:
            datum_str += f"  ({t['feiertag_name']})"
        row = [
            datum_str,
            _hstr(t['arbeit_min']),
            _hstr(t['abwesenheit_min']),
            _hstr(t['urlaub_min']),
            _hstr(t['krank_min']),
            _hstr(t['abbau_ueberstunden_min']),
            _hstr(t['feiertag_min']),
        ]
        tabellen_daten.append(row)
        sum_arbeit   += int(t['arbeit_min'] or 0)
        sum_abwes    += int(t['abwesenheit_min'] or 0)
        sum_urlaub   += int(t['urlaub_min'] or 0)
        sum_krank    += int(t['krank_min'] or 0)
        sum_abbau    += int(t['abbau_ueberstunden_min'] or 0)
        sum_feiertag += int(t['feiertag_min'] or 0)
        if t['feiertag_name']:
            tag_styles.append(('BACKGROUND', (0, idx), (-1, idx), FT_COLOR))
        elif t['wochenende']:
            tag_styles.append(('BACKGROUND', (0, idx), (-1, idx), WE_COLOR))

    # Summenzeile unten an der Tabelle.
    summen_row = [
        'Gesamt',
        _hstr_immer(sum_arbeit),
        _hstr_immer(sum_abwes),
        _hstr_immer(sum_urlaub),
        _hstr_immer(sum_krank),
        _hstr_immer(sum_abbau),
        _hstr_immer(sum_feiertag),
    ]
    tabellen_daten.append(summen_row)
    summen_row_idx = len(tabellen_daten) - 1

    # Spaltenbreiten (Summe ~ 18 cm bei 1.5cm Seitenrand auf A4)
    col_widths = [5.0*cm, 1.9*cm, 2.4*cm, 1.8*cm, 2.0*cm, 2.0*cm, 1.9*cm]

    tabelle = Table(tabellen_daten, colWidths=col_widths, repeatRows=1)
    ts = TableStyle([
        ('FONT',       (0, 0), (-1, 0), 'Helvetica-Bold', 8),
        ('BACKGROUND', (0, 0), (-1, 0), HDR_COLOR),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, 0), 'MIDDLE'),
        ('FONT',       (0, 1), (-1, -1), 'Helvetica', 8),
        ('ALIGN',      (0, 1), (0, -1), 'LEFT'),       # Datum linksbuendig
        ('ALIGN',      (1, 1), (-1, -1), 'RIGHT'),
        ('VALIGN',     (0, 1), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.3, LINE_COLOR),
        ('LEFTPADDING',  (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
        # Summenzeile optisch hervorheben.
        ('FONT',       (0, summen_row_idx), (-1, summen_row_idx), 'Helvetica-Bold', 8),
        ('BACKGROUND', (0, summen_row_idx), (-1, summen_row_idx), HDR_COLOR),
        ('LINEABOVE',  (0, summen_row_idx), (-1, summen_row_idx), 0.8, LINE_COLOR),
    ])
    for tstyle in tag_styles:
        ts.add(*tstyle)
    tabelle.setStyle(ts)

    # ── Summen-Tabelle (unterhalb der Haupttabelle) ─────────────────────────
    s = daten['summe']

    saldo_monat     = s['saldo_monat_min']
    saldo_vormonate = s.get('saldo_vormonate_min', 0)
    saldo_kum       = s['saldo_kumuliert_min']

    def _mit_vz(minuten: int) -> str:
        if minuten is None or minuten == 0:
            return '0:00'
        vz = '+' if minuten > 0 else '-'
        m = abs(int(minuten))
        h, rest = divmod(m, 60)
        return f'{vz}{h}:{rest:02d}'

    # Zwei-Spalten-Layout: links Stunden-Kennzahlen, rechts Urlaubs-Kennzahlen.
    # Leer-Tupel = Trennzeile (1 Zeile Abstand).
    links: list[tuple[str, str]] = [
        ('Gesamt (Monat)',                 _hstr_immer(s['gesamt_min'])),
        ('Soll (Monat)',                   _hstr_immer(s['soll_min'])),
        ('Korrekturen (Fehler)',           _mit_vz(s['korrektur_monat_min'])),
        ('Saldo aktueller Monat',          _mit_vz(saldo_monat)),
        ('Saldo Vormonate',                _mit_vz(saldo_vormonate)),
        ('Saldo kumuliert',                _mit_vz(saldo_kum)),
        ('', ''),  # ← 1 Zeile Abstand
        ('Arbeitszeit an Sonntagen',       _hstr_immer(s['sonntagsarbeit_min'])),
        ('Arbeitszeit an Feiertagen',      _hstr_immer(s['feiertagsarbeit_min'])),
    ]
    rechts: list[tuple[str, str]] = [
        ('Urlaubsanspruch Monatsbeginn',   f"{_tage_str(s['urlaub_beginn_tage'])} Tage"),
        ('Urlaub im Monat',                f"{_tage_str(s['urlaub_monat_tage'])} Tage"),
        ('Urlaubsanspruch Monatsende',     f"{_tage_str(s['urlaub_ende_tage'])} Tage"),
    ]
    if s.get('uebertrag_korrektur_min'):
        rechts.append(('Übertrag Vorjahr (Korrektur)',
                       _mit_vz(s['uebertrag_korrektur_min'])))

    # Indizes merken fuer optische Hervorhebungen.
    idx_saldo_monat = next(
        (i for i, e in enumerate(links) if e[0] == 'Saldo aktueller Monat'), -1)
    idx_saldo_kum = next(
        (i for i, e in enumerate(links) if e[0] == 'Saldo kumuliert'), -1)

    # Summentabelle als 4-Spalten-Layout: Label | Wert | Label | Wert
    sum_rows: list[list] = []
    for i in range(max(len(links), len(rechts))):
        l = links[i] if i < len(links) else ('', '')
        r = rechts[i] if i < len(rechts) else ('', '')
        sum_rows.append([l[0], l[1], r[0], r[1]])

    sum_tabelle = Table(
        sum_rows,
        colWidths=[5.0*cm, 2.5*cm, 6.0*cm, 3.5*cm],
    )
    sum_style = TableStyle([
        ('FONT',       (0, 0), (-1, -1), 'Helvetica', 9),
        ('FONT',       (0, 0), (0, -1), 'Helvetica-Bold', 9),
        ('FONT',       (2, 0), (2, -1), 'Helvetica-Bold', 9),
        ('ALIGN',      (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN',      (3, 0), (3, -1), 'RIGHT'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING',   (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
    ])
    # Saldo aktueller Monat: feine Trennlinie darueber.
    if idx_saldo_monat >= 0:
        sum_style.add('LINEABOVE', (0, idx_saldo_monat), (1, idx_saldo_monat),
                      0.3, LINE_COLOR)
    # Saldo kumuliert: Fett + Trennlinie (Schluss-Summe).
    if idx_saldo_kum >= 0:
        sum_style.add('LINEABOVE', (0, idx_saldo_kum), (1, idx_saldo_kum),
                      0.8, LINE_COLOR)
        sum_style.add('FONT', (0, idx_saldo_kum), (1, idx_saldo_kum),
                      'Helvetica-Bold', 9)
    sum_tabelle.setStyle(sum_style)

    # ── Header/Footer via onPage-Callback ───────────────────────────────────
    def _header_footer(canvas, doc):
        canvas.saveState()
        # Header
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawString(MARGIN, PAGE_H - 1.3*cm, titel)
        canvas.setFont('Helvetica', 9)
        ma_line = ma_name
        if pers_nr:
            ma_line += f"  ·  Personalnummer {pers_nr}"
        if kuerzel:
            ma_line += f"  ·  Kürzel {kuerzel}"
        canvas.drawString(MARGIN, PAGE_H - 1.9*cm, ma_line)
        if daten.get('regel_az_label'):
            canvas.setFillColor(colors.grey)
            canvas.drawString(MARGIN, PAGE_H - 2.4*cm,
                              f"Arbeitszeitmodell: {daten['regel_az_label']}")
            canvas.setFillColor(colors.black)
        if firma_name:
            canvas.setFont('Helvetica', 9)
            canvas.setFillColor(colors.grey)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.9*cm, firma_name)
            canvas.setFillColor(colors.black)
        canvas.setStrokeColor(LINE_COLOR)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - 2.7*cm, PAGE_W - MARGIN, PAGE_H - 2.7*cm)
        # Footer
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(MARGIN, 1.0*cm, f"Gedruckt: {jetzt}")
        canvas.drawRightString(PAGE_W - MARGIN, 1.0*cm,
                               f"Seite {canvas.getPageNumber()}")
        canvas.restoreState()

    story = [
        tabelle,
        Spacer(1, 0.4*cm),
        sum_tabelle,
    ]
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


def batch_als_zip(stundenzettel_liste: list[dict],
                  firma_name: str = '') -> bytes:
    """Erzeugt ein ZIP mit je einer PDF pro MA.

    Dateinamen: ``Stundenzettel_<Monat>_<Jahr>_<NAME>_<VNAME>.pdf``
    (Sonderzeichen werden durch Unterstriche ersetzt).
    """
    import zipfile
    import re

    def _safe(s: str) -> str:
        s = (s or '').strip()
        return re.sub(r'[^A-Za-z0-9._-]', '_', s) or 'MA'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for d in stundenzettel_liste:
            ma = d['ma']
            pdf = stundenzettel_als_pdf(d, firma_name=firma_name)
            dateiname = (
                f"Stundenzettel_{d['monats_name']}_{d['jahr']}_"
                f"{_safe(ma.get('NAME') or '')}_"
                f"{_safe(ma.get('VNAME') or '')}.pdf"
            )
            zf.writestr(dateiname, pdf)
    return buf.getvalue()
