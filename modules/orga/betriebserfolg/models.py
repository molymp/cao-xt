"""Datenmodell + Berechnungen fuer monatliche Betriebserfolgsmessung."""
from __future__ import annotations

import calendar
import datetime as _dt
import logging
from typing import Optional

from common.db import get_db
from modules.orga.bestellvorschlag.kategorie import (
    OEFFNUNGS_STUNDEN, gesamtumsatz_tagesdaten,
)

log = logging.getLogger(__name__)


def _konfig_holen() -> dict[str, float]:
    """Liest die Default-Konfig-Werte aus XT_EINSTELLUNGEN."""
    schluessel = [
        'betrieb.rohertrag_pct', 'betrieb.personalkosten_pct',
        'betrieb.sonst_kosten_pct', 'betrieb.ideal_mai',
        'betrieb.max_mai', 'betrieb.stundensatz_netto',
    ]
    with get_db() as cur:
        cur.execute(
            "SELECT schluessel, wert FROM XT_EINSTELLUNGEN "
            "WHERE schluessel IN ({})".format(
                ','.join(['%s'] * len(schluessel))),
            schluessel)
        rows = cur.fetchall() or []
    konfig = {}
    for r in rows:
        try:
            konfig[r['schluessel']] = float(r['wert'])
        except (TypeError, ValueError):
            pass
    # Fallback-Defaults, falls fehlend
    konfig.setdefault('betrieb.rohertrag_pct',      30.0)
    konfig.setdefault('betrieb.personalkosten_pct', 24.74)
    konfig.setdefault('betrieb.sonst_kosten_pct',   10.12)
    konfig.setdefault('betrieb.ideal_mai',          110.0)
    konfig.setdefault('betrieb.max_mai',            234.54)
    konfig.setdefault('betrieb.stundensatz_netto',  20.26)
    return konfig


def konfig_speichern(daten: dict) -> None:
    """Schreibt erlaubte Konfig-Werte zurueck in XT_EINSTELLUNGEN."""
    erlaubt = {
        'betrieb.rohertrag_pct', 'betrieb.personalkosten_pct',
        'betrieb.sonst_kosten_pct', 'betrieb.ideal_mai',
        'betrieb.max_mai', 'betrieb.stundensatz_netto',
    }
    with get_db() as cur:
        for k, v in daten.items():
            if k not in erlaubt:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            cur.execute("""
                INSERT INTO XT_EINSTELLUNGEN (schluessel, wert)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE wert = VALUES(wert)
            """, (k, f'{f:.4f}'.rstrip('0').rstrip('.')))


def monatswerte_holen(jahr: int, monat: int) -> dict:
    with get_db() as cur:
        cur.execute("""
            SELECT * FROM XT_BETRIEBSERFOLG_MONAT
            WHERE jahr=%s AND monat=%s
        """, (jahr, monat))
        r = cur.fetchone() or {}
    return {
        'verderb_eur':    float(r.get('verderb_eur')    or 0),
        'ma_einsatz_std': float(r.get('ma_einsatz_std') or 0),
        'krankstunden':   float(r.get('krankstunden')   or 0),
        'fixkosten_eur':  float(r.get('fixkosten_eur')  or 0),
        'anmerkung':      r.get('anmerkung') or '',
    }


def monatswerte_speichern(jahr: int, monat: int, daten: dict,
                           ma_id: Optional[int] = None) -> None:
    with get_db() as cur:
        cur.execute("""
            INSERT INTO XT_BETRIEBSERFOLG_MONAT
              (jahr, monat, verderb_eur, ma_einsatz_std,
               krankstunden, fixkosten_eur, anmerkung, erfasst_von)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              verderb_eur    = VALUES(verderb_eur),
              ma_einsatz_std = VALUES(ma_einsatz_std),
              krankstunden   = VALUES(krankstunden),
              fixkosten_eur  = VALUES(fixkosten_eur),
              anmerkung      = VALUES(anmerkung)
        """, (
            int(jahr), int(monat),
            float(daten.get('verderb_eur')    or 0),
            float(daten.get('ma_einsatz_std') or 0),
            float(daten.get('krankstunden')   or 0),
            float(daten.get('fixkosten_eur')  or 0),
            (daten.get('anmerkung') or None),
            ma_id,
        ))


def _oeffnungs_stunden_monat(jahr: int, monat: int) -> tuple[float, int]:
    """Liefert (Gesamt-Oeffnungsstunden, Anzahl Tage offen) fuer einen
    Kalendermonat. Sonderoeffnungstage werden hier nicht modelliert —
    fuer eine genauere Zahl muesste man auf die Ist-Tagesdaten gehen."""
    _, last = calendar.monthrange(jahr, monat)
    h = 0.0
    n_offen = 0
    for tag in range(1, last + 1):
        d = _dt.date(jahr, monat, tag)
        std = OEFFNUNGS_STUNDEN.get(d.weekday(), 0)
        if std > 0:
            h += std
            n_offen += 1
    return h, n_offen


def betriebserfolg(jahr: int, monat: int) -> dict:
    """Komplette Berechnung fuer einen Monat.

    Liefert eine flache Map mit allen Kennzahlen analog zur Excel-Vorlage.
    """
    konfig = _konfig_holen()
    eingaben = monatswerte_holen(jahr, monat)

    _, last_day = calendar.monthrange(jahr, monat)
    von = _dt.date(jahr, monat, 1)
    bis = _dt.date(jahr, monat, last_day)
    rows = gesamtumsatz_tagesdaten(von, bis)
    aktiv = [r for r in rows if r['n_bons'] > 0]

    umsatz = sum(r['umsatz_brutto'] for r in aktiv)
    bons   = sum(r['n_bons']        for r in aktiv)

    h_offen, n_offen = _oeffnungs_stunden_monat(jahr, monat)
    umsatz_je_std = (umsatz / h_offen)  if h_offen   else 0.0
    umsatz_je_kd  = (umsatz / bons)     if bons      else 0.0

    verderb_eur   = eingaben['verderb_eur']
    verderb_pct   = (verderb_eur / umsatz * 100.0) if umsatz else 0.0

    ma_std        = eingaben['ma_einsatz_std']
    krank_std     = eingaben['krankstunden']
    fixkosten_eur = eingaben['fixkosten_eur']

    mai = (umsatz / ma_std) if ma_std else None
    std_je_besetz = (ma_std / h_offen) if h_offen else None
    krank_quote   = (krank_std / ma_std * 100.0) if ma_std else None

    # Blitz-Ertragsrechnung (aktuell)
    rohertrag_pct      = konfig['betrieb.rohertrag_pct']
    personalkosten_pct = konfig['betrieb.personalkosten_pct']
    sonst_kosten_pct   = konfig['betrieb.sonst_kosten_pct']

    rohertrag       = umsatz * rohertrag_pct      / 100.0
    personalkosten  = umsatz * personalkosten_pct / 100.0
    sonstige_kosten = umsatz * sonst_kosten_pct   / 100.0
    ertrag          = rohertrag - personalkosten - sonstige_kosten - fixkosten_eur
    ertrag_pct      = (ertrag / umsatz * 100.0) if umsatz else 0.0
    fix_kosten_pct  = (fixkosten_eur / umsatz * 100.0) if umsatz else 0.0

    # Wochentag-Aufschluesselung
    wt_namen = ['Mo','Di','Mi','Do','Fr','Sa','So']
    wt_data = {}
    for wd in range(7):
        sub = [r for r in aktiv if r['wochentag'] == wd]
        if not sub:
            continue
        ums = [r['umsatz_brutto'] for r in sub]
        wt_data[wd] = {
            'name':          wt_namen[wd],
            'n':             len(sub),
            'umsatz_avg':    sum(ums) / len(ums),
            'umsatz_max':    max(ums),
            'umsatz_min':    min(ums),
            'umsatz_anteil_pct':
                (sum(ums) / umsatz * 100.0) if umsatz else 0,
            'mai_avg':       ((sum(ums) / len(ums)) / OEFFNUNGS_STUNDEN.get(wd, 0))
                              if OEFFNUNGS_STUNDEN.get(wd, 0) else None,
            'mai_max':       (max(ums) / OEFFNUNGS_STUNDEN.get(wd, 0))
                              if OEFFNUNGS_STUNDEN.get(wd, 0) else None,
            'mai_min':       (min(ums) / OEFFNUNGS_STUNDEN.get(wd, 0))
                              if OEFFNUNGS_STUNDEN.get(wd, 0) else None,
        }

    # Tageswerte (Mittelwert pro geoeffnetem Tag)
    n_aktiv = len(aktiv)
    avg_kunden_pro_tag = (bons / n_aktiv) if n_aktiv else 0
    avg_oeffnungs_std_pro_tag = (h_offen / n_offen) if n_offen else 0
    avg_umsatz_je_std = (umsatz_je_std)
    avg_umsatz_je_kd  = (umsatz_je_kd)
    avg_mai           = mai

    # Hochrechnung (YTD-basiert)
    jahr_start = _dt.date(jahr, 1, 1)
    ytd_bis = min(bis, _dt.date.today())
    ytd_rows = gesamtumsatz_tagesdaten(jahr_start, ytd_bis)
    ytd_aktiv = [r for r in ytd_rows if r['n_bons'] > 0]
    ytd_umsatz = sum(r['umsatz_brutto'] for r in ytd_aktiv)
    ytd_offene_tage = len(ytd_aktiv) or 1
    tag_avg_ytd = ytd_umsatz / ytd_offene_tage
    # Jahres-Hochrechnung: angenommen ~290 offene Tage/Jahr
    jahres_offene_tage_estimate = sum(
        1 for d_off in range(366)
        if (jahr_start + _dt.timedelta(days=d_off)).year == jahr
        and OEFFNUNGS_STUNDEN.get(
            (jahr_start + _dt.timedelta(days=d_off)).weekday(), 0) > 0)
    hochrechnung_umsatz = tag_avg_ytd * jahres_offene_tage_estimate
    hochrechnung_je_std = (
        hochrechnung_umsatz
        / (jahres_offene_tage_estimate
           * (h_offen / n_offen if n_offen else 11.5))
    ) if hochrechnung_umsatz else 0

    # Blitz-Hochrechnung
    rohertrag_hr      = hochrechnung_umsatz * rohertrag_pct      / 100.0
    personalkosten_hr = hochrechnung_umsatz * personalkosten_pct / 100.0
    sonst_hr          = hochrechnung_umsatz * sonst_kosten_pct   / 100.0
    fixkosten_hr      = fixkosten_eur * 12  # naive Jahres-Hochrechnung
    ertrag_hr         = rohertrag_hr - personalkosten_hr - sonst_hr - fixkosten_hr
    ertrag_hr_pct     = (ertrag_hr / hochrechnung_umsatz * 100.0
                          if hochrechnung_umsatz else 0)

    # Optimierungs-Potenziale
    verderb_optimierung = verderb_eur * 0.8 if verderb_eur else 0
    gehalt_optimierung  = personalkosten * 0.10  # 10% Spielraum (vorsichtig)
    handelsspanne_lift  = umsatz * 0.005  # 0.5pp Margenverbesserung
    potenzial_total     = verderb_optimierung + gehalt_optimierung + handelsspanne_lift

    # MAI-Block
    ideal_mai    = konfig['betrieb.ideal_mai']
    max_mai      = konfig['betrieb.max_mai']
    std_satz     = konfig['betrieb.stundensatz_netto']

    # Reserve-Nettostunden (Diff aus Oeffnungsstunden - MA-Einsatz)
    reserve_std_monat = (h_offen - ma_std) if ma_std else None

    return {
        'jahr': jahr, 'monat': monat,
        'periode': {
            'von': von.isoformat(), 'bis': bis.isoformat(),
            'n_offene_tage': n_offen,
            'n_aktive_tage': n_aktiv,
        },
        # Tageswerte
        'tageswerte': {
            'oeffnungs_std':  avg_oeffnungs_std_pro_tag,
            'kunden_pro_tag': avg_kunden_pro_tag,
            'umsatz_je_std':  umsatz_je_std,
            'mai_ist':        avg_mai,
            'std_je_besetz':  std_je_besetz,
            'umsatz_je_kd':   umsatz_je_kd,
        },
        # Monatswerte
        'monatswerte': {
            'umsatz':         umsatz,
            'verderb_eur':    verderb_eur,
            'verderb_pct':    verderb_pct,
            'ma_einsatz_std': ma_std,
            'krankstunden':   krank_std,
            'krank_quote_pct': krank_quote,
            'oeffnungs_std':  h_offen,
            'kunden':         bons,
            'umsatz_je_std':  umsatz_je_std,
            'mai':            mai,
            'std_je_besetz':  std_je_besetz,
            'umsatz_je_kd':   umsatz_je_kd,
            'rohertrag':      rohertrag,
            'fixkosten_eur':  fixkosten_eur,
            'fix_kosten_pct': fix_kosten_pct,
            'personalkosten': personalkosten,
            'personalkosten_pct': personalkosten_pct,
            'sonstige_kosten': sonstige_kosten,
            'sonst_kosten_pct': sonst_kosten_pct,
            'ertrag':         ertrag,
            'ertrag_pct':     ertrag_pct,
        },
        # Wochentag-Tabelle
        'wochentag':       wt_data,
        # Hochrechnung
        'hochrechnung': {
            'umsatz':         hochrechnung_umsatz,
            'je_std':         hochrechnung_je_std,
            'rohertrag':      rohertrag_hr,
            'personalkosten': personalkosten_hr,
            'sonstige_kosten': sonst_hr,
            'fixkosten':      fixkosten_hr,
            'ertrag':         ertrag_hr,
            'ertrag_pct':     ertrag_hr_pct,
            'ytd_umsatz':     ytd_umsatz,
            'ytd_offene_tage': ytd_offene_tage,
            'jahres_offene_tage': jahres_offene_tage_estimate,
        },
        # Potenzial
        'potenzial': {
            'verderb_eur':   verderb_optimierung,
            'verderb_pct':   verderb_pct,
            'gehalt_eur':    gehalt_optimierung,
            'handelsspanne_eur': handelsspanne_lift,
            'gesamt_eur':    potenzial_total,
        },
        # MAI-Block
        'mai_block': {
            'ideal_mai':      ideal_mai,
            'stundensatz_netto': std_satz,
            'max_mai_betrieb': max_mai,
            'reserve_std_monat': reserve_std_monat,
        },
        # Konfig + Eingaben fuer Editor
        'konfig':   konfig,
        'eingaben': eingaben,
    }
