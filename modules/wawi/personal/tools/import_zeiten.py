"""
Import von Arbeitszeit- und Abwesenheits-Daten aus einer ShiftJuggler-
Attendance-Export-CSV (Dateiname z.B. ``*-attendance-time.csv``).

Schreibt in mehrere Zieltabellen:

  * ``XT_PERSONAL_STEMPEL`` (QUELLE='import'):
      Art='Arbeit' → pro Zeile je 1 Kommen- und 1 Gehen-Stempel.
  * ``XT_PERSONAL_URLAUB_ANTRAG``:
      Art='Urlaub' → STATUS='genommen' (CSV ist rueckwirkender Attendance-
        Report), ganztaegig, Arbeitstage per AZ-Modell.
  * ``XT_PERSONAL_ABWESENHEIT``:
      Art='Krankmeldung' → TYP='krank', STATUS='genehmigt', ganztaegig.
  * ``XT_PERSONAL_STUNDEN_KORREKTUR`` (QUELLE='import'):
      Art='Korrektur Arbeitszeit' → DATUM + MINUTEN
        (= round(Arbeitszeit*60), vorzeichenbehaftet).

Nicht importiert (werden im Report als uebersprungen protokolliert):

  * Art='... (Feiertag)'
      → Feiertage laufen ueber die eigene Stammdaten-Tabelle
        (XT_FEIERTAG) und muessen dort nicht ein zweites Mal entstehen.

**Idempotenz** (erneutes Ausfuehren erzeugt keine Duplikate):

  * Arbeit-Stempel: zuvor werden ALLE Stempel mit QUELLE='import' fuer den
    jeweiligen MA im Import-Zeitraum geloescht und anschliessend neu
    angelegt. Kiosk-Selbststempel und Backoffice-Korrekturen (QUELLE!=
    'import') bleiben unberuehrt.
  * Urlaubsantraege: wir legen einen Satz nur an, wenn fuer (PERS_ID,
    VON, BIS) nicht bereits ein aktiver Antrag (STATUS !=
    'storniert'/'abgelehnt') existiert. Ueberlappungen werden gewarnt,
    aber nicht automatisch zusammengefuegt.
  * Abwesenheiten: wir legen einen Satz nur an, wenn fuer (PERS_ID, TYP,
    VON, BIS) nicht bereits ein aktiver (nicht stornierter) Eintrag
    existiert. Ueberlappungen mit abweichenden VON/BIS werden gewarnt,
    aber nicht automatisch zusammengefuegt.
  * Stunden-Korrekturen: alle QUELLE='import'-Zeilen des MA im
    Import-Zeitraum werden entfernt und neu angelegt. Manuelle
    Korrekturen (QUELLE='manuell') bleiben unberuehrt.

CSV-Format (Semikolon-separiert, UTF-8; Header in Zeile 1):

    Name;Personal-Nr.;Art;Standort;Arbeitsbereich;Schichtgruppe;Schichtname;
    Startdatum;Startzeit;"Startzeit (PLAN)";Enddatum;Endzeit;"Endzeit (PLAN)";
    "Pause (Minuten)";"Arbeitszeit (Stunden)";...

Aufruf::

    python3 -m modules.wawi.personal.tools.import_zeiten \\
        --csv /pfad/zur/attendance.csv --user 2

    # Dry-Run (zeigt nur, was gemacht wuerde):
    python3 -m modules.wawi.personal.tools.import_zeiten \\
        --csv /pfad/zur/attendance.csv --dry-run

"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterator


log = logging.getLogger(__name__)

# Re-use Pool-Init vom Stammdaten-Importer.
from .import_csv import _init_wawi_pool  # noqa: E402


# CSV-Art → internes Label. Urlaub hat eine eigene Zieltabelle
# (URLAUB_ANTRAG), daher wird er mit dem reservierten Wert 'urlaub'
# markiert; alle anderen Werte entsprechen einem ABWESENHEIT.TYP.
# Alles nicht Gelistete wird uebersprungen.
_FREISTELLUNGS_ART: dict[str, str] = {
    'Urlaub':        'urlaub',          # → XT_PERSONAL_URLAUB_ANTRAG
    'Krankmeldung':  'krank',           # → XT_PERSONAL_ABWESENHEIT
}


@dataclass
class _ImportStats:
    arbeit_stempel:     int = 0          # Paare (kommen+gehen)
    arbeit_zeilen_skip: int = 0          # Arbeit-Zeilen ohne Zeiten
    urlaub_angelegt:    int = 0
    urlaub_schon_da:    int = 0          # exakter Dublettenschutz
    urlaub_ueberlapp:   int = 0          # andere VON/BIS, nicht ueberschrieben
    abw_angelegt:       int = 0
    abw_schon_da:       int = 0          # exakter Dublettenschutz
    abw_ueberlapp:      int = 0          # andere VON/BIS, nicht ueberschrieben
    korrektur_angelegt: int = 0
    korrektur_skip:     int = 0          # unparsbarer Stunden-Wert
    feiertag_skip:      int = 0
    unbekannt_skip:     int = 0
    ma_fehlend:         set[str] = None  # Personalnummern ohne PERS_ID

    def __post_init__(self):
        if self.ma_fehlend is None:
            self.ma_fehlend = set()


# ── CSV-Parsing ────────────────────────────────────────────────────────────

def _parse_datum(s: str) -> date | None:
    """DD.MM.YYYY → date, leer → None."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%d.%m.%Y').date()
    except ValueError:
        return None


def _parse_zeit(s: str) -> time | None:
    """HH:MM → time, leer → None."""
    s = (s or '').strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, '%H:%M').time()
    except ValueError:
        return None


def _parse_stunden(s: str) -> float | None:
    """Parst den Spaltenwert "Arbeitszeit (Stunden)". Akzeptiert sowohl den
    unformatierten (Punkt-) als auch den formatierten (Komma-)Wert.
    Vorzeichen bleibt erhalten."""
    s = (s or '').strip().replace(',', '.')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _ist_feiertag_art(art: str) -> bool:
    return '(Feiertag)' in (art or '')


def _zeilen(csv_path: str) -> Iterator[dict]:
    with open(csv_path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            yield row


# ── Mapping: Personalnummer → PERS_ID ─────────────────────────────────────

def _personal_lookup() -> dict[str, int]:
    """Liefert {PERSONALNUMMER: PERS_ID} fuer alle existierenden MAs."""
    from common.db import get_db as _get_db
    with _get_db() as cur:
        cur.execute(
            "SELECT PERS_ID, PERSONALNUMMER FROM XT_PERSONAL_MA "
            "WHERE PERSONALNUMMER IS NOT NULL AND PERSONALNUMMER != ''"
        )
        return {str(r['PERSONALNUMMER']).strip(): int(r['PERS_ID'])
                for r in cur.fetchall() or []}


# ── DB-Operationen ────────────────────────────────────────────────────────

def _import_range_per_ma(rows: list[dict]) -> tuple[date, date]:
    """Ermittelt Min/Max-Datum aller Zeilen (fuer Stempel-Range-Cleanup)."""
    tage = [_parse_datum(r.get('Startdatum', '')) for r in rows]
    tage = [t for t in tage if t]
    if not tage:
        return date.today(), date.today()
    return min(tage), max(tage)


def _loesche_import_stempel(pers_id: int, von: date, bis: date) -> int:
    """Loescht alle QUELLE='import'-Stempel eines MA im Zeitraum [von, bis]."""
    from modules.wawi.personal.models import get_db_rw
    start = datetime.combine(von, datetime.min.time())
    ende = datetime.combine(bis, datetime.max.time())
    with get_db_rw() as cur:
        cur.execute(
            """DELETE FROM XT_PERSONAL_STEMPEL
                WHERE PERS_ID = %s AND QUELLE = 'import'
                  AND ZEITPUNKT >= %s AND ZEITPUNKT <= %s""",
            (pers_id, start, ende),
        )
        return cur.rowcount or 0


def _insert_stempel_paar(pers_id: int, kommen: datetime, gehen: datetime,
                         kommentar: str | None) -> None:
    from modules.wawi.personal.models import get_db_rw
    with get_db_rw() as cur:
        cur.executemany(
            """INSERT INTO XT_PERSONAL_STEMPEL
                 (PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE, KOMMENTAR)
               VALUES (%s, %s, %s, 'import', %s)""",
            [
                (pers_id, 'kommen', kommen, kommentar),
                (pers_id, 'gehen',  gehen,  kommentar),
            ],
        )


def _abwesenheit_exakt_vorhanden(pers_id: int, typ: str,
                                 von: date, bis: date) -> bool:
    from modules.wawi.personal.models import get_db_ro
    with get_db_ro() as cur:
        cur.execute(
            """SELECT 1 FROM XT_PERSONAL_ABWESENHEIT
                WHERE PERS_ID = %s AND TYP = %s
                  AND VON = %s AND BIS = %s
                  AND STORNIERT = 0
                LIMIT 1""",
            (pers_id, typ, von, bis),
        )
        return cur.fetchone() is not None


def _abwesenheit_ueberlappt(pers_id: int, typ: str,
                            von: date, bis: date) -> list[dict]:
    """Sucht aktive Abwesenheiten des gleichen TYPs, die sich mit
    [von, bis] ueberschneiden (aber NICHT exakt treffen)."""
    from modules.wawi.personal.models import get_db_ro
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, VON, BIS FROM XT_PERSONAL_ABWESENHEIT
                WHERE PERS_ID = %s AND TYP = %s AND STORNIERT = 0
                  AND VON <= %s AND BIS >= %s
                  AND NOT (VON = %s AND BIS = %s)""",
            (pers_id, typ, bis, von, von, bis),
        )
        return cur.fetchall() or []


def _urlaub_antrag_exakt_vorhanden(pers_id: int,
                                   von: date, bis: date) -> bool:
    from modules.wawi.personal.models import get_db_ro
    with get_db_ro() as cur:
        cur.execute(
            """SELECT 1 FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s AND VON = %s AND BIS = %s
                  AND STATUS NOT IN ('storniert','abgelehnt')
                LIMIT 1""",
            (pers_id, von, bis),
        )
        return cur.fetchone() is not None


def _urlaub_antrag_ueberlappt(pers_id: int,
                              von: date, bis: date) -> list[dict]:
    """Aktive (nicht stornierte/abgelehnte) Urlaubsantraege, die sich
    mit [von, bis] ueberschneiden (aber NICHT exakt treffen)."""
    from modules.wawi.personal.models import get_db_ro
    with get_db_ro() as cur:
        cur.execute(
            """SELECT REC_ID, VON, BIS FROM XT_PERSONAL_URLAUB_ANTRAG
                WHERE PERS_ID = %s
                  AND STATUS NOT IN ('storniert','abgelehnt')
                  AND VON <= %s AND BIS >= %s
                  AND NOT (VON = %s AND BIS = %s)""",
            (pers_id, bis, von, von, bis),
        )
        return cur.fetchall() or []


# ── Haupt-Logik ───────────────────────────────────────────────────────────

def _gruppiere_freistellungen(
    zeilen_je_ma: list[dict]
) -> list[tuple[str, date, date]]:
    """Gruppiert Freistellungs-Zeilen (Urlaub + Abwesenheits-Typen) zu
    (art_key, von, bis)-Tupeln.

    ``art_key`` ist der reservierte Wert ``'urlaub'`` (→ URLAUB_ANTRAG)
    oder ein Eintrag aus ``ABWESENHEIT_TYPEN`` (z.B. ``'krank'`` →
    ABWESENHEIT).

    Strategie: gleiche (art_key, Enddatum) gehoeren zusammen; VON =
    min(Startdatum), BIS = Enddatum. Passt zur ShiftJuggler-Export-Mimik,
    bei der fuer jeden Tag einer mehrtaegigen Phase eine eigene Zeile mit
    identischem Enddatum erzeugt wird.
    """
    # key=(art_key, ende_datum), value=list of start_datums
    gruppen: dict[tuple[str, date], list[date]] = defaultdict(list)
    for r in zeilen_je_ma:
        art = (r.get('Art') or '').strip()
        art_key = _FREISTELLUNGS_ART.get(art)
        if not art_key:
            continue
        d_start = _parse_datum(r.get('Startdatum', ''))
        d_ende = _parse_datum(r.get('Enddatum', '') or r.get('Startdatum', ''))
        if not d_start or not d_ende:
            continue
        gruppen[(art_key, d_ende)].append(d_start)

    result: list[tuple[str, date, date]] = []
    for (art_key, d_ende), starts in gruppen.items():
        result.append((art_key, min(starts), d_ende))
    # deterministisch sortieren
    result.sort(key=lambda t: (t[1], t[2], t[0]))
    return result


def importiere_csv(csv_path: str, benutzer_ma_id: int,
                   dry_run: bool = False) -> _ImportStats:
    """Liest die Attendance-CSV und schreibt Stempel + Abwesenheiten.

    Liefert ein Statistik-Objekt fuer den abschliessenden Report.
    """
    from modules.wawi.personal import models as m

    stats = _ImportStats()
    personal = _personal_lookup()

    # Zeilen nach Personalnummer gruppieren, dann pro MA verarbeiten.
    rows_by_persnr: dict[str, list[dict]] = defaultdict(list)
    for row in _zeilen(csv_path):
        persnr = (row.get('Personal-Nr.') or '').strip()
        if persnr:
            rows_by_persnr[persnr].append(row)

    for persnr, rows in sorted(rows_by_persnr.items()):
        pers_id = personal.get(persnr)
        if not pers_id:
            stats.ma_fehlend.add(persnr)
            log.warning('Personal-Nr %s nicht in XT_PERSONAL_MA gefunden – '
                        '%d Zeilen uebersprungen', persnr, len(rows))
            continue

        # 1) Arbeitsstempel: ganzen Range einmal wegfegen, dann neu anlegen.
        arbeit_rows = [r for r in rows if (r.get('Art') or '').strip() == 'Arbeit']
        range_von, range_bis = _import_range_per_ma(arbeit_rows) if arbeit_rows \
                               else (None, None)

        if arbeit_rows and range_von and range_bis:
            if dry_run:
                log.info('[dry-run] pers_id=%d: wuerde %s..%s QUELLE=import '
                         'loeschen, dann %d Arbeits-Tage neu stempeln',
                         pers_id, range_von, range_bis, len(arbeit_rows))
            else:
                geloescht = _loesche_import_stempel(pers_id, range_von, range_bis)
                if geloescht:
                    log.info('pers_id=%d: %d alte Import-Stempel entfernt '
                             '(%s..%s)', pers_id, geloescht, range_von, range_bis)

        for r in arbeit_rows:
            d_start = _parse_datum(r.get('Startdatum', ''))
            t_start = _parse_zeit(r.get('Startzeit', ''))
            d_ende = _parse_datum(r.get('Enddatum', '')) or d_start
            t_ende = _parse_zeit(r.get('Endzeit', ''))
            if not (d_start and t_start and d_ende and t_ende):
                stats.arbeit_zeilen_skip += 1
                log.debug('Arbeit-Zeile ohne Zeiten uebersprungen: persnr=%s '
                          'datum=%s', persnr, d_start)
                continue
            kommen = datetime.combine(d_start, t_start)
            gehen = datetime.combine(d_ende, t_ende)
            if gehen <= kommen:
                # Sollte nicht vorkommen (Export-Mimik: Endzeit immer nach
                # Startzeit am gleichen oder Folgetag). Defensive: +1 Tag.
                gehen = datetime.combine(d_ende, t_ende) \
                        if d_ende > d_start else gehen
                if gehen <= kommen:
                    stats.arbeit_zeilen_skip += 1
                    log.warning('Arbeit-Zeile unplausibel (gehen<=kommen): '
                                'persnr=%s %s-%s', persnr, kommen, gehen)
                    continue
            if dry_run:
                stats.arbeit_stempel += 1
                continue
            _insert_stempel_paar(pers_id, kommen, gehen,
                                 kommentar='Import CSV')
            stats.arbeit_stempel += 1

        # 2) Freistellungen gruppieren; Urlaub → URLAUB_ANTRAG,
        #    Krank/etc. → ABWESENHEIT. Jeweils idempotent.
        for art_key, von, bis in _gruppiere_freistellungen(rows):
            if art_key == 'urlaub':
                if _urlaub_antrag_exakt_vorhanden(pers_id, von, bis):
                    stats.urlaub_schon_da += 1
                    continue
                overlaps = _urlaub_antrag_ueberlappt(pers_id, von, bis)
                if overlaps:
                    stats.urlaub_ueberlapp += 1
                    log.warning('Ueberlappender Urlaubsantrag (nicht angelegt): '
                                'persnr=%s %s..%s – vorhanden: %s',
                                persnr, von, bis,
                                [(o['VON'], o['BIS']) for o in overlaps])
                    continue
                if dry_run:
                    log.info('[dry-run] pers_id=%d: wuerde Urlaub %s..%s '
                             'anlegen (STATUS=genommen)', pers_id, von, bis)
                    stats.urlaub_angelegt += 1
                    continue
                m.urlaub_antrag_anlegen(
                    pers_id=pers_id, von=von, bis=bis,
                    kommentar='Import CSV',
                    benutzer_ma_id=benutzer_ma_id,
                    status='genommen',
                )
                stats.urlaub_angelegt += 1
            else:
                typ = art_key
                if _abwesenheit_exakt_vorhanden(pers_id, typ, von, bis):
                    stats.abw_schon_da += 1
                    continue
                overlaps = _abwesenheit_ueberlappt(pers_id, typ, von, bis)
                if overlaps:
                    stats.abw_ueberlapp += 1
                    log.warning('Ueberlappende Abwesenheit (nicht angelegt): '
                                'persnr=%s TYP=%s %s..%s – vorhanden: %s',
                                persnr, typ, von, bis,
                                [(o['VON'], o['BIS']) for o in overlaps])
                    continue
                if dry_run:
                    log.info('[dry-run] pers_id=%d: wuerde Abwesenheit %s '
                             '%s..%s anlegen', pers_id, typ, von, bis)
                    stats.abw_angelegt += 1
                    continue
                m.abwesenheit_anlegen(
                    pers_id=pers_id, typ=typ, von=von, bis=bis,
                    ganztags=True, status='genehmigt',
                    bemerkung='Import CSV',
                    benutzer_ma_id=benutzer_ma_id,
                )
                stats.abw_angelegt += 1

        # 3) Stunden-Korrekturen: pro MA im Range idempotent neu befuellen.
        korrektur_rows = [r for r in rows
                          if (r.get('Art') or '').strip() == 'Korrektur Arbeitszeit']
        if korrektur_rows:
            tage = [_parse_datum(r.get('Startdatum', '')) for r in korrektur_rows]
            tage = [t for t in tage if t]
            if tage:
                k_von, k_bis = min(tage), max(tage)
                if dry_run:
                    log.info('[dry-run] pers_id=%d: wuerde %s..%s QUELLE=import '
                             'Korrekturen loeschen, dann %d Zeilen neu anlegen',
                             pers_id, k_von, k_bis, len(korrektur_rows))
                else:
                    geloescht = m.stundenkorrektur_import_loeschen(
                        pers_id, k_von, k_bis)
                    if geloescht:
                        log.info('pers_id=%d: %d alte Import-Korrekturen '
                                 'entfernt (%s..%s)',
                                 pers_id, geloescht, k_von, k_bis)

        for r in korrektur_rows:
            datum = _parse_datum(r.get('Startdatum', ''))
            stunden = _parse_stunden(r.get('Arbeitszeit (Stunden)', ''))
            if not datum or stunden is None:
                stats.korrektur_skip += 1
                log.warning('Korrektur-Zeile unparsbar: persnr=%s Startdatum=%r '
                            'Stunden=%r', persnr,
                            r.get('Startdatum'), r.get('Arbeitszeit (Stunden)'))
                continue
            minuten = int(round(stunden * 60))
            grund_suffix = (r.get('zuletzt bearbeitet von') or '').strip()
            grund = 'CSV-Import Korrektur Arbeitszeit' + (
                f' ({grund_suffix})' if grund_suffix else '')
            if dry_run:
                stats.korrektur_angelegt += 1
                continue
            m.stundenkorrektur_insert(
                pers_id=pers_id, datum=datum, minuten=minuten,
                grund=grund, quelle='import',
                benutzer_ma_id=benutzer_ma_id,
            )
            stats.korrektur_angelegt += 1

        # 4) Restkategorien zaehlen (Feiertage, unbekannte Arten).
        for r in rows:
            art = (r.get('Art') or '').strip()
            if art == 'Arbeit' or art in _FREISTELLUNGS_ART \
                    or art == 'Korrektur Arbeitszeit':
                continue
            if _ist_feiertag_art(art):
                stats.feiertag_skip += 1
            elif art:
                stats.unbekannt_skip += 1
                log.info('Unbekannte Art (uebersprungen): persnr=%s "%s"',
                         persnr, art)

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────

def _report(stats: _ImportStats, dry_run: bool) -> None:
    prefix = '[dry-run] ' if dry_run else ''
    log.info('%s──── Import-Zusammenfassung ────', prefix)
    log.info('%sArbeits-Tage (kommen+gehen):  %d', prefix, stats.arbeit_stempel)
    log.info('%sArbeits-Zeilen uebersprungen: %d', prefix, stats.arbeit_zeilen_skip)
    log.info('%sUrlaubsantraege angelegt:     %d', prefix, stats.urlaub_angelegt)
    log.info('%sUrlaubsantraege schon da:     %d', prefix, stats.urlaub_schon_da)
    log.info('%sUrlaubsantraege ueberlappend: %d', prefix, stats.urlaub_ueberlapp)
    log.info('%sAbwesenheiten angelegt:       %d', prefix, stats.abw_angelegt)
    log.info('%sAbwesenheiten schon da:       %d', prefix, stats.abw_schon_da)
    log.info('%sAbwesenheiten ueberlappend:   %d', prefix, stats.abw_ueberlapp)
    log.info('%sKorrekturen angelegt:         %d', prefix, stats.korrektur_angelegt)
    if stats.korrektur_skip:
        log.info('%sKorrekturen unparsbar:      %d', prefix, stats.korrektur_skip)
    log.info('%sFeiertage (skip):             %d', prefix, stats.feiertag_skip)
    if stats.unbekannt_skip:
        log.info('%sUnbekannte Art (skip):      %d', prefix, stats.unbekannt_skip)
    if stats.ma_fehlend:
        log.warning('%sPersonalnummern ohne MA-Satz: %s',
                    prefix, ', '.join(sorted(stats.ma_fehlend)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', required=True,
                   help='Pfad zur ShiftJuggler-Attendance-CSV')
    p.add_argument('--user', type=int, default=2,
                   help='CAO-MA_ID des ausfuehrenden Backoffice-Users (default: 2)')
    p.add_argument('--dry-run', action='store_true',
                   help='Keine DB-Schreibzugriffe, nur Report')
    p.add_argument('--verbose', '-v', action='store_true')
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s  %(message)s',
    )

    if not os.path.isfile(args.csv):
        log.error('Datei nicht gefunden: %s', args.csv)
        return 2

    _init_wawi_pool()
    stats = importiere_csv(args.csv, args.user, dry_run=args.dry_run)
    _report(stats, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
