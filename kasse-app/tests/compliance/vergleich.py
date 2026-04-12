"""Vergleichs-Engine: Feld-für-Feld-Diff zwischen XT-Kasse und CAO-Kasse.

Erzeugt eine Compliance-Matrix als strukturiertes Ergebnis und als
Markdown-Dokument.
"""

from dataclasses import dataclass, field
from datetime import datetime

from compliance.cao_referenz import (
    BEKANNTE_ABWEICHUNGEN,
    CAO_STANDARD_KASSENBON,
    TabellenErwartung,
)


@dataclass
class FeldVergleich:
    """Ergebnis eines Feld-für-Feld-Vergleichs."""
    tabelle: str
    feld: str
    xt_wert: object
    cao_erwartung: object
    status: str           # 'OK', 'ABWEICHUNG', 'FEHLT_XT', 'FEHLT_CAO', 'NICHT_GEPRUEFT'
    pflicht: bool = True
    beschreibung: str = ''
    risiko: str = ''      # 'hoch', 'mittel', 'niedrig', ''


@dataclass
class TabellenVergleich:
    """Vergleichsergebnis für eine Tabelle."""
    tabelle: str
    cao_operation: str
    xt_operation: str
    felder: list = field(default_factory=list)  # [FeldVergleich, ...]
    status: str = ''  # 'IDENTISCH', 'ABWEICHUNG', 'FEHLT_XT', 'FEHLT_CAO'


@dataclass
class ComplianceMatrix:
    """Gesamt-Compliance-Matrix über alle Tabellen."""
    tabellen: list = field(default_factory=list)  # [TabellenVergleich, ...]
    zeitpunkt: str = ''
    xt_version: str = 'XT-Kasse (current)'
    cao_version: str = 'CAO-Kasse Pro v1.5.5.66'

    @property
    def anzahl_ok(self) -> int:
        return sum(1 for t in self.tabellen for f in t.felder if f.status == 'OK')

    @property
    def anzahl_abweichung(self) -> int:
        return sum(1 for t in self.tabellen for f in t.felder if f.status == 'ABWEICHUNG')

    @property
    def anzahl_fehlt_xt(self) -> int:
        return sum(1 for t in self.tabellen
                   for f in t.felder if f.status == 'FEHLT_XT')

    @property
    def anzahl_gesamt(self) -> int:
        return sum(len(t.felder) for t in self.tabellen)


def xt_buchung_analysieren(journal_row: dict | None,
                           journalpos_rows: list | None,
                           delta: object | None = None) -> ComplianceMatrix:
    """Analysiert eine XT-Buchung gegen die CAO-Referenz.

    Args:
        journal_row: JOURNAL-Datensatz der XT-Buchung (oder None wenn nicht vorhanden).
        journalpos_rows: Liste der JOURNALPOS-Datensätze (oder None).
        delta: BuchungsDelta-Objekt (optional, für Tabellen-Coverage).

    Returns:
        ComplianceMatrix mit Feld-für-Feld-Vergleich.
    """
    matrix = ComplianceMatrix(zeitpunkt=datetime.now().isoformat())
    journalpos_rows = journalpos_rows or []

    for erwartung in CAO_STANDARD_KASSENBON:
        tv = _tabelle_vergleichen(erwartung, journal_row, journalpos_rows, delta)
        matrix.tabellen.append(tv)

    return matrix


def _tabelle_vergleichen(erwartung: TabellenErwartung,
                         journal_row: dict | None,
                         journalpos_rows: list,
                         delta: object | None) -> TabellenVergleich:
    """Vergleicht eine einzelne Tabelle gegen die CAO-Erwartung."""

    tabelle = erwartung.tabelle
    tv = TabellenVergleich(
        tabelle=tabelle,
        cao_operation=erwartung.operation,
        xt_operation='',
    )

    # Prüfe ob die Tabelle vom XT überhaupt geschrieben wird
    abweichung_key = tabelle
    if tabelle == 'TSE_LOG':
        abweichung_key = 'TSE_LOG.TABELLE'

    if abweichung_key in BEKANNTE_ABWEICHUNGEN:
        abw = BEKANNTE_ABWEICHUNGEN[abweichung_key]
        if abw['xt_wert'] == 'FEHLT':
            tv.xt_operation = 'FEHLT'
            tv.status = 'FEHLT_XT'
            for fe in erwartung.felder:
                tv.felder.append(FeldVergleich(
                    tabelle=tabelle,
                    feld=fe.feld,
                    xt_wert='(nicht implementiert)',
                    cao_erwartung=fe.cao_wert,
                    status='FEHLT_XT',
                    pflicht=fe.pflicht,
                    beschreibung=fe.beschreibung,
                    risiko=abw.get('risiko', ''),
                ))
            return tv

    # JOURNAL: Feld-für-Feld-Vergleich
    if tabelle == 'JOURNAL' and journal_row:
        tv.xt_operation = 'INSERT+UPDATE'
        tv.status = 'ABWEICHUNG'  # Wird ggf. auf IDENTISCH gesetzt
        alle_ok = True
        for fe in erwartung.felder:
            xt_val = journal_row.get(fe.feld)
            status = _feld_status(fe.feld, xt_val, fe.cao_wert, fe.exakt, tabelle)
            if status != 'OK':
                alle_ok = False
            risiko = ''
            bka_key = f'{tabelle}.{fe.feld}'
            if bka_key in BEKANNTE_ABWEICHUNGEN:
                risiko = BEKANNTE_ABWEICHUNGEN[bka_key].get('risiko', '')
            tv.felder.append(FeldVergleich(
                tabelle=tabelle,
                feld=fe.feld,
                xt_wert=xt_val,
                cao_erwartung=fe.cao_wert,
                status=status,
                pflicht=fe.pflicht,
                beschreibung=fe.beschreibung,
                risiko=risiko,
            ))
        if alle_ok:
            tv.status = 'IDENTISCH'
        return tv

    # JOURNALPOS: Prüfe erste Position als Beispiel
    if tabelle == 'JOURNALPOS' and journalpos_rows:
        tv.xt_operation = 'INSERT'
        tv.status = 'ABWEICHUNG'
        pos = journalpos_rows[0]
        alle_ok = True
        for fe in erwartung.felder:
            xt_val = pos.get(fe.feld)
            status = _feld_status(fe.feld, xt_val, fe.cao_wert, fe.exakt, tabelle)
            if status != 'OK':
                alle_ok = False
            risiko = ''
            bka_key = f'{tabelle}.{fe.feld}'
            if bka_key in BEKANNTE_ABWEICHUNGEN:
                risiko = BEKANNTE_ABWEICHUNGEN[bka_key].get('risiko', '')
            tv.felder.append(FeldVergleich(
                tabelle=tabelle,
                feld=fe.feld,
                xt_wert=xt_val,
                cao_erwartung=fe.cao_wert,
                status=status,
                pflicht=fe.pflicht,
                beschreibung=fe.beschreibung,
                risiko=risiko,
            ))
        if alle_ok:
            tv.status = 'IDENTISCH'
        return tv

    # TSE_LOG: XT nutzt eigene Tabelle
    if tabelle == 'TSE_LOG':
        abw = BEKANNTE_ABWEICHUNGEN.get('TSE_LOG.TABELLE', {})
        tv.xt_operation = 'XT_KASSE_TSE_LOG'
        tv.status = 'ABWEICHUNG'
        for fe in erwartung.felder:
            tv.felder.append(FeldVergleich(
                tabelle=tabelle,
                feld=fe.feld,
                xt_wert='(in XT_KASSE_TSE_LOG)',
                cao_erwartung=fe.cao_wert,
                status='ABWEICHUNG',
                pflicht=fe.pflicht,
                beschreibung=fe.beschreibung,
                risiko=abw.get('risiko', 'mittel'),
            ))
        return tv

    # Tabelle nicht analysierbar (keine Daten)
    tv.xt_operation = 'UNBEKANNT'
    tv.status = 'NICHT_GEPRUEFT'
    for fe in erwartung.felder:
        tv.felder.append(FeldVergleich(
            tabelle=tabelle,
            feld=fe.feld,
            xt_wert=None,
            cao_erwartung=fe.cao_wert,
            status='NICHT_GEPRUEFT',
            pflicht=fe.pflicht,
            beschreibung=fe.beschreibung,
        ))
    return tv


def _feld_status(feld: str, xt_wert, cao_erwartung, exakt: bool,
                 tabelle: str) -> str:
    """Bestimmt den Vergleichsstatus eines Feldes."""
    if xt_wert is None:
        return 'FEHLT_XT'

    # Bekannte Abweichung?
    bka_key = f'{tabelle}.{feld}'
    if bka_key in BEKANNTE_ABWEICHUNGEN:
        return 'ABWEICHUNG'

    # Exakter Vergleich bei festen Werten
    if exakt and not isinstance(cao_erwartung, str):
        if isinstance(cao_erwartung, float):
            try:
                return 'OK' if abs(float(xt_wert) - cao_erwartung) < 0.001 else 'ABWEICHUNG'
            except (TypeError, ValueError):
                return 'ABWEICHUNG'
        if str(xt_wert) == str(cao_erwartung):
            return 'OK'
        return 'ABWEICHUNG'

    # Bei String-Erwartungen (Beschreibungen) → nur prüfen ob Wert vorhanden
    if xt_wert is not None and xt_wert != '' and xt_wert != 0:
        return 'OK'
    if cao_erwartung == 0 and xt_wert == 0:
        return 'OK'

    return 'NICHT_GEPRUEFT'


def matrix_zu_markdown(matrix: ComplianceMatrix) -> str:
    """Erzeugt eine Markdown-Darstellung der Compliance-Matrix."""
    lines = []
    lines.append(f'# Compliance-Matrix: XT-Kasse vs. CAO-Kasse Pro')
    lines.append(f'')
    lines.append(f'**Stand:** {matrix.zeitpunkt}')
    lines.append(f'**XT-Version:** {matrix.xt_version}')
    lines.append(f'**CAO-Version:** {matrix.cao_version}')
    lines.append(f'')
    lines.append(f'## Zusammenfassung')
    lines.append(f'')
    lines.append(f'| Metrik | Wert |')
    lines.append(f'|--------|------|')
    lines.append(f'| Felder geprüft | {matrix.anzahl_gesamt} |')
    lines.append(f'| Identisch (OK) | {matrix.anzahl_ok} |')
    lines.append(f'| Abweichungen | {matrix.anzahl_abweichung} |')
    lines.append(f'| Fehlt in XT | {matrix.anzahl_fehlt_xt} |')
    lines.append(f'')

    # Bekannte Abweichungen Zusammenfassung
    lines.append(f'## Bekannte Abweichungen')
    lines.append(f'')
    lines.append(f'| Bereich | XT-Kasse | CAO-Kasse | Risiko | Empfehlung |')
    lines.append(f'|---------|----------|-----------|--------|------------|')
    for key, abw in BEKANNTE_ABWEICHUNGEN.items():
        lines.append(
            f"| {key} | {abw['xt_wert']} | {abw['cao_wert']} | "
            f"{abw['risiko']} | {abw['empfehlung']} |"
        )
    lines.append(f'')

    # Detail pro Tabelle
    for tv in matrix.tabellen:
        lines.append(f'## {tv.tabelle}')
        lines.append(f'')
        lines.append(f'- **CAO-Operation:** {tv.cao_operation}')
        lines.append(f'- **XT-Operation:** {tv.xt_operation}')
        lines.append(f'- **Status:** {tv.status}')
        lines.append(f'')

        if tv.felder:
            lines.append(f'| Feld | XT-Wert | CAO-Erwartung | Status | Beschreibung |')
            lines.append(f'|------|---------|---------------|--------|--------------|')
            for fv in tv.felder:
                xt_str = _wert_kuerzen(fv.xt_wert)
                cao_str = _wert_kuerzen(fv.cao_erwartung)
                status_icon = {
                    'OK': 'OK',
                    'ABWEICHUNG': 'ABWEICHUNG',
                    'FEHLT_XT': 'FEHLT',
                    'FEHLT_CAO': 'FEHLT_CAO',
                    'NICHT_GEPRUEFT': '?',
                }.get(fv.status, fv.status)
                lines.append(
                    f'| {fv.feld} | {xt_str} | {cao_str} | '
                    f'{status_icon} | {fv.beschreibung} |'
                )
            lines.append(f'')

    return '\n'.join(lines)


def _wert_kuerzen(wert, max_len=40) -> str:
    """Kürzt einen Wert für die Markdown-Tabelle."""
    s = str(wert) if wert is not None else '(null)'
    s = s.replace('|', '\\|').replace('\n', ' ')
    if len(s) > max_len:
        s = s[:max_len - 3] + '...'
    return s
