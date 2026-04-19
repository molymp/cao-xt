"""HACCP Alarm-Engine.

Eine **reine** Evaluationsfunktion ``auswerten()`` liefert eine Liste von
``Aktion``-Objekten (OEFFNEN / SCHLIESSEN / ESKALIEREN). Die Seiteneffekte
(DB-Schreiben, Mail versenden) macht der Poller — das haelt die Engine
testbar.

Regeln (pro Geraet, pro Poll-Durchlauf):

1. **Offline**: Ist der letzte Messwert aelter als ``STALE_MIN`` Minuten?
   -> offline-Alarm oeffnen / aktiven schliessen wenn wieder frisch.
2. **Temp absolut**: Letzter Messwert ausserhalb [TEMP_MIN, TEMP_MAX]?
   Wenn die Abweichung ununterbrochen seit >= KARENZ_MIN Minuten besteht
   -> temp_hoch / temp_tief oeffnen. Wieder im Band fuer >= 10 Min ->
   schliessen.
3. **Drift** (optional): Aktueller Wert vs. rolling Median des letzten
   DRIFT_FENSTER_H Fensters. Abweichung > DRIFT_K und anhaltend
   >= KARENZ_MIN -> drift-Alarm. (Nicht scharfschalten wenn absolut-Alarm
   bereits aktiv — absolut hat Vorrang.)
4. **Battery-Low**: Flag vom Sensor uebernehmen (kein Karenz-Timer).
5. **Eskalation**: Bei jedem Poll fuer jeden offenen Alarm pruefen, ob
   die naechste Stufe faellig ist (Zeit seit START_AT >= DELAY_MIN
   der konfigurierten Empfaenger).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from . import models as m


# Abschluss-Karenz: wenn der Wert X Minuten durchgaengig wieder im Band ist,
# wird der Alarm geschlossen. Damit flackern keine Mikro-Erholungen.
ABSCHLUSS_KARENZ_MIN = 10


class AktionTyp(str, Enum):
    OEFFNEN     = 'oeffnen'
    SCHLIESSEN  = 'schliessen'
    ESKALIEREN  = 'eskalieren'


@dataclass(frozen=True)
class Aktion:
    typ:       AktionTyp
    geraet_id: int
    alarm_typ: str | None = None       # temp_hoch|temp_tief|drift|offline|battery
    alarm_id:  int | None = None       # bei SCHLIESSEN/ESKALIEREN
    stufe:     int | None = None       # bei ESKALIEREN
    wert:      float | None = None     # aktueller Messwert
    start_at:  datetime | None = None  # bei OEFFNEN
    ende_at:   datetime | None = None  # bei SCHLIESSEN


def auswerten(geraet: dict, grenz: dict, jetzt_utc: datetime,
              alarmkette: list[dict] | None = None) -> list[Aktion]:
    """Haupt-Entry. Liest Messwerte + offene Alarme selbst aus der DB."""
    gid = int(geraet['GERAET_ID'])
    aktionen: list[Aktion] = []

    letzter = _letzter_messwert(gid)
    offline_alarm = m.alarm_offen(gid, 'offline')
    hoch_alarm    = m.alarm_offen(gid, 'temp_hoch')
    tief_alarm    = m.alarm_offen(gid, 'temp_tief')
    drift_alarm   = m.alarm_offen(gid, 'drift')
    battery_alarm = m.alarm_offen(gid, 'battery')

    # ── Staleness / offline ───────────────────────────────────────────
    stale_min = int(grenz['STALE_MIN']) if grenz else 30
    if letzter is None:
        stale = True
    else:
        stale = (jetzt_utc - letzter['ZEITPUNKT_UTC']
                 ).total_seconds() >= stale_min * 60

    if stale and not offline_alarm:
        start = letzter['ZEITPUNKT_UTC'] + timedelta(minutes=stale_min) \
                if letzter else jetzt_utc
        aktionen.append(Aktion(AktionTyp.OEFFNEN, gid,
                               alarm_typ='offline', start_at=start))
    elif not stale and offline_alarm:
        aktionen.append(Aktion(AktionTyp.SCHLIESSEN, gid,
                               alarm_typ='offline',
                               alarm_id=int(offline_alarm['ALARM_ID']),
                               ende_at=jetzt_utc))

    # ── Temperatur-Pruefung (nur wenn nicht offline und wenn Grenz da) ─
    if not stale and grenz and letzter and letzter['TEMP_C'] is not None \
            and not letzter['NO_CONNECTION']:
        temp = float(letzter['TEMP_C'])
        t_min = float(grenz['TEMP_MIN_C'])
        t_max = float(grenz['TEMP_MAX_C'])
        karenz = int(grenz['KARENZ_MIN'])

        # --- absolut: zu hoch
        aktionen += _abweichungs_handler(
            gid=gid, typ='temp_hoch',
            verstoss=(temp > t_max),
            aktueller_alarm=hoch_alarm,
            wert=temp,
            verstoss_bedingung=lambda mw: mw['TEMP_C'] is not None
                                          and not mw['NO_CONNECTION']
                                          and float(mw['TEMP_C']) > t_max,
            karenz_min=karenz,
            jetzt_utc=jetzt_utc,
        )
        # --- absolut: zu tief
        aktionen += _abweichungs_handler(
            gid=gid, typ='temp_tief',
            verstoss=(temp < t_min),
            aktueller_alarm=tief_alarm,
            wert=temp,
            verstoss_bedingung=lambda mw: mw['TEMP_C'] is not None
                                          and not mw['NO_CONNECTION']
                                          and float(mw['TEMP_C']) < t_min,
            karenz_min=karenz,
            jetzt_utc=jetzt_utc,
        )

        # --- Drift: nur wenn kein absoluter Alarm aktiv/entsteht (sonst Doppelt)
        hat_absolut = hoch_alarm or tief_alarm or \
                      any(a.typ == AktionTyp.OEFFNEN and
                          a.alarm_typ in ('temp_hoch','temp_tief') for a in aktionen)
        if grenz.get('DRIFT_AKTIV') and grenz.get('DRIFT_K') and not hat_absolut:
            fenster_h = int(grenz['DRIFT_FENSTER_H'] or 24)
            median = m.rolling_median_temp(gid, jetzt_utc, fenster_h)
            if median is not None:
                drift_k = float(grenz['DRIFT_K'])
                delta = abs(temp - median)
                aktionen += _abweichungs_handler(
                    gid=gid, typ='drift',
                    verstoss=(delta > drift_k),
                    aktueller_alarm=drift_alarm,
                    wert=temp,
                    verstoss_bedingung=_drift_condition_factory(
                        gid, drift_k, fenster_h),
                    karenz_min=karenz,
                    jetzt_utc=jetzt_utc,
                )

    # ── Battery (kein Karenz-Timer; Low-Flag direkt) ──────────────────
    if letzter and letzter.get('BATTERY_LOW') and not battery_alarm:
        aktionen.append(Aktion(AktionTyp.OEFFNEN, gid,
                               alarm_typ='battery',
                               start_at=letzter['ZEITPUNKT_UTC']))
    elif letzter and not letzter.get('BATTERY_LOW') and battery_alarm:
        aktionen.append(Aktion(AktionTyp.SCHLIESSEN, gid,
                               alarm_typ='battery',
                               alarm_id=int(battery_alarm['ALARM_ID']),
                               ende_at=jetzt_utc))

    # ── Eskalation: fuer jeden offenen Alarm pruefen ──────────────────
    if alarmkette is None:
        alarmkette = m.alarmkette_aktiv()
    for alarm in _alle_offenen_fuer(gid,
                                    hoch_alarm, tief_alarm, drift_alarm,
                                    offline_alarm, battery_alarm):
        faellig = _naechste_faellige_stufe(alarm, alarmkette, jetzt_utc)
        if faellig is not None:
            aktionen.append(Aktion(AktionTyp.ESKALIEREN, gid,
                                   alarm_id=int(alarm['ALARM_ID']),
                                   alarm_typ=alarm['TYP'],
                                   stufe=faellig,
                                   start_at=alarm['START_AT']))
    return aktionen


# ── Helfer ─────────────────────────────────────────────────────────────

def _letzter_messwert(geraet_id: int) -> dict | None:
    rows = m.messwerte_letzte(geraet_id, 1)
    return rows[0] if rows else None


def _abweichungs_handler(*, gid, typ, verstoss, aktueller_alarm, wert,
                         verstoss_bedingung, karenz_min, jetzt_utc
                         ) -> list[Aktion]:
    """Gemeinsame Logik fuer temp_hoch, temp_tief, drift.

    Oeffnen: Verstoss + kein offener Alarm + Verstoss bestand bereits
             seit ``karenz_min`` Minuten (Blick in die Historie).
    Schliessen: kein Verstoss, offener Alarm + Wert durchgaengig wieder
                im Band seit ``ABSCHLUSS_KARENZ_MIN``.
    """
    if verstoss and not aktueller_alarm:
        if _hat_dauerhaft_verstossen(gid, karenz_min, jetzt_utc,
                                     verstoss_bedingung):
            start = jetzt_utc - timedelta(minutes=karenz_min)
            return [Aktion(AktionTyp.OEFFNEN, gid, alarm_typ=typ,
                           start_at=start, wert=wert)]
    elif not verstoss and aktueller_alarm:
        if _ist_dauerhaft_im_band(gid, ABSCHLUSS_KARENZ_MIN, jetzt_utc,
                                  verstoss_bedingung):
            return [Aktion(AktionTyp.SCHLIESSEN, gid, alarm_typ=typ,
                           alarm_id=int(aktueller_alarm['ALARM_ID']),
                           ende_at=jetzt_utc)]
    return []


def _hat_dauerhaft_verstossen(geraet_id, minuten, jetzt_utc, bedingung) -> bool:
    """True wenn in den letzten ``minuten`` Minuten ALLE gueltigen Messwerte die
    Bedingung (``bedingung(mw) == True``) erfuellen UND die Historie das Fenster
    zu mindestens 80% abdeckt (oldest value ≥ 0.8 · minuten alt).

    Die Deckungs-Pruefung verhindert Fehlalarme, wenn wir zu wenig Historie
    haben (frisch angelegter Sensor, gerade aus offline zurueck)."""
    von = jetzt_utc - timedelta(minutes=minuten)
    werte = m.messwerte_zeitraum(geraet_id, von, jetzt_utc)
    gueltig = [w for w in werte if w['TEMP_C'] is not None
                                   and not w['NO_CONNECTION']]
    if not gueltig:
        return False
    oldest_alter_min = (jetzt_utc - gueltig[0]['ZEITPUNKT_UTC']
                        ).total_seconds() / 60
    if oldest_alter_min < minuten * 0.8:
        return False
    return all(bedingung(w) for w in gueltig)


def _ist_dauerhaft_im_band(geraet_id, minuten, jetzt_utc, bedingung) -> bool:
    """True wenn in den letzten ``minuten`` Minuten KEIN Messwert mehr
    die Verstoss-Bedingung erfuellt und mindestens einer da ist."""
    von = jetzt_utc - timedelta(minutes=minuten)
    werte = m.messwerte_zeitraum(geraet_id, von, jetzt_utc)
    gueltig = [w for w in werte if w['TEMP_C'] is not None
                                   and not w['NO_CONNECTION']]
    if not gueltig:
        return False
    return not any(bedingung(w) for w in gueltig)


def _drift_condition_factory(gid, drift_k, fenster_h):
    """Liefert eine Bedingungs-Funktion fuer Drift-Verstoss.
    Wichtig: Median wird nur *einmal* pro Pruefung berechnet und nicht pro
    Messwert — Abweichung gilt relativ zum aktuellen Prueffenster."""
    def bed(mw):
        if mw['TEMP_C'] is None or mw['NO_CONNECTION']:
            return False
        # Median zum Zeitpunkt des jeweiligen MW
        med = m.rolling_median_temp(gid, mw['ZEITPUNKT_UTC'], fenster_h)
        return med is not None and abs(float(mw['TEMP_C']) - med) > drift_k
    return bed


def _alle_offenen_fuer(gid, *kandidaten) -> list[dict]:
    return [a for a in kandidaten if a and int(a['GERAET_ID']) == gid]


def _naechste_faellige_stufe(alarm: dict, alarmkette: list[dict],
                             jetzt_utc: datetime) -> int | None:
    """Liefert die kleinste Stufe, deren DELAY_MIN erreicht ist UND deren
    Empfaenger noch nicht benachrichtigt wurden (LETZTE_STUFE < diese Stufe)."""
    bereits = int(alarm.get('LETZTE_STUFE') or 0)
    minuten_offen = (jetzt_utc - alarm['START_AT']).total_seconds() / 60
    stufen = sorted({int(e['STUFE']) for e in alarmkette
                     if int(e['STUFE']) > bereits})
    for stufe in stufen:
        delays = [int(e['DELAY_MIN']) for e in alarmkette
                  if int(e['STUFE']) == stufe]
        if delays and minuten_offen >= min(delays):
            return stufe
    return None
