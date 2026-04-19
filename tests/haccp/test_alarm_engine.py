"""
Unit-Tests fuer modules/haccp/alarm_engine.py.

Kein DB-Zugriff – alle Zugriffe ueber modules.haccp.models sind gemockt.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from modules.haccp import alarm_engine as ae
from modules.haccp.alarm_engine import AktionTyp


# ── Fabriken fuer Testdaten ─────────────────────────────────────────────

def _geraet(gid=1, name='Test'):
    return {'GERAET_ID': gid, 'NAME': name,
            'STANDORT': 'Kueche', 'WARENGRUPPE': 'Milch'}


def _grenz(**k):
    g = {'TEMP_MIN_C': 2.0, 'TEMP_MAX_C': 8.0, 'KARENZ_MIN': 15,
         'STALE_MIN': 30, 'DRIFT_AKTIV': 0, 'DRIFT_K': None,
         'DRIFT_FENSTER_H': 24}
    g.update(k)
    return g


def _mw(temp, zeitpunkt, *, feuchte=None, bat=False, nc=False):
    return {'TEMP_C': temp, 'FEUCHTE_PCT': feuchte,
            'ZEITPUNKT_UTC': zeitpunkt,
            'BATTERY_LOW': bat, 'NO_CONNECTION': nc}


def _alarm(gid, typ, start_at, alarm_id=77, letzte_stufe=0):
    return {'ALARM_ID': alarm_id, 'GERAET_ID': gid,
            'TYP': typ, 'START_AT': start_at, 'ENDE_AT': None,
            'MAX_WERT': None, 'LETZTE_STUFE': letzte_stufe}


# ── Patch-Helfer ────────────────────────────────────────────────────────

class _ModelsStub:
    """Haelt alle Mock-Rueckgaben zentral, damit jeder Test nur setzen muss,
    was ihn interessiert."""
    def __init__(self):
        self.letzter_mw = None
        self.zeitraum_mw = []          # list[dict]
        self.alarme_offen = {}         # typ -> dict | None
        self.rolling_median = None
        self.alarmkette = []

    def messwerte_letzte(self, gid, n):
        return [self.letzter_mw] if self.letzter_mw else []

    def messwerte_zeitraum(self, gid, von, bis):
        # Real DB query uses ORDER BY ZEITPUNKT_UTC (asc) — stub muss passen.
        sel = [w for w in self.zeitraum_mw if von <= w['ZEITPUNKT_UTC'] <= bis]
        return sorted(sel, key=lambda w: w['ZEITPUNKT_UTC'])

    def alarm_offen(self, gid, typ):
        return self.alarme_offen.get(typ)

    def rolling_median_temp(self, gid, ende, fenster_h):
        return self.rolling_median

    def alarmkette_aktiv(self):
        return list(self.alarmkette)


def _patches(stub):
    """Patched alle Models-Calls, auf die alarm_engine zugreift."""
    return [
        patch('modules.haccp.alarm_engine.m.messwerte_letzte',
              side_effect=stub.messwerte_letzte),
        patch('modules.haccp.alarm_engine.m.messwerte_zeitraum',
              side_effect=stub.messwerte_zeitraum),
        patch('modules.haccp.alarm_engine.m.alarm_offen',
              side_effect=stub.alarm_offen),
        patch('modules.haccp.alarm_engine.m.rolling_median_temp',
              side_effect=stub.rolling_median_temp),
        patch('modules.haccp.alarm_engine.m.alarmkette_aktiv',
              side_effect=stub.alarmkette_aktiv),
    ]


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.jetzt = datetime(2026, 4, 18, 12, 0)
        self.stub = _ModelsStub()
        self._patches = _patches(self.stub)
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()


# ── 1. Offline-Detection ────────────────────────────────────────────────

class TestOfflineDetection(BaseCase):

    def test_kein_messwert_oeffnet_offline(self):
        self.stub.letzter_mw = None
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        typen = [(a.typ, a.alarm_typ) for a in akt]
        self.assertIn((AktionTyp.OEFFNEN, 'offline'), typen)

    def test_frischer_messwert_kein_offline(self):
        self.stub.letzter_mw = _mw(4.0, self.jetzt - timedelta(minutes=5))
        self.stub.zeitraum_mw = [self.stub.letzter_mw]
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        self.assertFalse(any(a.alarm_typ == 'offline' for a in akt))

    def test_alter_messwert_oeffnet_offline(self):
        self.stub.letzter_mw = _mw(4.0, self.jetzt - timedelta(minutes=45))
        akt = ae.auswerten(_geraet(), _grenz(stale_min=30), self.jetzt)
        # Hinweis: Key in models ist STALE_MIN — _grenz passt das um.
        typen = [(a.typ, a.alarm_typ) for a in akt]
        self.assertIn((AktionTyp.OEFFNEN, 'offline'), typen)

    def test_wieder_frisch_schliesst_offline(self):
        self.stub.letzter_mw = _mw(4.0, self.jetzt - timedelta(minutes=2))
        self.stub.zeitraum_mw = [self.stub.letzter_mw]
        self.stub.alarme_offen['offline'] = _alarm(1, 'offline',
                                                   self.jetzt - timedelta(hours=2))
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        schliessen = [a for a in akt if a.typ == AktionTyp.SCHLIESSEN
                                       and a.alarm_typ == 'offline']
        self.assertEqual(len(schliessen), 1)


# ── 2. Absolut-Alarm: temp_hoch / temp_tief mit Karenz ──────────────────

class TestTempAbsolut(BaseCase):

    def _zeitreihe(self, temp, minuten_zurueck):
        """Erzeugt eine Reihe Messwerte mit konstanter Temp seit ``minuten_zurueck``."""
        return [_mw(temp, self.jetzt - timedelta(minutes=i))
                for i in range(minuten_zurueck + 1)]

    def test_kurze_abweichung_kein_alarm(self):
        # 10 Min. zu warm, Karenz 15 -> noch kein Alarm
        self.stub.letzter_mw = _mw(9.5, self.jetzt)
        self.stub.zeitraum_mw = self._zeitreihe(9.5, 10)
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        self.assertFalse(any(a.alarm_typ == 'temp_hoch' for a in akt))

    def test_langere_abweichung_oeffnet_alarm(self):
        # 20 Min. durchgaengig zu warm, Karenz 15 -> Alarm
        self.stub.letzter_mw = _mw(9.5, self.jetzt)
        self.stub.zeitraum_mw = self._zeitreihe(9.5, 20)
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        self.assertTrue(any(a.typ == AktionTyp.OEFFNEN
                            and a.alarm_typ == 'temp_hoch' for a in akt))

    def test_unterbrechung_in_karenz_kein_alarm(self):
        # Die meisten Werte zu warm, aber einer im Band -> kein Alarm
        self.stub.letzter_mw = _mw(9.5, self.jetzt)
        werte = self._zeitreihe(9.5, 20)
        werte[10] = _mw(7.0, werte[10]['ZEITPUNKT_UTC'])  # einmal OK
        self.stub.zeitraum_mw = werte
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        self.assertFalse(any(a.alarm_typ == 'temp_hoch'
                             and a.typ == AktionTyp.OEFFNEN for a in akt))

    def test_temp_tief_wird_erkannt(self):
        self.stub.letzter_mw = _mw(0.5, self.jetzt)
        self.stub.zeitraum_mw = self._zeitreihe(0.5, 20)
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        self.assertTrue(any(a.typ == AktionTyp.OEFFNEN
                            and a.alarm_typ == 'temp_tief' for a in akt))

    def test_hoch_nicht_nochmal_oeffnen_wenn_schon_offen(self):
        self.stub.letzter_mw = _mw(9.5, self.jetzt)
        self.stub.zeitraum_mw = self._zeitreihe(9.5, 30)
        self.stub.alarme_offen['temp_hoch'] = _alarm(1, 'temp_hoch',
                                                     self.jetzt - timedelta(hours=1))
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        # Kein zweites OEFFNEN fuer temp_hoch
        hoch_oeffnen = [a for a in akt if a.typ == AktionTyp.OEFFNEN
                                         and a.alarm_typ == 'temp_hoch']
        self.assertEqual(len(hoch_oeffnen), 0)

    def test_rueckkehr_ins_band_schliesst_alarm(self):
        # Wert seit 12 Min. wieder OK, Abschluss-Karenz 10 -> schliessen
        self.stub.letzter_mw = _mw(6.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(6.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(12)]
        self.stub.alarme_offen['temp_hoch'] = _alarm(1, 'temp_hoch',
                                                     self.jetzt - timedelta(hours=1))
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        schliessen = [a for a in akt if a.typ == AktionTyp.SCHLIESSEN
                                       and a.alarm_typ == 'temp_hoch']
        self.assertEqual(len(schliessen), 1)

    def test_rueckkehr_zu_kurz_schliesst_nicht(self):
        # Nur 5 Min. wieder OK -> nicht schliessen
        self.stub.letzter_mw = _mw(6.0, self.jetzt)
        werte = [_mw(6.0, self.jetzt - timedelta(minutes=i))
                 for i in range(6)]
        werte += [_mw(9.5, self.jetzt - timedelta(minutes=i))
                  for i in range(6, 15)]
        self.stub.zeitraum_mw = werte
        self.stub.alarme_offen['temp_hoch'] = _alarm(1, 'temp_hoch',
                                                     self.jetzt - timedelta(hours=1))
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        schliessen = [a for a in akt if a.typ == AktionTyp.SCHLIESSEN
                                       and a.alarm_typ == 'temp_hoch']
        self.assertEqual(len(schliessen), 0)


# ── 3. Drift-Alarm ──────────────────────────────────────────────────────

class TestDrift(BaseCase):

    def test_drift_nicht_aktiv_kein_alarm(self):
        self.stub.letzter_mw = _mw(12.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(12.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(20)]
        self.stub.rolling_median = 5.0
        akt = ae.auswerten(_geraet(),
                           _grenz(DRIFT_AKTIV=0), self.jetzt)
        self.assertFalse(any(a.alarm_typ == 'drift' for a in akt))

    def test_drift_ohne_median_kein_alarm(self):
        self.stub.letzter_mw = _mw(12.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(12.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(20)]
        self.stub.rolling_median = None  # zu wenige Werte
        akt = ae.auswerten(_geraet(),
                           _grenz(TEMP_MIN_C=-50, TEMP_MAX_C=50,
                                  DRIFT_AKTIV=1, DRIFT_K=2.0), self.jetzt)
        self.assertFalse(any(a.alarm_typ == 'drift' for a in akt))

    def test_drift_nicht_wenn_absolut_alarm(self):
        # Wert ausserhalb Band UND drift waere auch erfuellt
        # -> nur absolut-Alarm, kein drift-Alarm.
        self.stub.letzter_mw = _mw(12.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(12.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(20)]
        self.stub.rolling_median = 5.0
        akt = ae.auswerten(_geraet(),
                           _grenz(TEMP_MIN_C=2, TEMP_MAX_C=8,
                                  DRIFT_AKTIV=1, DRIFT_K=2.0,
                                  KARENZ_MIN=15), self.jetzt)
        alarm_typen = {a.alarm_typ for a in akt if a.typ == AktionTyp.OEFFNEN}
        self.assertIn('temp_hoch', alarm_typen)
        self.assertNotIn('drift', alarm_typen)


# ── 4. Battery-Low ──────────────────────────────────────────────────────

class TestBattery(BaseCase):

    def test_battery_low_oeffnet_alarm(self):
        self.stub.letzter_mw = _mw(4.0, self.jetzt, bat=True)
        self.stub.zeitraum_mw = [self.stub.letzter_mw]
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        self.assertTrue(any(a.typ == AktionTyp.OEFFNEN
                            and a.alarm_typ == 'battery' for a in akt))

    def test_battery_low_verschwindet_schliesst_alarm(self):
        self.stub.letzter_mw = _mw(4.0, self.jetzt, bat=False)
        self.stub.zeitraum_mw = [self.stub.letzter_mw]
        self.stub.alarme_offen['battery'] = _alarm(1, 'battery',
                                                   self.jetzt - timedelta(days=1))
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        self.assertTrue(any(a.typ == AktionTyp.SCHLIESSEN
                            and a.alarm_typ == 'battery' for a in akt))


# ── 5. Eskalation ───────────────────────────────────────────────────────

class TestEskalation(BaseCase):

    def _kette(self):
        return [
            {'STUFE': 1, 'DELAY_MIN': 0,  'EMAIL': 'kueche@x.de', 'NAME': 'Kueche', 'AKTIV': 1},
            {'STUFE': 2, 'DELAY_MIN': 30, 'EMAIL': 'bl@x.de',     'NAME': 'BL',     'AKTIV': 1},
            {'STUFE': 3, 'DELAY_MIN': 120,'EMAIL': 'gf@x.de',     'NAME': 'GF',     'AKTIV': 1},
        ]

    def test_eskalation_erreicht_stufe_2_nach_30_min(self):
        # Alarm laeuft seit 35 Min., war zuletzt auf Stufe 1
        alarm = _alarm(1, 'temp_hoch',
                       self.jetzt - timedelta(minutes=35), letzte_stufe=1)
        self.stub.alarme_offen['temp_hoch'] = alarm
        # Letzter Wert zurueck im Band -> keine Abschlussaktion wegen Zeitraum
        self.stub.letzter_mw = _mw(9.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(9.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(40)]
        self.stub.alarmkette = self._kette()
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        esk = [a for a in akt if a.typ == AktionTyp.ESKALIEREN]
        self.assertEqual(len(esk), 1)
        self.assertEqual(esk[0].stufe, 2)

    def test_eskalation_nicht_wenn_schon_auf_stufe_2(self):
        alarm = _alarm(1, 'temp_hoch',
                       self.jetzt - timedelta(minutes=35), letzte_stufe=2)
        self.stub.alarme_offen['temp_hoch'] = alarm
        self.stub.letzter_mw = _mw(9.0, self.jetzt)
        self.stub.zeitraum_mw = [_mw(9.0, self.jetzt - timedelta(minutes=i))
                                 for i in range(40)]
        self.stub.alarmkette = self._kette()
        akt = ae.auswerten(_geraet(), _grenz(KARENZ_MIN=15), self.jetzt)
        esk = [a for a in akt if a.typ == AktionTyp.ESKALIEREN]
        # Nur bis Stufe 3 faellig waere, aber erst nach 120 min
        self.assertEqual(len(esk), 0)

    def test_eskalation_springt_direkt_auf_stufe_3_bei_lang_liegendem_alarm(self):
        alarm = _alarm(1, 'offline',
                       self.jetzt - timedelta(minutes=130), letzte_stufe=2)
        self.stub.alarme_offen['offline'] = alarm
        self.stub.letzter_mw = _mw(4.0, self.jetzt - timedelta(minutes=200))
        self.stub.alarmkette = self._kette()
        akt = ae.auswerten(_geraet(), _grenz(), self.jetzt)
        esk = [a for a in akt if a.typ == AktionTyp.ESKALIEREN]
        self.assertEqual(len(esk), 1)
        self.assertEqual(esk[0].stufe, 3)


# ── 6. _naechste_faellige_stufe direkt ──────────────────────────────────

class TestNaechsteFaellige(unittest.TestCase):

    def setUp(self):
        self.jetzt = datetime(2026, 4, 18, 12, 0)

    def test_frisch_und_stufe_1_sofort(self):
        alarm = {'START_AT': self.jetzt, 'LETZTE_STUFE': 0}
        kette = [{'STUFE': 1, 'DELAY_MIN': 0}]
        self.assertEqual(
            ae._naechste_faellige_stufe(alarm, kette, self.jetzt), 1)

    def test_noch_nicht_faellig(self):
        alarm = {'START_AT': self.jetzt - timedelta(minutes=5),
                 'LETZTE_STUFE': 1}
        kette = [{'STUFE': 2, 'DELAY_MIN': 30}]
        self.assertIsNone(
            ae._naechste_faellige_stufe(alarm, kette, self.jetzt))

    def test_min_delay_pro_stufe_zaehlt(self):
        # zwei Empfaenger in Stufe 2 mit unterschiedlichem Delay —
        # der kleinere wird zuerst faellig.
        alarm = {'START_AT': self.jetzt - timedelta(minutes=20),
                 'LETZTE_STUFE': 1}
        kette = [
            {'STUFE': 2, 'DELAY_MIN': 30},
            {'STUFE': 2, 'DELAY_MIN': 15},
        ]
        self.assertEqual(
            ae._naechste_faellige_stufe(alarm, kette, self.jetzt), 2)


if __name__ == '__main__':
    unittest.main()
