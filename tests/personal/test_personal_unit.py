"""
Unit-Tests fuer modules/orga/personal/models.py und tools/import_csv.py.

Kein DB-Zugriff – DB-abhaengige Funktionen werden gemockt.
"""
import json
import os
import sys
import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from modules.orga.personal import models as m
from modules.orga.personal import routes as r
from modules.orga.personal.tools import import_csv as ic


class TestNormalisiere(unittest.TestCase):

    def test_nur_bekannte_felder(self):
        out = m._normalisiere({
            'VNAME': 'Maria', 'NAME': 'Klein',
            'FREMDES_FELD': 'x', 'PERSONALNUMMER': '11',
        })
        self.assertIn('VNAME', out)
        self.assertIn('PERSONALNUMMER', out)
        self.assertNotIn('FREMDES_FELD', out)

    def test_leere_strings_zu_none(self):
        out = m._normalisiere({'EMAIL': '', 'EMAIL_ALT': '   ', 'NAME': 'x'})
        self.assertIsNone(out['EMAIL'])
        self.assertIsNone(out['EMAIL_ALT'])
        self.assertEqual(out['NAME'], 'x')


class TestCtZuEurostr(unittest.TestCase):

    def test_none(self):
        self.assertEqual(m.ct_to_eurostr(None), '')

    def test_glatter_euro(self):
        self.assertEqual(m.ct_to_eurostr(100), '1,00')

    def test_13_90(self):
        self.assertEqual(m.ct_to_eurostr(1390), '13,90')


class TestMaInsertValidierung(unittest.TestCase):

    def test_fehlende_pflichtfelder(self):
        with self.assertRaises(ValueError):
            m.ma_insert({'VNAME': 'x'}, 1)
        with self.assertRaises(ValueError):
            m.ma_insert({'NAME': 'x', 'PERSONALNUMMER': '1'}, 1)
        with self.assertRaises(ValueError):
            m.ma_insert({'VNAME': 'x', 'NAME': 'y'}, 1)


class TestMaUpdateDiff(unittest.TestCase):

    def _cur_mit_bestand(self, alt: dict):
        cur = MagicMock()
        cur.fetchone.return_value = alt
        return cur

    def test_keine_aenderung_kein_update(self):
        alt = {'PERS_ID': 1, 'VNAME': 'Maria', 'NAME': 'Klein',
               'EMAIL': 'm@x.de'}
        cur = self._cur_mit_bestand(alt)
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = cur
        mock_ctx.__exit__.return_value = False
        with patch('modules.orga.personal.models.get_db_rw',
                   return_value=mock_ctx):
            anz = m.ma_update(1, {'VNAME': 'Maria', 'EMAIL': 'm@x.de'}, 2)
        self.assertEqual(anz, 0)

    def test_diff_wird_geloggt(self):
        alt = {'PERS_ID': 1, 'VNAME': 'Maria', 'NAME': 'Klein',
               'EMAIL': 'alt@x.de'}
        cur = self._cur_mit_bestand(alt)
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = cur
        mock_ctx.__exit__.return_value = False
        with patch('modules.orga.personal.models.get_db_rw',
                   return_value=mock_ctx):
            anz = m.ma_update(1, {'EMAIL': 'neu@x.de'}, 2)
        self.assertEqual(anz, 1)
        # Pruefe dass UPDATE + INSERT INTO _LOG gerufen wurden
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any('UPDATE XT_PERSONAL_MA' in s for s in sqls))
        self.assertTrue(any('XT_PERSONAL_MA_LOG' in s for s in sqls))


class TestCsvParsing(unittest.TestCase):

    def test_parse_date(self):
        self.assertEqual(ic._parse_date('1968-09-25'), date(1968, 9, 25))
        self.assertIsNone(ic._parse_date(''))
        self.assertIsNone(ic._parse_date('  '))
        self.assertIsNone(ic._parse_date('ungueltig'))

    def test_parse_eur(self):
        self.assertEqual(ic._parse_eur_to_ct('13.90'), 1390)
        self.assertEqual(ic._parse_eur_to_ct('0.00'), 0)
        self.assertIsNone(ic._parse_eur_to_ct(''))
        self.assertIsNone(ic._parse_eur_to_ct('kein_zahl'))

    def test_row_mapping(self):
        row = {
            'id': '5', 'externalEmployeeID': '10',
            'firstname': 'Claudia', 'lastname': 'David', 'shorthand': 'dav',
            'email': 'c@x.de', 'alternativeEmail': 'c2@x.de',
            'birthday': '1964-03-09', 'hourlyRate': '13.90',
            'dateEntry': '2012-05-01', 'dateLeave': '',
            'Strasse': 'Haupt 1', 'PLZ': '82392', 'Stadt': 'Habach',
            'Telefon (privat)': '', 'Mobil (privat)': '0172-123',
        }
        werte, satz_ct, gueltig_ab = ic._row_zu_werte(row)
        self.assertEqual(werte['PERSONALNUMMER'], '10')
        self.assertEqual(werte['VNAME'], 'Claudia')
        self.assertEqual(werte['NAME'], 'David')
        self.assertEqual(werte['KUERZEL'], 'DAV')   # uppercase!
        self.assertEqual(werte['GEBDATUM'], date(1964, 3, 9))
        self.assertEqual(werte['EMAIL_ALT'], 'c2@x.de')
        self.assertEqual(werte['EINTRITT'], date(2012, 5, 1))
        self.assertIsNone(werte['AUSTRITT'])
        self.assertIsNone(werte['TELEFON'])
        self.assertEqual(werte['MOBIL'], '0172-123')
        self.assertEqual(satz_ct, 1390)
        self.assertEqual(gueltig_ab, date(2012, 5, 1))


class TestMinijobCheck(unittest.TestCase):
    """Live-Minijob-Pruefung gegen die Grenze 2026 (603 €)."""

    GRENZE_2026 = 60300   # 603,00 €

    def test_woche_knapp_unter_grenze(self):
        # 10 h/Woche × 13,90 € × 4,33 = 601,87 €  → unter 603 €
        res = m.minijob_check(10, 'WOCHE', 1390, self.GRENZE_2026)
        self.assertEqual(res['brutto_monat_ct'], 60187)
        self.assertFalse(res['ueberschreitet'])
        self.assertEqual(res['differenz_ct'], -113)

    def test_woche_ueber_grenze(self):
        # 15 h/Woche × 13,90 € × 4,33 = 902,80 €  → ueber
        res = m.minijob_check(15, 'WOCHE', 1390, self.GRENZE_2026)
        self.assertEqual(res['brutto_monat_ct'], 90280)
        self.assertTrue(res['ueberschreitet'])

    def test_monat_direkt(self):
        # 40 h/Monat × 13,90 € = 556 €  → unter (ohne Faktor)
        res = m.minijob_check(40, 'MONAT', 1390, self.GRENZE_2026)
        self.assertEqual(res['brutto_monat_ct'], 55600)
        self.assertFalse(res['ueberschreitet'])

    def test_null_eingabe(self):
        res = m.minijob_check(0, 'WOCHE', 1390, self.GRENZE_2026)
        self.assertEqual(res['brutto_monat_ct'], 0)
        self.assertFalse(res['ueberschreitet'])


class TestAzModellPflichtfelder(unittest.TestCase):

    def test_fehlende_pflichtfelder(self):
        with self.assertRaises(ValueError):
            m.az_modell_speichern(1, {'TYP': 'WOCHE', 'STUNDEN_SOLL': 10}, 2)
        with self.assertRaises(ValueError):
            m.az_modell_speichern(1, {
                'GUELTIG_AB': '2026-01-01', 'LOHNART_ID': 1,
                'TYP': 'UNGUELTIG', 'STUNDEN_SOLL': 10,
            }, 2)


class TestAzModellBearbeiten(unittest.TestCase):
    """az_modell_bearbeiten: GUELTIG_AB wird uebernommen, Vorgaenger gekuerzt,
    und jede Aenderung landet im AZ_MODELL_LOG."""

    def _patch_cur(self, fetchone_side_effect):
        cur = MagicMock()
        cur.fetchone.side_effect = fetchone_side_effect
        cur.rowcount = 1
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return cur, patch('modules.orga.personal.models.get_db_rw',
                          return_value=ctx)

    def test_gueltig_ab_wird_gesetzt_und_vorgaenger_gekuerzt(self):
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': None,
             'GUELTIG_AB': date(2026, 1, 1)},
            {'n': 0},
        ])
        with p:
            anz = m.az_modell_bearbeiten(
                42, {'GUELTIG_AB': date(2026, 3, 1)}, 7,
            )
        self.assertEqual(anz, 1)
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Vorgaenger-Kuerzung + finales UPDATE + LOG-INSERT muessen laufen
        self.assertTrue(any('GUELTIG_BIS = DATE_SUB' in s for s in sqls))
        self.assertTrue(any('SET GUELTIG_AB = %s' in s for s in sqls))
        self.assertTrue(any('XT_PERSONAL_AZ_MODELL_LOG' in s for s in sqls))

    def test_gueltig_ab_nach_eigenem_bis_wirft(self):
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': date(2026, 2, 28),
             'GUELTIG_AB': date(2026, 1, 1)},
        ])
        with p, self.assertRaises(ValueError):
            m.az_modell_bearbeiten(42, {'GUELTIG_AB': date(2026, 3, 1)}, 7)

    def test_gueltig_ab_kollision_wirft(self):
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': None,
             'GUELTIG_AB': date(2026, 1, 1)},
            {'n': 1},  # anderer Datensatz startet bereits am selben Tag
        ])
        with p, self.assertRaises(ValueError):
            m.az_modell_bearbeiten(42, {'GUELTIG_AB': date(2026, 3, 1)}, 7)

    def test_gueltig_ab_none_wirft(self):
        # Alter Wert ist ein echtes Datum, neu = None → Diff erkennt Aenderung,
        # Branch wird betreten und wirft ValueError.
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': None,
             'GUELTIG_AB': date(2026, 1, 1)},
        ])
        with p, self.assertRaises(ValueError):
            m.az_modell_bearbeiten(42, {'GUELTIG_AB': None}, 7)

    def test_ohne_gueltig_ab_aendert_andere_felder(self):
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': None, 'STUNDEN_SOLL': 15},
        ])
        with p:
            anz = m.az_modell_bearbeiten(42, {'STUNDEN_SOLL': 20}, 7)
        self.assertEqual(anz, 1)
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        # Keine Vorgaenger-Kuerzung bei reiner Feldaenderung
        self.assertFalse(any('DATE_SUB' in s for s in sqls))
        self.assertTrue(any('SET STUNDEN_SOLL = %s' in s for s in sqls))
        # Log wird trotzdem geschrieben
        self.assertTrue(any('XT_PERSONAL_AZ_MODELL_LOG' in s for s in sqls))

    def test_keine_echte_aenderung_kein_update(self):
        # Diff ist leer (neu == alt) → return 0, kein UPDATE, kein LOG
        cur, p = self._patch_cur([
            {'PERS_ID': 1, 'GUELTIG_BIS': None, 'STUNDEN_SOLL': 20},
        ])
        with p:
            anz = m.az_modell_bearbeiten(42, {'STUNDEN_SOLL': 20}, 7)
        self.assertEqual(anz, 0)
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertFalse(any('XT_PERSONAL_AZ_MODELL_LOG' in s for s in sqls))
        self.assertFalse(any('UPDATE XT_PERSONAL_AZ_MODELL' in s
                             and 'DATE_SUB' not in s for s in sqls))


class TestFaktor(unittest.TestCase):
    def test_konstante_4_33(self):
        self.assertEqual(m.FAKTOR_WOCHE_MONAT, 4.33)


class TestJsonDefault(unittest.TestCase):

    def test_date_wird_serialisiert(self):
        s = json.dumps({'d': date(2026, 1, 1)}, default=m._json_default)
        self.assertIn('2026-01-01', s)

    def test_unbekannter_typ_wirft(self):
        with self.assertRaises(TypeError):
            json.dumps({'x': object()}, default=m._json_default)


class TestArbeitstageZaehlung(unittest.TestCase):
    """urlaub_arbeitstage zaehlt Tage anhand der Wochenverteilung des jeweils
    gueltigen AZ-Modells. Wir mocken aktuelles_az_modell."""

    def test_mo_fr_modell(self):
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell):
            # Mo 2026-04-13 .. So 2026-04-19 = 5 Arbeitstage
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 13), date(2026, 4, 19)),
                5.0,
            )

    def test_teilzeit_mo_mi_fr(self):
        modell = {'STD_MO': 4, 'STD_DI': None, 'STD_MI': 4, 'STD_DO': None,
                  'STD_FR': 4, 'STD_SA': None, 'STD_SO': None}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell):
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 13), date(2026, 4, 19)),
                3.0,
            )

    def test_fallback_ohne_verteilung(self):
        # Alle STD_* None → Fallback Mo–Fr
        modell = {k: None for k in m.WOCHENTAGE}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell):
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 13), date(2026, 4, 19)),
                5.0,
            )

    def test_kein_modell_null_tage(self):
        with patch.object(m, 'aktuelles_az_modell', return_value=None):
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 13), date(2026, 4, 19)),
                0.0,
            )

    def test_einzelner_tag(self):
        modell = {'STD_MO': 8, 'STD_DI': None, 'STD_MI': None, 'STD_DO': None,
                  'STD_FR': None, 'STD_SA': None, 'STD_SO': None}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell):
            # Montag
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 13), date(2026, 4, 13)),
                1.0,
            )
            # Dienstag – kein Arbeitstag
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 14), date(2026, 4, 14)),
                0.0,
            )

    def test_bis_vor_von(self):
        self.assertEqual(m.urlaub_arbeitstage(1, date(2026, 4, 20),
                                              date(2026, 4, 13)), 0.0)


class TestUrlaubAntragValidierung(unittest.TestCase):

    def test_bis_vor_von_wirft(self):
        with self.assertRaises(ValueError):
            m.urlaub_antrag_anlegen(1, date(2026, 5, 1), date(2026, 4, 30),
                                    None, 2)

    def test_unbekannter_status_wirft(self):
        with self.assertRaises(ValueError):
            m.urlaub_antrag_anlegen(1, date(2026, 5, 1), date(2026, 5, 5),
                                    None, 2, status='erledigt')


class TestStatusUebergang(unittest.TestCase):

    def _mock_cursor(self, aktuell_status: str | None):
        cur = MagicMock()
        cur.fetchone.return_value = (
            {'PERS_ID': 1, 'STATUS': aktuell_status}
            if aktuell_status else None
        )
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm, cur

    def test_erlaubt_geplant_zu_genehmigt(self):
        cm, cur = self._mock_cursor('geplant')
        with patch.object(m, 'get_db_rw', return_value=cm):
            n = m.urlaub_antrag_status_setzen(1, 'genehmigt', 2)
        self.assertEqual(n, 1)

    def test_verboten_geplant_zu_genommen(self):
        cm, cur = self._mock_cursor('geplant')
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError):
                m.urlaub_antrag_status_setzen(1, 'genommen', 2)

    def test_verboten_storniert_ist_terminal(self):
        cm, cur = self._mock_cursor('storniert')
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError):
                m.urlaub_antrag_status_setzen(1, 'geplant', 2)

    def test_gleichbleiben_ist_noop(self):
        cm, cur = self._mock_cursor('geplant')
        with patch.object(m, 'get_db_rw', return_value=cm):
            n = m.urlaub_antrag_status_setzen(1, 'geplant', 2)
        self.assertEqual(n, 0)

    def test_nicht_existent_wirft(self):
        cm, cur = self._mock_cursor(None)
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(LookupError):
                m.urlaub_antrag_status_setzen(1, 'genehmigt', 2)

    def test_unbekannter_zielstatus_wirft(self):
        with self.assertRaises(ValueError):
            m.urlaub_antrag_status_setzen(1, 'erledigt', 2)


class TestUrlaubAbschliessen(unittest.TestCase):
    """Tagesaktueller Auto-Abschluss: 'genehmigt' → 'genommen' wenn BIS < heute.
    Betroffene Antraege werden zuerst via SELECT geladen, dann bulk-UPDATE,
    danach je Zeile ein LOG-Eintrag mit GEAEND_VON = NULL (System)."""

    def _mock_cursor(self, betroffene: list[dict] | None = None,
                     rowcount: int = 0):
        cur = MagicMock()
        cur.fetchall.return_value = betroffene or []
        cur.rowcount = rowcount
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm, cur

    def test_mit_pers_id_filtert_auf_ma(self):
        betroffene = [
            {'REC_ID': 10, 'PERS_ID': 42},
            {'REC_ID': 11, 'PERS_ID': 42},
        ]
        cm, cur = self._mock_cursor(betroffene=betroffene, rowcount=2)
        stichtag = date(2026, 4, 18)
        with patch.object(m, 'get_db_rw', return_value=cm):
            n = m.urlaub_antraege_abschliessen(pers_id=42, stichtag=stichtag)
        self.assertEqual(n, 2)
        calls = [c.args for c in cur.execute.call_args_list]
        sel_sql, sel_params = calls[0]
        self.assertIn("STATUS = 'genehmigt'", sel_sql)
        self.assertIn("BIS < %s", sel_sql)
        self.assertIn("PERS_ID = %s", sel_sql)
        self.assertEqual(sel_params, (stichtag, 42))
        upd_sql = calls[1][0]
        self.assertIn("STATUS = 'genommen'", upd_sql)
        self.assertIn("STATUS_GEAEND_VON = NULL", upd_sql)
        # 2 LOG-Eintraege, GEAEND_VON = None (System-Marker)
        log_calls = [c for c in cur.execute.call_args_list
                     if 'XT_PERSONAL_URLAUB_ANTRAG_LOG' in c.args[0]]
        self.assertEqual(len(log_calls), 2)
        for c in log_calls:
            self.assertIsNone(c.args[1][-1])  # GEAEND_VON ist letzter Param

    def test_ohne_pers_id_global(self):
        cm, cur = self._mock_cursor(betroffene=[], rowcount=0)
        stichtag = date(2026, 4, 18)
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.urlaub_antraege_abschliessen(stichtag=stichtag)
        sel_sql, sel_params = cur.execute.call_args_list[0].args
        self.assertNotIn("PERS_ID = %s", sel_sql)  # kein Filter
        self.assertEqual(sel_params, (stichtag,))

    def test_stichtag_default_ist_heute(self):
        cm, cur = self._mock_cursor(betroffene=[], rowcount=0)
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.urlaub_antraege_abschliessen(pers_id=1)
        sel_params = cur.execute.call_args_list[0].args[1]
        self.assertEqual(sel_params[0], date.today())


class TestKorrekturGrund(unittest.TestCase):

    def test_leerer_grund_wirft(self):
        with self.assertRaises(ValueError):
            m.urlaub_korrektur_anlegen(1, 2026, 3.0, '', None, 2)
        with self.assertRaises(ValueError):
            m.urlaub_korrektur_anlegen(1, 2026, 3.0, '   ', None, 2)


class TestLogSchreiben(unittest.TestCase):
    """Alle schreibenden Personal-Funktionen schreiben zusaetzlich einen
    Audit-Eintrag in die passende LOG-Tabelle (Option A: eine LOG-Tabelle
    pro Haupttabelle)."""

    def _ctx(self, cur):
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm

    def test_az_modell_speichern_schreibt_log(self):
        cur = MagicMock()
        # Fuer Vorgaenger-UPDATE / Nachfolger-Abfrage / INSERT gebraucht
        cur.fetchone.return_value = {'next_ab': None}
        cur.lastrowid = 555
        with patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            m.az_modell_speichern(1, {
                'GUELTIG_AB': date(2026, 1, 1), 'LOHNART_ID': 1,
                'TYP': 'WOCHE', 'STUNDEN_SOLL': 20,
            }, 7)
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any('XT_PERSONAL_AZ_MODELL_LOG' in s for s in sqls))
        log_call = next(c for c in cur.execute.call_args_list
                        if 'XT_PERSONAL_AZ_MODELL_LOG' in c.args[0])
        params = log_call.args[1]
        # params: (PERS_ID, REF_REC_ID, OPERATION, alt_json, neu_json, GEAEND_VON)
        self.assertEqual(params[0], 1)          # PERS_ID
        self.assertEqual(params[1], 555)         # REF_REC_ID = lastrowid
        self.assertEqual(params[2], 'INSERT')
        self.assertIsNone(params[3])             # alt leer bei INSERT
        self.assertIn('"GUELTIG_AB": "2026-01-01"', params[4])
        self.assertIn('"STUNDEN_SOLL": 20', params[4])
        self.assertEqual(params[5], 7)

    def test_urlaub_antrag_anlegen_schreibt_log(self):
        cur = MagicMock()
        cur.lastrowid = 999
        with patch.object(m, 'urlaub_arbeitstage', return_value=5.0):
            with patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
                m.urlaub_antrag_anlegen(
                    1, date(2026, 5, 1), date(2026, 5, 7),
                    'Sommerurlaub', 7,
                )
        log_call = next(c for c in cur.execute.call_args_list
                        if 'XT_PERSONAL_URLAUB_ANTRAG_LOG' in c.args[0])
        params = log_call.args[1]
        self.assertEqual(params[0], 1)
        self.assertEqual(params[1], 999)
        self.assertEqual(params[2], 'INSERT')
        self.assertIsNone(params[3])
        self.assertIn('"STATUS": "geplant"', params[4])
        self.assertIn('"ARBEITSTAGE": 5.0', params[4])
        self.assertEqual(params[5], 7)

    def test_urlaub_antrag_status_setzen_schreibt_log(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'PERS_ID': 1, 'STATUS': 'geplant'}
        cur.rowcount = 1
        with patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            m.urlaub_antrag_status_setzen(42, 'genehmigt', 7)
        log_call = next(c for c in cur.execute.call_args_list
                        if 'XT_PERSONAL_URLAUB_ANTRAG_LOG' in c.args[0])
        params = log_call.args[1]
        self.assertEqual(params[0], 1)
        self.assertEqual(params[1], 42)
        self.assertEqual(params[2], 'UPDATE')
        self.assertIn('"STATUS": "geplant"', params[3])
        self.assertIn('"STATUS": "genehmigt"', params[4])
        self.assertEqual(params[5], 7)


class TestMaLogUnion(unittest.TestCase):
    """ma_log() aggregiert ueber die drei LOG-Tabellen und setzt BEREICH."""

    def test_query_enthaelt_union_aller_drei_tabellen(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        with patch.object(m, 'get_db_ro', return_value=cm):
            m.ma_log(42)
        sql = cur.execute.call_args.args[0]
        self.assertIn('XT_PERSONAL_MA_LOG', sql)
        self.assertIn('XT_PERSONAL_AZ_MODELL_LOG', sql)
        self.assertIn('XT_PERSONAL_URLAUB_ANTRAG_LOG', sql)
        self.assertIn("'Stammdaten'", sql)
        self.assertIn("'Arbeitszeit'", sql)
        self.assertIn("'Urlaub'", sql)
        self.assertIn('UNION ALL', sql)
        params = cur.execute.call_args.args[1]
        # pers_id drei Mal + limit
        self.assertEqual(params, (42, 42, 42, 50))


class TestSchichtBruttoMin(unittest.TestCase):
    """P2: Brutto-Minuten je Zuordnung, inkl. Nachtschicht/flex/aufgabe."""

    def test_fix_time_objekt(self):
        s = {'TYP': 'fix', 'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0)}
        self.assertEqual(m.schicht_brutto_min(s), 6 * 60)

    def test_fix_timedelta_wie_mysql_liefert(self):
        # MySQL/MariaDB liefert TIME-Spalten als timedelta
        s = {'TYP': 'fix',
             'STARTZEIT': timedelta(hours=8),
             'ENDZEIT':   timedelta(hours=17, minutes=30)}
        self.assertEqual(m.schicht_brutto_min(s), 9 * 60 + 30)

    def test_fix_nachtschicht(self):
        s = {'TYP': 'fix', 'STARTZEIT': time(22, 0), 'ENDZEIT': time(6, 0)}
        self.assertEqual(m.schicht_brutto_min(s), 8 * 60)

    def test_flex_nutzt_dauer_parameter(self):
        s = {'TYP': 'flex', 'STARTZEIT': None, 'ENDZEIT': None}
        self.assertEqual(m.schicht_brutto_min(s, dauer_min=90), 90)

    def test_flex_ohne_dauer_ist_null(self):
        s = {'TYP': 'flex', 'STARTZEIT': None, 'ENDZEIT': None}
        self.assertEqual(m.schicht_brutto_min(s), 0)

    def test_aufgabe_ist_immer_null(self):
        s = {'TYP': 'aufgabe', 'STARTZEIT': None, 'ENDZEIT': None}
        self.assertEqual(m.schicht_brutto_min(s, dauer_min=500), 0)

    def test_fix_ohne_zeiten_ist_null(self):
        s = {'TYP': 'fix', 'STARTZEIT': None, 'ENDZEIT': None}
        self.assertEqual(m.schicht_brutto_min(s), 0)


class TestPauseMinFuerDauer(unittest.TestCase):
    """P2: ArbZG §4 - tagesbezogene Pausenregelung mit 2 Schwellen."""

    REGELUNG = {
        'SCHWELLE1_MIN': 360, 'PAUSE1_MIN': 30,
        'SCHWELLE2_MIN': 540, 'PAUSE2_MIN': 45,
        'PAUSE_BEZAHLT_FLAG': 0,
    }

    def test_keine_regelung_null(self):
        self.assertEqual(m.pause_min_fuer_dauer(720, None), 0)

    def test_unter_schwelle1_keine_pause(self):
        # Genau 6h = 360 min: Regel ist ">6h", also KEINE Pause
        self.assertEqual(m.pause_min_fuer_dauer(360, self.REGELUNG), 0)

    def test_zwischen_schwelle1_und_2(self):
        self.assertEqual(m.pause_min_fuer_dauer(361, self.REGELUNG), 30)
        self.assertEqual(m.pause_min_fuer_dauer(540, self.REGELUNG), 30)

    def test_ueber_schwelle2(self):
        self.assertEqual(m.pause_min_fuer_dauer(541, self.REGELUNG), 45)
        self.assertEqual(m.pause_min_fuer_dauer(600, self.REGELUNG), 45)

    def test_null_brutto_null_pause(self):
        self.assertEqual(m.pause_min_fuer_dauer(0, self.REGELUNG), 0)


class TestTagesarbeitszeit(unittest.TestCase):
    """P2: Aggregation mehrerer Zuordnungen pro MA pro Tag."""

    REGELUNG = {
        'SCHWELLE1_MIN': 360, 'PAUSE1_MIN': 30,
        'SCHWELLE2_MIN': 540, 'PAUSE2_MIN': 45,
        'PAUSE_BEZAHLT_FLAG': 0,
    }
    REGELUNG_BEZAHLT = dict(REGELUNG, PAUSE_BEZAHLT_FLAG=1)

    def test_eine_kurze_schicht_keine_pause(self):
        zs = [{'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(12, 0)}]
        agg = m.tagesarbeitszeit_min(zs, self.REGELUNG)
        self.assertEqual(agg, {'brutto_min': 240, 'pause_min': 0, 'netto_min': 240})

    def test_mehrere_schichten_werden_addiert(self):
        # Fix 4h + Flex 3h = 7h > 6h → 30 min Pause
        zs = [
            {'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(12, 0)},
            {'TYP': 'flex', 'DAUER_MIN': 180, 'STARTZEIT': None, 'ENDZEIT': None},
        ]
        agg = m.tagesarbeitszeit_min(zs, self.REGELUNG)
        self.assertEqual(agg['brutto_min'], 420)
        self.assertEqual(agg['pause_min'], 30)
        self.assertEqual(agg['netto_min'], 390)

    def test_aufgabe_erhoeht_brutto_nicht(self):
        zs = [
            {'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(14, 0)},
            {'TYP': 'aufgabe', 'STARTZEIT': None, 'ENDZEIT': None},
        ]
        agg = m.tagesarbeitszeit_min(zs, self.REGELUNG)
        self.assertEqual(agg['brutto_min'], 360)
        self.assertEqual(agg['pause_min'], 0)  # genau 6h, Regel >6h

    def test_lange_schicht_triggert_schwelle2(self):
        # Ganztag 08:00-18:00 = 10h > 9h → 45 min
        zs = [{'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(18, 0)}]
        agg = m.tagesarbeitszeit_min(zs, self.REGELUNG)
        self.assertEqual(agg['brutto_min'], 600)
        self.assertEqual(agg['pause_min'], 45)
        self.assertEqual(agg['netto_min'], 555)

    def test_pause_bezahlt_kein_abzug(self):
        zs = [{'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(18, 0)}]
        agg = m.tagesarbeitszeit_min(zs, self.REGELUNG_BEZAHLT)
        # Pause wird ausgewiesen, aber Netto = Brutto
        self.assertEqual(agg['pause_min'], 45)
        self.assertEqual(agg['netto_min'], 600)

    def test_ohne_regelung_kein_abzug(self):
        zs = [{'TYP': 'fix', 'STARTZEIT': time(8, 0), 'ENDZEIT': time(18, 0)}]
        agg = m.tagesarbeitszeit_min(zs, None)
        self.assertEqual(agg['pause_min'], 0)
        self.assertEqual(agg['netto_min'], 600)

    def test_leere_liste(self):
        self.assertEqual(
            m.tagesarbeitszeit_min([], self.REGELUNG),
            {'brutto_min': 0, 'pause_min': 0, 'netto_min': 0},
        )


class TestSchichtNormalisiere(unittest.TestCase):
    """P2: Typ-abhaengige Zeitbereinigung beim Speichern."""

    def test_flex_zwingt_zeiten_auf_null(self):
        out = m._schicht_normalisiere({
            'TYP': 'flex', 'BEZEICHNUNG': 'Buchhaltung', 'KUERZEL': 'BH',
            'STARTZEIT': '08:00', 'ENDZEIT': '12:00',
        })
        self.assertIsNone(out['STARTZEIT'])
        self.assertIsNone(out['ENDZEIT'])

    def test_aufgabe_zwingt_zeiten_auf_null(self):
        out = m._schicht_normalisiere({
            'TYP': 'aufgabe', 'BEZEICHNUNG': 'Kassenabschluss', 'KUERZEL': 'KA',
            'STARTZEIT': '18:00', 'ENDZEIT': '19:00',
        })
        self.assertIsNone(out['STARTZEIT'])
        self.assertIsNone(out['ENDZEIT'])

    def test_fix_behaelt_zeiten(self):
        out = m._schicht_normalisiere({
            'TYP': 'fix', 'BEZEICHNUNG': 'Frueh', 'KUERZEL': 'F',
            'STARTZEIT': '06:00', 'ENDZEIT': '12:00',
        })
        self.assertEqual(out['STARTZEIT'], '06:00')
        self.assertEqual(out['ENDZEIT'], '12:00')

    def test_leere_strings_werden_none(self):
        out = m._schicht_normalisiere({
            'TYP': 'fix', 'BEZEICHNUNG': '  ', 'KUERZEL': '',
            'STARTZEIT': '06:00', 'ENDZEIT': '12:00',
        })
        self.assertIsNone(out['BEZEICHNUNG'])
        self.assertIsNone(out['KUERZEL'])


class TestSchichtInsertValidierung(unittest.TestCase):
    """P2: Validierung beim Anlegen von Schichten (ohne DB-Zugriff)."""

    def test_unbekannter_typ_wirft(self):
        with self.assertRaises(ValueError):
            m.schicht_insert({
                'TYP': 'xyz', 'BEZEICHNUNG': 'X', 'KUERZEL': 'X',
                'STARTZEIT': '08:00', 'ENDZEIT': '09:00',
            }, benutzer_ma_id=1)

    def test_fix_ohne_zeiten_wirft(self):
        with self.assertRaises(ValueError):
            m.schicht_insert({
                'TYP': 'fix', 'BEZEICHNUNG': 'Frueh', 'KUERZEL': 'F',
                'STARTZEIT': '', 'ENDZEIT': '',
            }, benutzer_ma_id=1)

    def test_fehlende_bezeichnung_wirft(self):
        with self.assertRaises(ValueError):
            m.schicht_insert({
                'TYP': 'aufgabe', 'BEZEICHNUNG': '', 'KUERZEL': 'X',
            }, benutzer_ma_id=1)

    def test_flex_ohne_zeiten_ok(self):
        """flex darf keine Zeiten haben – DB-Aufruf wird gemockt."""
        cur = MagicMock()
        cur.lastrowid = 42
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=cm):
            rec_id = m.schicht_insert({
                'TYP': 'flex', 'BEZEICHNUNG': 'Buchhaltung', 'KUERZEL': 'BH',
            }, benutzer_ma_id=1)
        self.assertEqual(rec_id, 42)


class TestSchichtZuordnungInsertValidierung(unittest.TestCase):
    """P2: Validierung Dauer-Parameter je nach Schichttyp."""

    def test_flex_ohne_dauer_wirft(self):
        with patch.object(m, 'schicht_by_id', return_value={'TYP': 'flex'}):
            with self.assertRaises(ValueError):
                m.schicht_zuordnung_insert(
                    pers_id=1, datum=date(2026, 4, 13),
                    schicht_id=6, kommentar=None, benutzer_ma_id=1,
                    dauer_min=None,
                )

    def test_flex_mit_null_dauer_wirft(self):
        with patch.object(m, 'schicht_by_id', return_value={'TYP': 'flex'}):
            with self.assertRaises(ValueError):
                m.schicht_zuordnung_insert(
                    pers_id=1, datum=date(2026, 4, 13),
                    schicht_id=6, kommentar=None, benutzer_ma_id=1,
                    dauer_min=0,
                )

    def test_fix_mit_dauer_wird_genullt(self):
        """fix darf keine Dauer haben – Zusatzwert wird verworfen."""
        cur = MagicMock()
        cur.lastrowid = 99
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'schicht_by_id', return_value={'TYP': 'fix'}), \
             patch.object(m, 'ist_woche_gesperrt', return_value=False), \
             patch.object(m, 'get_db_rw', return_value=cm):
            m.schicht_zuordnung_insert(
                pers_id=1, datum=date(2026, 4, 13),
                schicht_id=1, kommentar=None, benutzer_ma_id=1,
                dauer_min=120,
            )
        inserted_sql, inserted_params = cur.execute.call_args[0]
        self.assertIn('INSERT', inserted_sql.upper())
        # Params: (pers_id, datum, schicht_id, dauer_min, kommentar, benutzer)
        self.assertIsNone(inserted_params[3])

    def test_aufgabe_dauer_wird_genullt(self):
        cur = MagicMock()
        cur.lastrowid = 77
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'schicht_by_id', return_value={'TYP': 'aufgabe'}), \
             patch.object(m, 'ist_woche_gesperrt', return_value=False), \
             patch.object(m, 'get_db_rw', return_value=cm):
            m.schicht_zuordnung_insert(
                pers_id=1, datum=date(2026, 4, 13),
                schicht_id=8, kommentar=None, benutzer_ma_id=1,
                dauer_min=500,
            )
        _, inserted_params = cur.execute.call_args[0]
        self.assertIsNone(inserted_params[3])


class TestZeigeAlleAusArgsOderSession(unittest.TestCase):
    """Server-seitige Persistenz des 'Nur aktive'-Filters via Flask-Session."""

    def setUp(self):
        import flask
        from modules.orga.personal.routes import _zeige_alle_aus_args_oder_session
        self.helper = _zeige_alle_aus_args_oder_session
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'test'

    def test_url_alle_1_setzt_session_und_gibt_true(self):
        with self.app.test_request_context('/?alle=1'):
            from flask import session
            ergebnis = self.helper('test_key')
            self.assertTrue(ergebnis)
            self.assertTrue(session['test_key'])

    def test_url_alle_0_ueberschreibt_session_auf_false(self):
        with self.app.test_request_context('/?alle=0'):
            from flask import session
            session['test_key'] = True  # alter Zustand
            ergebnis = self.helper('test_key')
            self.assertFalse(ergebnis)
            self.assertFalse(session['test_key'])

    def test_ohne_url_param_gilt_session(self):
        with self.app.test_request_context('/'):
            from flask import session
            session['test_key'] = True
            self.assertTrue(self.helper('test_key'))

    def test_ohne_url_und_ohne_session_ist_false(self):
        with self.app.test_request_context('/'):
            self.assertFalse(self.helper('test_key'))


class TestIsoJahrKw(unittest.TestCase):
    """ISO-Woche-Ableitung fuer den Schichtplan-Freigabe-Workflow."""

    def test_normale_woche(self):
        # 13.04.2026 ist Montag, KW 16
        self.assertEqual(m._iso_jahr_kw(date(2026, 4, 13)), (2026, 16))

    def test_silvester_gehoert_zu_folgejahr(self):
        # 30.12.2024 (Mo) ist ISO-W01 von 2025
        self.assertEqual(m._iso_jahr_kw(date(2024, 12, 30)), (2025, 1))


class TestWocheStatusVirtuell(unittest.TestCase):
    """Kein Eintrag → virtueller 'offen'-Status ohne Metadaten."""

    def test_ohne_eintrag_liefert_offen(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_ro', return_value=cm):
            s = m.woche_status(2026, 16)
        self.assertEqual(s['STATUS'], 'offen')
        self.assertIsNone(s['FREIGEGEBEN_AT'])
        self.assertIsNone(s['FREIGEGEBEN_VON'])
        self.assertEqual(s['JAHR'], 2026)
        self.assertEqual(s['KW'], 16)

    def test_mit_eintrag_liefert_db_zeile(self):
        cur = MagicMock()
        cur.fetchone.return_value = {
            'JAHR': 2026, 'KW': 16, 'STATUS': 'freigegeben',
            'FREIGEGEBEN_AT': datetime(2026, 4, 12, 18, 30),
            'FREIGEGEBEN_VON': 42,
            'FREIGEGEBEN_NAME': 'Max Mustermann',
            'KOMMENTAR': None, 'GEAEND_AT': None, 'GEAEND_VON': 42,
        }
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_ro', return_value=cm):
            s = m.woche_status(2026, 16)
        self.assertEqual(s['STATUS'], 'freigegeben')
        self.assertEqual(s['FREIGEGEBEN_VON'], 42)


class TestIstWocheGesperrt(unittest.TestCase):
    """Gesperrt-Check aus Datum oder aus explizitem (jahr, kw)."""

    def _patch_db(self, row):
        cur = MagicMock()
        cur.fetchone.return_value = row
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        return cm

    def test_aus_datum_gesperrt(self):
        with patch.object(m, 'get_db_ro',
                          return_value=self._patch_db({'1': 1})):
            self.assertTrue(m.ist_woche_gesperrt(date(2026, 4, 13)))

    def test_aus_datum_offen(self):
        with patch.object(m, 'get_db_ro', return_value=self._patch_db(None)):
            self.assertFalse(m.ist_woche_gesperrt(date(2026, 4, 13)))

    def test_jahr_kw_ohne_kw_wirft(self):
        with self.assertRaises(TypeError):
            m.ist_woche_gesperrt(2026)


class TestWocheFreigebenEntsperren(unittest.TestCase):
    """Freigeben/Entsperren: Status-Uebergaenge + Log-Schreiben."""

    def _rw(self, fetchone_row):
        cur = MagicMock()
        cur.fetchone.return_value = fetchone_row
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        return cm, cur

    def test_freigeben_ohne_row_inserts(self):
        cm, cur = self._rw(None)
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.woche_freigeben(2026, 16, benutzer_ma_id=1, kommentar='ok')
        # 1x SELECT FOR UPDATE, 1x INSERT WOCHE, 1x INSERT LOG
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        self.assertTrue(any('FOR UPDATE' in s for s in sqls))
        self.assertTrue(any('INSERT INTO XT_PERSONAL_SCHICHTPLAN_WOCHE'
                            in s and 'LOG' not in s.split('\n')[0]
                            for s in sqls))
        self.assertTrue(any('XT_PERSONAL_SCHICHTPLAN_WOCHE_LOG' in s
                            for s in sqls))

    def test_freigeben_bereits_freigegeben_wirft(self):
        cm, _ = self._rw({'STATUS': 'freigegeben'})
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError):
                m.woche_freigeben(2026, 16, benutzer_ma_id=1)

    def test_entsperren_setzt_auf_offen(self):
        cm, cur = self._rw({'STATUS': 'freigegeben'})
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.woche_entsperren(2026, 16, benutzer_ma_id=1)
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        # UPDATE auf STATUS='offen' und LOG-Eintrag
        self.assertTrue(any("STATUS = 'offen'" in s for s in sqls))
        self.assertTrue(any('XT_PERSONAL_SCHICHTPLAN_WOCHE_LOG' in s
                            for s in sqls))

    def test_entsperren_offene_woche_wirft(self):
        cm, _ = self._rw(None)
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError):
                m.woche_entsperren(2026, 16, benutzer_ma_id=1)


class TestZuordnungGesperrtCheck(unittest.TestCase):
    """Bei freigegebener Woche verweigern insert/delete die Aenderung."""

    def test_insert_gesperrt_wirft(self):
        with patch.object(m, 'schicht_by_id',
                          return_value={'TYP': 'fix'}), \
             patch.object(m, 'ist_woche_gesperrt', return_value=True):
            with self.assertRaises(ValueError) as ctx:
                m.schicht_zuordnung_insert(
                    pers_id=1, datum=date(2026, 4, 13),
                    schicht_id=1, kommentar=None, benutzer_ma_id=1,
                )
            self.assertIn('gesperrt', str(ctx.exception))

    def test_delete_gesperrt_wirft(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'DATUM': date(2026, 4, 13)}
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=cm), \
             patch.object(m, 'ist_woche_gesperrt', return_value=True):
            with self.assertRaises(ValueError):
                m.schicht_zuordnung_delete(42)

    def test_delete_offen_loescht(self):
        cur = MagicMock()
        cur.fetchone.return_value = {'DATUM': date(2026, 4, 13)}
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=cm), \
             patch.object(m, 'ist_woche_gesperrt', return_value=False):
            n = m.schicht_zuordnung_delete(42)
        self.assertEqual(n, 1)
        sqls = [c[0][0] for c in cur.execute.call_args_list]
        self.assertTrue(any('DELETE FROM XT_PERSONAL_SCHICHT_ZUORDNUNG'
                            in s for s in sqls))


class TestSchichtplanKopieren(unittest.TestCase):
    """Kopieren einer Woche in die Zukunft: Konflikt-Check + Warnungen."""

    def _rw(self, fetchone_side, fetchall_side):
        cur = MagicMock()
        cur.fetchone.side_effect = fetchone_side
        cur.fetchall.side_effect = fetchall_side
        cur.lastrowid = 123
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        return cm, cur

    def test_ziel_nicht_montag_wirft(self):
        quelle = date(2026, 4, 13)  # Mo
        ziel = date(2026, 4, 21)    # Di
        with self.assertRaises(ValueError):
            m.schichtplan_kopieren_in_woche(quelle, ziel, 1)

    def test_ziel_nicht_zukunft_wirft(self):
        quelle = date(2026, 4, 13)
        ziel = date(2020, 1, 6)  # Mo, lange vorbei
        with self.assertRaises(ValueError):
            m.schichtplan_kopieren_in_woche(quelle, ziel, 1)

    def test_ziel_gesperrt_wirft(self):
        quelle = date(2099, 1, 5)   # Mo
        ziel = date(2099, 1, 12)    # Mo
        cm, _ = self._rw(
            fetchone_side=[{'STATUS': 'freigegeben'}],
            fetchall_side=[],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.schichtplan_kopieren_in_woche(quelle, ziel, 1)
        self.assertIn('freigegeben', str(ctx.exception))

    def test_ziel_nicht_leer_wirft(self):
        quelle = date(2099, 1, 5)
        ziel = date(2099, 1, 12)
        cm, _ = self._rw(
            fetchone_side=[None, {'n': 3}],  # Status leer, aber 3 Zuordnungen
            fetchall_side=[],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.schichtplan_kopieren_in_woche(quelle, ziel, 1)
        self.assertIn('bereits', str(ctx.exception))

    def test_ziel_quelle_identisch_wirft(self):
        mo = date(2099, 1, 5)
        with self.assertRaises(ValueError):
            m.schichtplan_kopieren_in_woche(mo, mo, 1)

    def test_erfolgreiches_kopieren_mit_urlaub_warnung(self):
        quelle = date(2099, 1, 5)   # Mo
        ziel = date(2099, 1, 12)    # Mo
        # fetchone-Reihenfolge: 1) STATUS-Check (None), 2) n_ziel (0)
        # fetchall-Reihenfolge: 1) quell-Zuordnungen, 2) urlaube, 3) MA-Index
        quell_zuordnungen = [
            {'PERS_ID': 7, 'DATUM': date(2099, 1, 6), 'SCHICHT_ID': 2,
             'DAUER_MIN': None, 'KOMMENTAR': None},
            {'PERS_ID': 8, 'DATUM': date(2099, 1, 7), 'SCHICHT_ID': 2,
             'DAUER_MIN': None, 'KOMMENTAR': None},
        ]
        urlaube = [
            {'PERS_ID': 7, 'VON': date(2099, 1, 13), 'BIS': date(2099, 1, 15),
             'STATUS': 'genehmigt'},
        ]
        ma_index = [
            {'PERS_ID': 7, 'VNAME': 'Anna', 'NAME': 'Klein',
             'EINTRITT': date(2020, 1, 1), 'AUSTRITT': None},
            {'PERS_ID': 8, 'VNAME': 'Ben', 'NAME': 'Gross',
             'EINTRITT': date(2020, 1, 1), 'AUSTRITT': None},
        ]
        cm, cur = self._rw(
            fetchone_side=[None, {'n': 0}],
            fetchall_side=[quell_zuordnungen, urlaube, ma_index],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            ergebnis = m.schichtplan_kopieren_in_woche(quelle, ziel, 1)
        self.assertEqual(ergebnis['kopiert'], 2)
        self.assertEqual(len(ergebnis['warnungen']), 1)
        self.assertIn('Anna', ergebnis['warnungen'][0])
        self.assertIn('Urlaub', ergebnis['warnungen'][0])
        # 2 INSERTs in ZUORDNUNG + 1 LOG-INSERT
        inserts = [c[0][0] for c in cur.execute.call_args_list
                   if 'INSERT' in c[0][0]]
        self.assertEqual(
            sum(1 for s in inserts if 'XT_PERSONAL_SCHICHT_ZUORDNUNG' in s), 2)
        self.assertTrue(any('SCHICHTPLAN_WOCHE_LOG' in s for s in inserts))

    def test_austritt_erzeugt_warnung(self):
        quelle = date(2099, 1, 5)
        ziel = date(2099, 1, 12)
        quell_zuordnungen = [
            {'PERS_ID': 7, 'DATUM': date(2099, 1, 6), 'SCHICHT_ID': 2,
             'DAUER_MIN': None, 'KOMMENTAR': None},
        ]
        ma_index = [
            {'PERS_ID': 7, 'VNAME': 'Anna', 'NAME': 'Klein',
             'EINTRITT': date(2020, 1, 1), 'AUSTRITT': date(2099, 1, 10)},
        ]
        cm, _ = self._rw(
            fetchone_side=[None, {'n': 0}],
            fetchall_side=[quell_zuordnungen, [], ma_index],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            ergebnis = m.schichtplan_kopieren_in_woche(quelle, ziel, 1)
        self.assertEqual(ergebnis['kopiert'], 1)
        self.assertEqual(len(ergebnis['warnungen']), 1)
        self.assertIn('nicht mehr aktiv', ergebnis['warnungen'][0])


class TestVorlageSpeichern(unittest.TestCase):
    """Vorlage-Speichern: Quelle-Zuordnungen → Vorlage-Tabelle, WOCHENTAG-Mapping."""

    def _rw(self, fetchone_side, fetchall_side, lastrowid=42):
        cur = MagicMock()
        cur.fetchone.side_effect = fetchone_side
        cur.fetchall.side_effect = fetchall_side
        cur.lastrowid = lastrowid
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        return cm, cur

    def test_quelle_nicht_montag_wirft(self):
        with self.assertRaises(ValueError):
            m.vorlage_speichern(date(2026, 4, 14), 'Name', 1)

    def test_leerer_name_wirft(self):
        with self.assertRaises(ValueError):
            m.vorlage_speichern(date(2026, 4, 13), '   ', 1)

    def test_leere_woche_wirft(self):
        cm, _ = self._rw(fetchone_side=[], fetchall_side=[[]])
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.vorlage_speichern(date(2026, 4, 13), 'Test', 1)
        self.assertIn('keine Zuordnungen', str(ctx.exception))

    def test_name_doppelt_wirft(self):
        quell = [{'PERS_ID': 1, 'DATUM': date(2026, 4, 13),
                  'SCHICHT_ID': 1, 'DAUER_MIN': None, 'KOMMENTAR': None}]
        cm, _ = self._rw(
            fetchone_side=[{'REC_ID': 9}],  # Name existiert schon
            fetchall_side=[quell],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.vorlage_speichern(date(2026, 4, 13), 'Test', 1)
        self.assertIn('existiert bereits', str(ctx.exception))

    def test_erfolgreich_wochentag_berechnet(self):
        montag = date(2026, 4, 13)  # Mo = 0
        quell = [
            {'PERS_ID': 1, 'DATUM': date(2026, 4, 13),  # Mo
             'SCHICHT_ID': 1, 'DAUER_MIN': None, 'KOMMENTAR': None},
            {'PERS_ID': 2, 'DATUM': date(2026, 4, 16),  # Do
             'SCHICHT_ID': 2, 'DAUER_MIN': 120, 'KOMMENTAR': 'X'},
        ]
        cm, cur = self._rw(
            fetchone_side=[None],  # Name frei
            fetchall_side=[quell],
            lastrowid=77,
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            rec_id = m.vorlage_speichern(montag, 'Standard', 1)
        self.assertEqual(rec_id, 77)
        # Insert-Calls: 1 Header + 2 ZUORDNUNG
        inserts = [c[0] for c in cur.execute.call_args_list
                   if 'INSERT' in c[0][0]]
        self.assertTrue(any('XT_PERSONAL_SCHICHTPLAN_VORLAGE\n' in s[0]
                            or 'VORLAGE\n' in s[0]
                            for s in inserts))
        # Finde die ZUORDNUNG-Inserts und prüfe WOCHENTAG
        zuordnung_inserts = [
            s[1] for s in inserts
            if 'VORLAGE_ZUORDNUNG' in s[0]
        ]
        self.assertEqual(len(zuordnung_inserts), 2)
        wtage = [params[1] for params in zuordnung_inserts]
        self.assertEqual(sorted(wtage), [0, 3])  # Mo + Do


class TestVorlageAnwenden(unittest.TestCase):
    """Vorlage-Anwenden: analog Kopieren, aber mit WOCHENTAG→DATUM-Mapping."""

    def _rw(self, fetchone_side, fetchall_side):
        cur = MagicMock()
        cur.fetchone.side_effect = fetchone_side
        cur.fetchall.side_effect = fetchall_side
        cur.lastrowid = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        return cm, cur

    def test_ziel_nicht_montag_wirft(self):
        with self.assertRaises(ValueError):
            m.vorlage_anwenden(1, date(2099, 1, 6), 1)  # Di

    def test_ziel_nicht_zukunft_wirft(self):
        with self.assertRaises(ValueError):
            m.vorlage_anwenden(1, date(2020, 1, 6), 1)  # Mo aber Vergangenheit

    def test_vorlage_nicht_gefunden_wirft(self):
        cm, _ = self._rw(
            fetchone_side=[None],  # Vorlage fehlt
            fetchall_side=[],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.vorlage_anwenden(99, date(2099, 1, 12), 1)
        self.assertIn('nicht gefunden', str(ctx.exception))

    def test_ziel_gesperrt_wirft(self):
        cm, _ = self._rw(
            fetchone_side=[
                {'REC_ID': 1, 'NAME': 'T'},
                {'STATUS': 'freigegeben'},
            ],
            fetchall_side=[],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.vorlage_anwenden(1, date(2099, 1, 12), 1)
        self.assertIn('freigegeben', str(ctx.exception))

    def test_ziel_nicht_leer_wirft(self):
        cm, _ = self._rw(
            fetchone_side=[
                {'REC_ID': 1, 'NAME': 'T'},
                None,                # Status
                {'n': 5},            # Ziel-KW Anzahl
            ],
            fetchall_side=[],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            with self.assertRaises(ValueError) as ctx:
                m.vorlage_anwenden(1, date(2099, 1, 12), 1)
        self.assertIn('bereits', str(ctx.exception))

    def test_erfolgreich_legt_zuordnungen_an(self):
        ziel = date(2099, 1, 12)  # Mo
        vzs = [
            {'WOCHENTAG': 0, 'PERS_ID': 7, 'SCHICHT_ID': 1,
             'DAUER_MIN': None, 'KOMMENTAR': None},
            {'WOCHENTAG': 4, 'PERS_ID': 8, 'SCHICHT_ID': 2,
             'DAUER_MIN': 180, 'KOMMENTAR': None},
        ]
        ma_index = [
            {'PERS_ID': 7, 'VNAME': 'A', 'NAME': 'K',
             'EINTRITT': date(2020, 1, 1), 'AUSTRITT': None},
            {'PERS_ID': 8, 'VNAME': 'B', 'NAME': 'G',
             'EINTRITT': date(2020, 1, 1), 'AUSTRITT': None},
        ]
        cm, cur = self._rw(
            fetchone_side=[
                {'REC_ID': 1, 'NAME': 'Standard'},
                None,          # Status offen
                {'n': 0},      # Ziel leer
            ],
            fetchall_side=[vzs, [], ma_index],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            ergebnis = m.vorlage_anwenden(1, ziel, 1)
        self.assertEqual(ergebnis['angelegt'], 2)
        self.assertEqual(ergebnis['warnungen'], [])
        # 2 ZUORDNUNG-Inserts + 1 LOG-Insert
        inserts = [c[0] for c in cur.execute.call_args_list
                   if 'INSERT' in c[0][0]]
        zuordnung = [s for s in inserts if 'XT_PERSONAL_SCHICHT_ZUORDNUNG' in s[0]]
        self.assertEqual(len(zuordnung), 2)
        # DATUM = Montag + WOCHENTAG
        datums = [params[1] for _, params in zuordnung]
        self.assertIn(date(2099, 1, 12), datums)  # WOCHENTAG=0
        self.assertIn(date(2099, 1, 16), datums)  # WOCHENTAG=4
        self.assertTrue(any('SCHICHTPLAN_WOCHE_LOG' in s[0] for s in inserts))

    def test_urlaub_erzeugt_warnung(self):
        ziel = date(2099, 1, 12)
        vzs = [{'WOCHENTAG': 2, 'PERS_ID': 7, 'SCHICHT_ID': 1,
                'DAUER_MIN': None, 'KOMMENTAR': None}]
        urlaube = [{'PERS_ID': 7, 'VON': date(2099, 1, 14),
                    'BIS': date(2099, 1, 16), 'STATUS': 'genehmigt'}]
        ma_index = [{'PERS_ID': 7, 'VNAME': 'Anna', 'NAME': 'K',
                     'EINTRITT': date(2020, 1, 1), 'AUSTRITT': None}]
        cm, _ = self._rw(
            fetchone_side=[
                {'REC_ID': 1, 'NAME': 'T'},
                None, {'n': 0},
            ],
            fetchall_side=[vzs, urlaube, ma_index],
        )
        with patch.object(m, 'get_db_rw', return_value=cm):
            ergebnis = m.vorlage_anwenden(1, ziel, 1)
        self.assertEqual(ergebnis['angelegt'], 1)
        self.assertEqual(len(ergebnis['warnungen']), 1)
        self.assertIn('Urlaub', ergebnis['warnungen'][0])


class TestFreigabeBody(unittest.TestCase):
    """Build-Funktion fuer die Schichtplan-Freigabe-Email."""

    def _ma(self):
        return {'VNAME': 'Anna', 'NAME': 'Klein', 'EMAIL': 'a@b.de'}

    def test_leere_woche_zeigt_frei_an_allen_tagen(self):
        montag = date(2099, 1, 5)  # Mo
        text, html = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, []
        )
        # 7x ": frei" in der Listen-Darstellung (nicht 'Freitag' zaehlen)
        self.assertEqual(text.count(': frei'), 7)
        self.assertIn('KW 02/2099', text)
        self.assertIn('Anna', text)

    def test_fix_schicht_formatiert_zeitbereich(self):
        montag = date(2099, 1, 5)
        eintraege = [{
            'DATUM': date(2099, 1, 6),
            'BEZEICHNUNG': 'Frueh',
            'KUERZEL': 'F',
            'TYP': 'fix',
            'STARTZEIT': time(6, 0),
            'ENDZEIT':   time(12, 0),
            'DAUER_MIN': None,
        }]
        text, html = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, eintraege
        )
        self.assertIn('06:00', text)
        self.assertIn('12:00', text)
        self.assertIn('Frueh', text)
        self.assertIn('Dienstag', text)

    def test_flex_schicht_zeigt_dauer(self):
        montag = date(2099, 1, 5)
        eintraege = [{
            'DATUM': date(2099, 1, 7),
            'BEZEICHNUNG': 'Buchhaltung',
            'TYP': 'flex',
            'STARTZEIT': None, 'ENDZEIT': None,
            'DAUER_MIN': 180,
        }]
        text, _ = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, eintraege
        )
        self.assertIn('3:00 h', text)
        self.assertIn('Buchhaltung', text)

    def test_aufgabe_zeigt_label_aufgabe(self):
        montag = date(2099, 1, 5)
        eintraege = [{
            'DATUM': date(2099, 1, 8),
            'BEZEICHNUNG': 'Kassenabschluss',
            'TYP': 'aufgabe',
            'STARTZEIT': None, 'ENDZEIT': None,
            'DAUER_MIN': None,
        }]
        text, _ = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, eintraege
        )
        self.assertIn('Kassenabschluss', text)
        self.assertIn('Aufgabe', text)

    def test_neue_signatur_erscheint_in_text_und_html(self):
        """Neue Signatur: 'Bitte zeitnah pruefen...' + Dorfladen-Gruss."""
        montag = date(2099, 1, 5)
        text, html = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, []
        )
        self.assertIn('Bitte zeitnah', text)
        self.assertIn('Habacher Dorfladen', text)
        self.assertIn('Bitte zeitnah', html)
        self.assertIn('Habacher Dorfladen', html)

    def test_voll_modus_ueberschrift_deine_schichten(self):
        montag = date(2099, 1, 5)
        text, _ = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, []
        )
        self.assertIn('Deine Schichten:', text)

    def test_delta_modus_zeigt_alt_zu_neu(self):
        """aenderungs_tage gesetzt → Aenderungs-Ueberschrift + alt→neu."""
        montag = date(2099, 1, 5)
        aenderungs_tage = [{
            'datum': date(2099, 1, 7),
            'alt': [{'BEZEICHNUNG': 'Frueh', 'TYP': 'fix',
                     'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
                     'DAUER_MIN': None}],
            'neu': [{'BEZEICHNUNG': 'Spaet', 'TYP': 'fix',
                     'STARTZEIT': time(12, 0), 'ENDZEIT': time(18, 0),
                     'DAUER_MIN': None}],
        }]
        text, html = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, eintraege=[],
            aenderungs_tage=aenderungs_tage,
        )
        self.assertIn('Folgende Aenderungen', text)
        self.assertIn('Frueh', text)
        self.assertIn('Spaet', text)
        self.assertIn('→', text)
        self.assertNotIn('Deine Schichten', text)
        self.assertIn('Folgende Aenderungen', html)

    def test_delta_modus_frei_bei_neuem_freien_tag(self):
        """Neu leer → 'frei' im neu-Teil."""
        montag = date(2099, 1, 5)
        aenderungs_tage = [{
            'datum': date(2099, 1, 7),
            'alt': [{'BEZEICHNUNG': 'Frueh', 'TYP': 'fix',
                     'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
                     'DAUER_MIN': None}],
            'neu': [],
        }]
        text, _ = m._freigabe_body_bauen(
            self._ma(), montag, 2099, 2, eintraege=[],
            aenderungs_tage=aenderungs_tage,
        )
        self.assertIn('Frueh', text)
        self.assertIn('frei', text)
        self.assertIn('→', text)


class TestFreigabeEmailsSenden(unittest.TestCase):
    """Orchestrierung: MA-Gruppierung + Versand + Rueckgabe.

    Die Funktion oeffnet mehrere ``get_db_ro()``-Bloecke (Zuordnungen,
    cao_benutzer_email, _snapshot_lesen) und einen ``get_db_rw()``-Block
    (_snapshot_schreiben). Wir patchen die _helper_-Funktionen direkt,
    damit die Tests nicht Reihenfolge-sensitiv gegen den internen SQL-Fluss
    verriegelt sind.
    """

    def _bereite_vor(self, zuordnungen, sender_email=None,
                     snapshot_alt=None, dev_mode=False, sender_shift=None):
        """Patch-Bundle fuer den Orchestrator. Gibt (patches, send_mock) zurueck."""
        # Placeholder – configuration in the test body via contextlib.ExitStack.
        raise NotImplementedError  # fuer Lesbarkeit: siehe Tests unten.

    def test_ohne_ma_keine_mails(self):
        with patch.object(m, '_freigabe_zuordnungen_lesen', return_value=[]), \
             patch.object(m, 'cao_benutzer_email', return_value='p@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden') as send:
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 0)
        send.assert_not_called()

    def test_ma_ohne_email_wird_uebersprungen(self):
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': None,
        }]
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value='p@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden') as send:
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 0)
        self.assertEqual(r['uebersprungen'], 1)
        send.assert_not_called()

    def test_erfolg_zaehlt_gesendet(self):
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        send_ergebnis = {'versendet': 1, 'modus': 'ok',
                         'empfaenger': ['a@b.de']}
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value='planer@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden',
                   return_value=send_ergebnis) as send:
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 1)
        self.assertEqual(r['modus'], 'ok')
        send.assert_called_once()
        # Empfaenger = MA-Email
        self.assertEqual(send.call_args.args[0], 'a@b.de')
        # Reply-To = Absender-Email (kein sender_shift gesetzt)
        self.assertEqual(send.call_args.kwargs.get('reply_to'), 'planer@b.de')
        # from_addr-Override = None → Config-Default
        self.assertIsNone(send.call_args.kwargs.get('from_addr'))

    def test_sender_shift_setzt_from_und_replyto(self):
        """Registry-Key SMTP_SENDER_SHIFT → beide From + Reply-To Override."""
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        send_ergebnis = {'versendet': 1, 'modus': 'ok',
                         'empfaenger': ['a@b.de']}
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value='planer@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False,
                                 'sender_shift': 'shift@b.de'}), \
             patch('common.email.email_senden',
                   return_value=send_ergebnis) as send:
            m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(send.call_args.kwargs.get('from_addr'), 'shift@b.de')
        self.assertEqual(send.call_args.kwargs.get('reply_to'), 'shift@b.de')

    def test_delta_modus_nur_geaenderte_ma(self):
        """Snapshot vorhanden + unveraenderter MA → keine Mail."""
        montag = date(2099, 1, 5)
        # MA 7: unveraendert; MA 8: geaendert (BEZEICHNUNG anders).
        alt = [
            {'PERS_ID': 7, 'DATUM': date(2099, 1, 6), 'SCHICHT_ID': 3,
             'BEZEICHNUNG': 'F', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'DAUER_MIN': None},
            {'PERS_ID': 8, 'DATUM': date(2099, 1, 6), 'SCHICHT_ID': 3,
             'BEZEICHNUNG': 'F', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'DAUER_MIN': None},
        ]
        neu = [
            {'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
             'SCHICHT_ID': 3, 'DAUER_MIN': None,
             'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de'},
            {'REC_ID': 2, 'PERS_ID': 8, 'DATUM': date(2099, 1, 6),
             'SCHICHT_ID': 3, 'DAUER_MIN': None,
             'BEZEICHNUNG': 'Spaet', 'KUERZEL': 'S', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'VNAME': 'B', 'NAME': 'L', 'EMAIL': 'b@b.de'},
        ]
        send_ergebnis = {'versendet': 1, 'modus': 'ok',
                         'empfaenger': ['b@b.de']}
        with patch.object(m, '_freigabe_zuordnungen_lesen', return_value=neu), \
             patch.object(m, 'cao_benutzer_email', return_value='planer@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=alt), \
             patch.object(m, '_snapshot_schreiben') as snapshot_schreiben, \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden',
                   return_value=send_ergebnis) as send:
            r = m.schichtplan_freigabe_emails_senden(montag, 1)
        self.assertEqual(r['gesendet'], 1)
        send.assert_called_once()
        # Nur MA 8 (b@b.de) bekommt Mail.
        self.assertEqual(send.call_args.args[0], 'b@b.de')
        # Betreff hat [Aenderung]-Prefix.
        self.assertIn('[Aenderung]', send.call_args.args[1])
        # Snapshot wird ueberschrieben.
        snapshot_schreiben.assert_called_once()

    def test_delta_modus_ohne_aenderungen_keine_mails(self):
        """Snapshot == Plan → niemand bekommt Mail."""
        montag = date(2099, 1, 5)
        alt = [
            {'PERS_ID': 7, 'DATUM': date(2099, 1, 6), 'SCHICHT_ID': 3,
             'BEZEICHNUNG': 'F', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'DAUER_MIN': None},
        ]
        neu = [
            {'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
             'SCHICHT_ID': 3, 'DAUER_MIN': None,
             'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
             'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
             'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de'},
        ]
        with patch.object(m, '_freigabe_zuordnungen_lesen', return_value=neu), \
             patch.object(m, 'cao_benutzer_email', return_value='planer@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=alt), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden') as send:
            r = m.schichtplan_freigabe_emails_senden(montag, 1)
        self.assertEqual(r['gesendet'], 0)
        send.assert_not_called()

    def test_dev_mode_sendet_an_freigebenden(self):
        """Dev-Modus: Empfaenger = Sender, auch wenn MA Email haette."""
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        send_ergebnis = {'versendet': 1, 'modus': 'ok',
                         'empfaenger': ['planer@b.de']}
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value='planer@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': True, 'sender_shift': ''}), \
             patch('common.email.email_senden',
                   return_value=send_ergebnis) as send:
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 1)
        self.assertEqual(r['modus'], 'dev')
        self.assertEqual(send.call_args.args[0], 'planer@b.de')
        self.assertTrue(send.call_args.args[1].startswith('[DEV]'))

    def test_dev_mode_ohne_sender_email_ist_disabled(self):
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value=None), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': True, 'sender_shift': ''}), \
             patch('common.email.email_senden') as send:
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 0)
        self.assertEqual(r['modus'], 'disabled')
        send.assert_not_called()

    def test_fehler_sammelt_ma_bezeichnung(self):
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        send_ergebnis = {'versendet': 0, 'modus': 'fehler',
                         'empfaenger': ['a@b.de'],
                         'fehler': 'SMTP down'}
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value=None), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben'), \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden', return_value=send_ergebnis):
            r = m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        self.assertEqual(r['gesendet'], 0)
        self.assertEqual(r['modus'], 'fehler')
        self.assertEqual(len(r['fehler']), 1)
        self.assertIn('A K', r['fehler'][0])
        self.assertIn('SMTP down', r['fehler'][0])

    def test_snapshot_wird_geschrieben_nach_freigabe(self):
        """Erstfreigabe (Snapshot leer) → Snapshot wird mit neuen Daten gefuellt."""
        zuordnungen = [{
            'REC_ID': 1, 'PERS_ID': 7, 'DATUM': date(2099, 1, 6),
            'SCHICHT_ID': 3, 'DAUER_MIN': None,
            'BEZEICHNUNG': 'F', 'KUERZEL': 'F', 'TYP': 'fix',
            'STARTZEIT': time(6, 0), 'ENDZEIT': time(12, 0),
            'VNAME': 'A', 'NAME': 'K', 'EMAIL': 'a@b.de',
        }]
        send_ergebnis = {'versendet': 1, 'modus': 'ok',
                         'empfaenger': ['a@b.de']}
        with patch.object(m, '_freigabe_zuordnungen_lesen',
                          return_value=zuordnungen), \
             patch.object(m, 'cao_benutzer_email', return_value='p@b.de'), \
             patch.object(m, '_snapshot_lesen', return_value=[]), \
             patch.object(m, '_snapshot_schreiben') as snap, \
             patch.object(m, 'get_db_ro', return_value=MagicMock()), \
             patch('common.config.load_email_config',
                   return_value={'dev_mode': False, 'sender_shift': ''}), \
             patch('common.email.email_senden', return_value=send_ergebnis):
            m.schichtplan_freigabe_emails_senden(date(2099, 1, 5), 1)
        snap.assert_called_once()
        # Drittes Arg = Zuordnungen-Liste.
        self.assertEqual(snap.call_args.args[2], zuordnungen)


class TestVorlageLoeschen(unittest.TestCase):
    """Vorlage-Loeschen: erst Zuordnungen, dann Header."""

    def test_loescht_zuerst_zuordnungen_dann_header(self):
        cur = MagicMock()
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=cm):
            n = m.vorlage_loeschen(5)
        self.assertEqual(n, 1)
        deletes = [c[0][0] for c in cur.execute.call_args_list
                   if 'DELETE' in c[0][0]]
        self.assertEqual(len(deletes), 2)
        self.assertIn('VORLAGE_ZUORDNUNG', deletes[0])
        self.assertIn('XT_PERSONAL_SCHICHTPLAN_VORLAGE', deletes[1])


class TestAbwesenheitAnlegenValidierung(unittest.TestCase):
    """P4 Abwesenheit: Anlage rejectet ungueltige TYP/Datums-/Stunden-Kombis."""

    def _mock_cursor(self, lastrowid: int = 77):
        cur = MagicMock()
        cur.lastrowid = lastrowid
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm, cur

    def test_ungueltiger_typ_wirft(self):
        with self.assertRaises(ValueError):
            m.abwesenheit_anlegen(
                1, 'urlaub', date(2026, 5, 1), date(2026, 5, 2),
                benutzer_ma_id=2,
            )

    def test_bis_vor_von_wirft(self):
        with self.assertRaises(ValueError):
            m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 3), date(2026, 5, 2),
                benutzer_ma_id=2,
            )

    def test_stundenweise_ohne_stunden_wirft(self):
        with self.assertRaises(ValueError):
            m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 1), date(2026, 5, 1),
                ganztags=False, stunden=None, benutzer_ma_id=2,
            )

    def test_stundenweise_mit_null_stunden_wirft(self):
        with self.assertRaises(ValueError):
            m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 1), date(2026, 5, 1),
                ganztags=False, stunden=0, benutzer_ma_id=2,
            )

    def test_ganztags_nullt_stunden(self):
        """Auch bei ganztags=True UND STUNDEN!=None wird STUNDEN auf None
        gesetzt, damit der DB-State konsistent bleibt."""
        cm, cur = self._mock_cursor(lastrowid=99)
        with patch.object(m, 'get_db_rw', return_value=cm):
            rec_id = m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 1), date(2026, 5, 3),
                ganztags=True, stunden=6.0, benutzer_ma_id=2,
            )
        self.assertEqual(rec_id, 99)
        ins_call = cur.execute.call_args_list[0]
        params = ins_call.args[1]
        # (PERS_ID, TYP, VON, BIS, GANZTAGS, STUNDEN, AU_VORGELEGT, BEMERKUNG, ERSTELLT_VON)
        self.assertEqual(params[4], 1)       # GANZTAGS
        self.assertIsNone(params[5])         # STUNDEN genullt

    def test_schreibt_insert_log(self):
        cm, cur = self._mock_cursor(lastrowid=77)
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_anlegen(
                1, 'schulung', date(2026, 5, 1), date(2026, 5, 1),
                ganztags=False, stunden=4.0, au_vorgelegt=False,
                bemerkung='Kasse neu', benutzer_ma_id=2,
            )
        log_calls = [c for c in cur.execute.call_args_list
                     if 'XT_PERSONAL_ABWESENHEIT_LOG' in c.args[0]]
        self.assertEqual(len(log_calls), 1)


class TestAbwesenheitBearbeiten(unittest.TestCase):
    """Edit-Pfad: Diff-basiert, no-op bei leerer Aenderung,
    sperrt stornierte Eintraege."""

    def _ctx(self, cur):
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm

    _ALT = {
        'REC_ID': 5, 'PERS_ID': 1,
        'TYP': 'krank', 'VON': date(2026, 5, 1), 'BIS': date(2026, 5, 3),
        'GANZTAGS': 1, 'STUNDEN': None,
        'AU_VORGELEGT': 0, 'BEMERKUNG': None, 'STORNIERT': 0,
    }

    def test_nicht_existent_wirft(self):
        with patch.object(m, 'abwesenheit_by_id', return_value=None):
            with self.assertRaises(LookupError):
                m.abwesenheit_bearbeiten(5, {'TYP': 'krank'}, 2)

    def test_storniert_wirft(self):
        alt = {**self._ALT, 'STORNIERT': 1}
        with patch.object(m, 'abwesenheit_by_id', return_value=alt):
            with self.assertRaises(LookupError):
                m.abwesenheit_bearbeiten(5, {'BEMERKUNG': 'x'}, 2)

    def test_leere_aenderung_ist_noop(self):
        cur = MagicMock()
        with patch.object(m, 'abwesenheit_by_id', return_value=dict(self._ALT)), \
             patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            # Nur unbekanntes Feld → nach dem Filter bleibt 'neu' leer.
            n = m.abwesenheit_bearbeiten(5, {'FREMD': 'x'}, 2)
        self.assertEqual(n, 0)
        cur.execute.assert_not_called()

    def test_ungueltiger_typ_wirft(self):
        with patch.object(m, 'abwesenheit_by_id', return_value=dict(self._ALT)):
            with self.assertRaises(ValueError):
                m.abwesenheit_bearbeiten(5, {'TYP': 'urlaub'}, 2)

    def test_bis_vor_von_nach_edit_wirft(self):
        # Nur BIS geaendert, liegt jetzt vor (unveraendertem) VON=05-01
        with patch.object(m, 'abwesenheit_by_id', return_value=dict(self._ALT)):
            with self.assertRaises(ValueError):
                m.abwesenheit_bearbeiten(
                    5, {'BIS': date(2026, 4, 30)}, 2)

    def test_ganztags_setzt_stunden_auf_none(self):
        """Bleibt GANZTAGS=1 und kein STUNDEN-Override: neu behaelt nur die
        expliziten Felder; wird aber stundenweise→ganztags umgeschaltet,
        wird STUNDEN in 'neu' auf None gesetzt."""
        alt = {**self._ALT, 'GANZTAGS': 0, 'STUNDEN': 4.0}
        cur = MagicMock()
        cur.rowcount = 1
        with patch.object(m, 'abwesenheit_by_id', return_value=alt), \
             patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            m.abwesenheit_bearbeiten(5, {'GANZTAGS': 1}, 2)
        upd_sql, upd_params = cur.execute.call_args_list[0].args
        # SET-Reihenfolge entspricht dict-Insertionsreihenfolge:
        # GANZTAGS=?, STUNDEN=?, GEAEND_AT=NOW(), GEAEND_VON=?
        self.assertIn('GANZTAGS = %s', upd_sql)
        self.assertIn('STUNDEN = %s', upd_sql)
        self.assertEqual(upd_params[0], 1)     # GANZTAGS
        self.assertIsNone(upd_params[1])       # STUNDEN auf None genullt

    def test_stundenweise_ohne_stunden_wirft(self):
        alt = dict(self._ALT)  # ganztags=1, stunden=None
        with patch.object(m, 'abwesenheit_by_id', return_value=alt):
            with self.assertRaises(ValueError):
                # Schaltet auf ganztags=0, aber STUNDEN bleibt None
                m.abwesenheit_bearbeiten(5, {'GANZTAGS': 0}, 2)

    def test_update_schreibt_log(self):
        cur = MagicMock()
        cur.rowcount = 1
        with patch.object(m, 'abwesenheit_by_id', return_value=dict(self._ALT)), \
             patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            m.abwesenheit_bearbeiten(5, {'BEMERKUNG': 'neu'}, 2)
        log_calls = [c for c in cur.execute.call_args_list
                     if 'XT_PERSONAL_ABWESENHEIT_LOG' in c.args[0]]
        self.assertEqual(len(log_calls), 1)


class TestAbwesenheitStornieren(unittest.TestCase):
    """Soft-Delete via STORNIERT=1, mit Log-Eintrag. Bereits stornierte: noop."""

    def _ctx(self, cur):
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm

    def test_nicht_existent_wirft(self):
        with patch.object(m, 'abwesenheit_by_id', return_value=None):
            with self.assertRaises(LookupError):
                m.abwesenheit_stornieren(5, 2)

    def test_bereits_storniert_ist_noop(self):
        alt = {'REC_ID': 5, 'PERS_ID': 1, 'STORNIERT': 1}
        cur = MagicMock()
        with patch.object(m, 'abwesenheit_by_id', return_value=alt), \
             patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            n = m.abwesenheit_stornieren(5, 2)
        self.assertEqual(n, 0)
        cur.execute.assert_not_called()

    def test_setzt_storniert_und_schreibt_log(self):
        alt = {'REC_ID': 5, 'PERS_ID': 1, 'STORNIERT': 0}
        cur = MagicMock()
        cur.rowcount = 1
        with patch.object(m, 'abwesenheit_by_id', return_value=alt), \
             patch.object(m, 'get_db_rw', return_value=self._ctx(cur)):
            n = m.abwesenheit_stornieren(5, 2)
        self.assertEqual(n, 1)
        upd_sql = cur.execute.call_args_list[0].args[0]
        self.assertIn('STORNIERT = 1', upd_sql)
        log_calls = [c for c in cur.execute.call_args_list
                     if 'XT_PERSONAL_ABWESENHEIT_LOG' in c.args[0]]
        self.assertEqual(len(log_calls), 1)


class TestAbwesenheitenImZeitraum(unittest.TestCase):
    """Overlap-Filter + optionaler TYP-Filter. Liefert nur STORNIERT=0."""

    def _ctx_with_fetchall(self, rows):
        cur = MagicMock()
        cur.fetchall.return_value = rows
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm, cur

    def test_ungueltiger_typ_wirft(self):
        with self.assertRaises(ValueError):
            m.abwesenheiten_im_zeitraum(
                date(2026, 5, 1), date(2026, 5, 7), typ='urlaub')

    def test_default_ohne_typ(self):
        cm, cur = self._ctx_with_fetchall([])
        with patch.object(m, 'get_db_ro', return_value=cm):
            m.abwesenheiten_im_zeitraum(
                date(2026, 5, 1), date(2026, 5, 7))
        sql, params = cur.execute.call_args.args
        self.assertIn('STORNIERT = 0', sql)
        self.assertIn('a.VON <= %s AND a.BIS >= %s', sql)
        self.assertNotIn('a.TYP = %s', sql)
        self.assertEqual(params, (date(2026, 5, 7), date(2026, 5, 1)))

    def test_mit_typ_filter(self):
        cm, cur = self._ctx_with_fetchall([])
        with patch.object(m, 'get_db_ro', return_value=cm):
            m.abwesenheiten_im_zeitraum(
                date(2026, 5, 1), date(2026, 5, 7), typ='krank')
        sql, params = cur.execute.call_args.args
        self.assertIn('a.TYP = %s', sql)
        self.assertEqual(params,
                         (date(2026, 5, 7), date(2026, 5, 1), 'krank'))


class TestAbwesenheitBezahlt(unittest.TestCase):
    """BEZAHLT-Flag: Default pro TYP, explicit Override via Parameter,
    INSERT/UPDATE setzen das Feld, Bearbeiten akzeptiert Toggle."""

    def _mock_cursor(self, lastrowid: int = 1):
        cur = MagicMock()
        cur.lastrowid = lastrowid
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        return cm, cur

    def test_default_pro_typ(self):
        self.assertEqual(m.abwesenheit_bezahlt_default('krank'),      1)
        self.assertEqual(m.abwesenheit_bezahlt_default('kind_krank'), 1)
        self.assertEqual(m.abwesenheit_bezahlt_default('schulung'),   1)
        self.assertEqual(m.abwesenheit_bezahlt_default('unbezahlt'),  0)
        self.assertEqual(m.abwesenheit_bezahlt_default('sonstiges'),  1)

    def test_anlegen_default_bei_none(self):
        """bezahlt=None → Default aus _BEZAHLT_DEFAULT[typ] (unbezahlt → 0)."""
        cm, cur = self._mock_cursor()
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_anlegen(
                1, 'unbezahlt', date(2026, 5, 1), date(2026, 5, 3),
                benutzer_ma_id=2,
            )
        params = cur.execute.call_args_list[0].args[1]
        # Reihenfolge: (PERS_ID, TYP, VON, BIS, GANZTAGS, STUNDEN,
        #              AU_VORGELEGT, BEZAHLT, BEMERKUNG, ERSTELLT_VON)
        self.assertEqual(params[7], 0)  # BEZAHLT = 0 fuer unbezahlt

    def test_anlegen_default_krank_ist_bezahlt(self):
        cm, cur = self._mock_cursor()
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 1), date(2026, 5, 3),
                benutzer_ma_id=2,
            )
        params = cur.execute.call_args_list[0].args[1]
        self.assertEqual(params[7], 1)  # BEZAHLT = 1 fuer krank

    def test_anlegen_explicit_override(self):
        """bezahlt=False ueberschreibt Default auch bei TYP=krank."""
        cm, cur = self._mock_cursor()
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_anlegen(
                1, 'krank', date(2026, 5, 1), date(2026, 5, 3),
                bezahlt=False, benutzer_ma_id=2,
            )
        params = cur.execute.call_args_list[0].args[1]
        self.assertEqual(params[7], 0)

    def test_bearbeiten_toggle_bezahlt(self):
        """BEZAHLT laesst sich via Edit umschalten, wird als int normalisiert."""
        alt = {
            'REC_ID': 5, 'PERS_ID': 1, 'TYP': 'krank',
            'VON': date(2026, 5, 1), 'BIS': date(2026, 5, 3),
            'GANZTAGS': 1, 'STUNDEN': None,
            'AU_VORGELEGT': 0, 'BEZAHLT': 1, 'BEMERKUNG': None,
            'STORNIERT': 0,
        }
        cur = MagicMock()
        cur.rowcount = 1
        cm = MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = None
        with patch.object(m, 'abwesenheit_by_id', return_value=alt), \
             patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_bearbeiten(5, {'BEZAHLT': False}, 2)
        upd_sql, upd_params = cur.execute.call_args_list[0].args
        self.assertIn('BEZAHLT = %s', upd_sql)
        self.assertEqual(upd_params[0], 0)  # False → 0

    def test_anlegen_schreibt_bezahlt_ins_log(self):
        cm, cur = self._mock_cursor()
        with patch.object(m, 'get_db_rw', return_value=cm):
            m.abwesenheit_anlegen(
                1, 'unbezahlt', date(2026, 5, 1), date(2026, 5, 1),
                benutzer_ma_id=2,
            )
        # FELDER_NEU_JSON ist in _log_schreiben ein Parameter → kommt im
        # INSERT-Aufruf in der LOG-Tabelle vor. Wir pruefen ueber alle
        # execute-calls auf das Log-Statement und dort in den Params
        # nach dem BEZAHLT-Schluessel im JSON.
        log_calls = [c for c in cur.execute.call_args_list
                     if 'XT_PERSONAL_ABWESENHEIT_LOG' in c.args[0]]
        self.assertEqual(len(log_calls), 1)
        log_params = log_calls[0].args[1]
        felder_neu_json = next(p for p in log_params
                               if isinstance(p, str) and 'BEZAHLT' in p)
        self.assertIn('"BEZAHLT": 0', felder_neu_json)


class TestKwOptionen(unittest.TestCase):
    """Die KW-Select-Options fuer den Schichtplan-Datepicker.
    Deckt Vorjahr, aktuelles Jahr und Folgejahr ab und liefert Montage als value."""

    def test_drei_jahre_abgedeckt(self):
        opts = r._kw_optionen(2026)
        jahre = {o['jahr'] for o in opts}
        self.assertEqual(jahre, {2025, 2026, 2027})

    def test_mindestens_52_je_jahr(self):
        opts = r._kw_optionen(2026)
        for jahr in (2025, 2026, 2027):
            count = sum(1 for o in opts if o['jahr'] == jahr)
            self.assertGreaterEqual(count, 52)
            self.assertLessEqual(count, 53)

    def test_value_ist_montag_iso(self):
        opts = r._kw_optionen(2026)
        # ISO KW 1 / 2026 startet am 2025-12-29 (Montag)
        kw1_2026 = next(o for o in opts
                        if o['jahr'] == 2026 and 'KW 01' in o['label'])
        self.assertEqual(kw1_2026['value'], '2025-12-29')

    def test_label_format(self):
        opts = r._kw_optionen(2026)
        o = opts[0]
        self.assertIn('KW', o['label'])
        self.assertIn('/', o['label'])


class TestAbwesenheitSchichtplanMap(unittest.TestCase):
    """Integration: der Schichtplan baut (pers_id, datum)-Index fuer
    ueberlappende Abwesenheiten auf. Wir bilden die Logik ohne DB nach."""

    def test_map_deckt_ueberlappung_in_woche_ab(self):
        montag = date(2026, 5, 4)   # KW 19, Mo
        sonntag = date(2026, 5, 10)
        rows = [
            # PERS 1: Mi–Do krank
            {'PERS_ID': 1, 'TYP': 'krank',
             'VON': date(2026, 5, 6), 'BIS': date(2026, 5, 7)},
            # PERS 2: Fr schulung
            {'PERS_ID': 2, 'TYP': 'schulung',
             'VON': date(2026, 5, 8), 'BIS': date(2026, 5, 8)},
            # PERS 3: Ueberlappt Vorwoche bis Mo
            {'PERS_ID': 3, 'TYP': 'sonstiges',
             'VON': date(2026, 4, 30), 'BIS': date(2026, 5, 4)},
        ]

        # Gleiche Logik wie in routes.schichtplan()
        abwesenheit_map = {}
        for a in rows:
            for i in range(7):
                d = montag + timedelta(days=i)
                if a['VON'] <= d <= a['BIS']:
                    abwesenheit_map.setdefault((a['PERS_ID'], d), a['TYP'])

        self.assertEqual(abwesenheit_map[(1, date(2026, 5, 6))], 'krank')
        self.assertEqual(abwesenheit_map[(1, date(2026, 5, 7))], 'krank')
        self.assertNotIn((1, date(2026, 5, 5)), abwesenheit_map)
        self.assertEqual(abwesenheit_map[(2, date(2026, 5, 8))], 'schulung')
        self.assertEqual(abwesenheit_map[(3, date(2026, 5, 4))], 'sonstiges')
        # Nicht in der Woche → darf nicht drin sein
        self.assertNotIn((3, date(2026, 5, 5)), abwesenheit_map)
        # Sonntag-Rand: niemand krank
        self.assertNotIn((1, sonntag), abwesenheit_map)


class TestFeiertageImZeitraum(unittest.TestCase):
    """feiertage_im_zeitraum ist tolerant gegen DB-Fehler und liefert
    {datum: name} mit 'manuell gewinnt'-Semantik pro Tag."""

    def _db_mock(self, rows: list[dict]):
        cur = MagicMock()
        cur.fetchall.return_value = rows
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return ctx

    def test_leerer_zeitraum_ohne_db(self):
        # bis < von: kein DB-Zugriff noetig
        self.assertEqual(
            m.feiertage_im_zeitraum(date(2026, 5, 10), date(2026, 5, 1)),
            {},
        )

    def test_liefert_dict_datum_zu_name(self):
        rows = [
            {'DATUM': date(2026, 4, 6), 'NAME': 'Ostermontag', 'QUELLE': 'paket'},
            {'DATUM': date(2026, 5, 1), 'NAME': 'Tag der Arbeit', 'QUELLE': 'paket'},
        ]
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro', return_value=self._db_mock(rows)):
            aus = m.feiertage_im_zeitraum(date(2026, 4, 1), date(2026, 5, 31))
        self.assertEqual(aus[date(2026, 4, 6)], 'Ostermontag')
        self.assertEqual(aus[date(2026, 5, 1)], 'Tag der Arbeit')

    def test_manuell_schlaegt_paket(self):
        # Zwei Eintraege am gleichen Tag: die SQL sortiert manuell zuerst,
        # und die Funktion uebernimmt den ersten pro Datum.
        rows = [
            {'DATUM': date(2026, 7, 15), 'NAME': 'Betriebsferien', 'QUELLE': 'manuell'},
            {'DATUM': date(2026, 7, 15), 'NAME': 'irgendwas',      'QUELLE': 'paket'},
        ]
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro', return_value=self._db_mock(rows)):
            aus = m.feiertage_im_zeitraum(date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(aus[date(2026, 7, 15)], 'Betriebsferien')

    def test_db_fehler_liefert_leeres_dict(self):
        # Simuliert fehlenden Pool / nicht migrierte Tabelle
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro', side_effect=RuntimeError('no pool')):
            aus = m.feiertage_im_zeitraum(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(aus, {})


class TestIstFeiertag(unittest.TestCase):
    """ist_feiertag liefert (True, name) oder (False, None). Fehler
    degradieren zu (False, None) – der Aufrufer sieht keinen Crash."""

    def _cur(self, row):
        cur = MagicMock()
        cur.fetchone.return_value = row
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return ctx

    def test_treffer(self):
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro',
                          return_value=self._cur({'NAME': 'Ostermontag'})):
            ok, name = m.ist_feiertag(date(2026, 4, 6))
        self.assertTrue(ok)
        self.assertEqual(name, 'Ostermontag')

    def test_kein_treffer(self):
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro', return_value=self._cur(None)):
            ok, name = m.ist_feiertag(date(2026, 4, 8))
        self.assertFalse(ok)
        self.assertIsNone(name)

    def test_db_fehler(self):
        with patch.object(m, 'aktuelles_bundesland', return_value='BY'), \
             patch.object(m, 'get_db_ro', side_effect=RuntimeError('nope')):
            ok, name = m.ist_feiertag(date(2026, 4, 6))
        self.assertFalse(ok)
        self.assertIsNone(name)


class TestUrlaubArbeitstageDetail(unittest.TestCase):
    """urlaub_arbeitstage[_detail] muss Feiertage vom Urlaubsverbrauch
    abziehen und sie fuer die UI zaehlen/benennen."""

    def test_keine_feiertage(self):
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell), \
             patch.object(m, 'feiertage_im_zeitraum', return_value={}):
            det = m.urlaub_arbeitstage_detail(
                1, date(2026, 4, 13), date(2026, 4, 19))
        self.assertEqual(det['arbeitstage'], 5.0)
        self.assertEqual(det['feiertage'], 0)
        self.assertEqual(det['feiertag_namen'], [])
        self.assertEqual(det['kalendertage'], 7)

    def test_feiertag_am_arbeitstag_wird_abgezogen(self):
        # Mo–Fr Modell, Ostermontag 2026-04-06 ist Montag → zaehlt nicht als Urlaub
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        ft = {date(2026, 4, 6): 'Ostermontag'}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell), \
             patch.object(m, 'feiertage_im_zeitraum', return_value=ft):
            det = m.urlaub_arbeitstage_detail(
                1, date(2026, 4, 6), date(2026, 4, 10))
        # Mo Feiertag, Di–Fr = 4 Arbeitstage angerechnet
        self.assertEqual(det['arbeitstage'], 4.0)
        self.assertEqual(det['feiertage'], 1)
        self.assertEqual(det['feiertag_namen'], ['Ostermontag'])

    def test_feiertag_am_sonntag_wirkt_nicht(self):
        # Sonntag ist ohnehin kein Arbeitstag in Mo-Fr-Modell
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        # Fiktiver Feiertag am Sonntag
        ft = {date(2026, 4, 12): 'Irgendwas am Sonntag'}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell), \
             patch.object(m, 'feiertage_im_zeitraum', return_value=ft):
            det = m.urlaub_arbeitstage_detail(
                1, date(2026, 4, 6), date(2026, 4, 12))
        # Mo–Fr = 5 Arbeitstage, Feiertag am So zieht nichts ab
        self.assertEqual(det['arbeitstage'], 5.0)
        self.assertEqual(det['feiertage'], 0)

    def test_legacy_funktion_liefert_netto(self):
        # urlaub_arbeitstage delegiert an _detail und gibt nur 'arbeitstage'
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        ft = {date(2026, 4, 6): 'Ostermontag'}
        with patch.object(m, 'aktuelles_az_modell', return_value=modell), \
             patch.object(m, 'feiertage_im_zeitraum', return_value=ft):
            self.assertEqual(
                m.urlaub_arbeitstage(1, date(2026, 4, 6), date(2026, 4, 10)),
                4.0,
            )

    def test_mehrere_feiertage(self):
        modell = {'STD_MO': 8, 'STD_DI': 8, 'STD_MI': 8, 'STD_DO': 8,
                  'STD_FR': 8, 'STD_SA': None, 'STD_SO': None}
        # Karfreitag 2026-04-03, Ostermontag 2026-04-06
        ft = {
            date(2026, 4, 3): 'Karfreitag',
            date(2026, 4, 6): 'Ostermontag',
        }
        with patch.object(m, 'aktuelles_az_modell', return_value=modell), \
             patch.object(m, 'feiertage_im_zeitraum', return_value=ft):
            det = m.urlaub_arbeitstage_detail(
                1, date(2026, 3, 30), date(2026, 4, 10))
        # Mo-Fr 30.3..3.4 + Mo-Fr 6.4..10.4 = 10 Arbeitstage,
        # minus 2 Feiertage (Karfreitag 3.4, Ostermontag 6.4) → 8 angerechnet
        self.assertEqual(det['arbeitstage'], 8.0)
        self.assertEqual(det['feiertage'], 2)
        self.assertIn('Karfreitag', det['feiertag_namen'])
        self.assertIn('Ostermontag', det['feiertag_namen'])


class TestAktuellesBundesland(unittest.TestCase):
    """aktuelles_bundesland liest XT_EINSTELLUNGEN und validiert den Code."""

    def _cur(self, row):
        cur = MagicMock()
        cur.fetchone.return_value = row
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        return ctx

    def test_bundesland_aus_db(self):
        with patch.object(m, 'get_db_ro',
                          return_value=self._cur({'wert': 'BW'})):
            self.assertEqual(m.aktuelles_bundesland(), 'BW')

    def test_normalisiert_zu_upper(self):
        with patch.object(m, 'get_db_ro',
                          return_value=self._cur({'wert': 'by'})):
            self.assertEqual(m.aktuelles_bundesland(), 'BY')

    def test_unbekannter_code_faellt_auf_by_zurueck(self):
        with patch.object(m, 'get_db_ro',
                          return_value=self._cur({'wert': 'ZZ'})):
            self.assertEqual(m.aktuelles_bundesland(), 'BY')

    def test_kein_eintrag_default_by(self):
        with patch.object(m, 'get_db_ro',
                          return_value=self._cur(None)):
            self.assertEqual(m.aktuelles_bundesland(), 'BY')

    def test_db_fehler_default_by(self):
        with patch.object(m, 'get_db_ro', side_effect=RuntimeError('no pool')):
            self.assertEqual(m.aktuelles_bundesland(), 'BY')


# ── P3: Stempeluhr ────────────────────────────────────────────────────────────

def _ro_cur(row=None, rows=None):
    """Read-only Cursor-Mock: fetchone/fetchall liefern die vorgegebenen Werte."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    return ctx, cur


def _rw_cur(lastrowid: int = 1, rowcount: int = 1, fetchone_values=None):
    """Write-Cursor-Mock: simuliert INSERT/UPDATE/DELETE."""
    cur = MagicMock()
    cur.lastrowid = lastrowid
    cur.rowcount = rowcount
    if fetchone_values is not None:
        cur.fetchone.side_effect = list(fetchone_values)
    ctx = MagicMock()
    ctx.__enter__.return_value = cur
    ctx.__exit__.return_value = False
    return ctx, cur


class TestStempelNaechsteRichtung(unittest.TestCase):
    """'last event wins': robust gegen Mitternacht und vergessene Stempel."""

    def test_kein_vorheriger_stempel_startet_mit_kommen(self):
        ctx, _ = _ro_cur(row=None)
        with patch.object(m, 'get_db_ro', return_value=ctx):
            self.assertEqual(m.stempel_naechste_richtung(42), 'kommen')

    def test_nach_kommen_kommt_gehen(self):
        ctx, _ = _ro_cur(row={'RICHTUNG': 'kommen'})
        with patch.object(m, 'get_db_ro', return_value=ctx):
            self.assertEqual(m.stempel_naechste_richtung(42), 'gehen')

    def test_nach_gehen_kommt_kommen(self):
        ctx, _ = _ro_cur(row={'RICHTUNG': 'gehen'})
        with patch.object(m, 'get_db_ro', return_value=ctx):
            self.assertEqual(m.stempel_naechste_richtung(42), 'kommen')


class TestStempelnKarte(unittest.TestCase):
    """Flow: GUID → MITARBEITER → XT_PERSONAL_MA → INSERT stempel."""

    def test_leere_guid_liefert_fehler(self):
        r2 = m.stempeln_karte('', terminal_nr=3)
        self.assertFalse(r2['ok'])
        self.assertIn('Barcode', r2['msg'])

    def test_unbekannte_karte_liefert_fehler(self):
        with patch('common.auth.mitarbeiter_login_karte', return_value=None):
            r2 = m.stempeln_karte('ABC123', terminal_nr=3)
        self.assertFalse(r2['ok'])
        self.assertIn('Karte nicht erkannt', r2['msg'])

    def test_karte_ohne_personal_datensatz(self):
        with patch('common.auth.mitarbeiter_login_karte',
                   return_value={'MA_ID': 99, 'VNAME': 'x', 'NAME': 'y',
                                 'LOGIN_NAME': 'x'}), \
             patch.object(m, '_ma_by_cao_ma_id', return_value=None):
            r2 = m.stempeln_karte('ABC', terminal_nr=3)
        self.assertFalse(r2['ok'])
        self.assertIn('Personaldatensatz', r2['msg'])

    def test_ausgetretener_ma_wird_abgelehnt(self):
        gestern = date.today() - timedelta(days=1)
        personal = {'PERS_ID': 5, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                    'KUERZEL': 'ALB', 'AUSTRITT': gestern}
        with patch('common.auth.mitarbeiter_login_karte',
                   return_value={'MA_ID': 99, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                                 'LOGIN_NAME': 'aa'}), \
             patch.object(m, '_ma_by_cao_ma_id', return_value=personal):
            r2 = m.stempeln_karte('ABC', terminal_nr=3)
        self.assertFalse(r2['ok'])
        self.assertIn('ausgetreten', r2['msg'])

    def test_erfolgreicher_stempel_kommen(self):
        personal = {'PERS_ID': 5, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                    'KUERZEL': 'ALB', 'AUSTRITT': None}
        ctx, cur = _rw_cur(lastrowid=101)
        with patch('common.auth.mitarbeiter_login_karte',
                   return_value={'MA_ID': 99, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                                 'LOGIN_NAME': 'aa'}), \
             patch.object(m, '_ma_by_cao_ma_id', return_value=personal), \
             patch.object(m, 'stempel_naechste_richtung', return_value='kommen'), \
             patch.object(m, 'get_db_rw', return_value=ctx):
            r2 = m.stempeln_karte('ABC', terminal_nr=3)
        self.assertTrue(r2['ok'])
        self.assertEqual(r2['richtung'], 'kommen')
        self.assertEqual(r2['pers_id'], 5)
        self.assertEqual(r2['vname'], 'Anna')
        self.assertIn('Willkommen', r2['msg'])
        # Es wurde genau ein INSERT ausgefuehrt.
        insert_calls = [c for c in cur.execute.call_args_list
                        if 'INSERT INTO XT_PERSONAL_STEMPEL' in c.args[0]]
        self.assertEqual(len(insert_calls), 1)
        # Terminal-Nr und QUELLE korrekt im Parameter-Tuple.
        params = insert_calls[0].args[1]
        self.assertEqual(params[0], 5)           # PERS_ID
        self.assertEqual(params[1], 'kommen')    # RICHTUNG
        self.assertEqual(params[3], 3)           # TERMINAL_NR

    def test_erfolgreicher_stempel_gehen(self):
        personal = {'PERS_ID': 5, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                    'KUERZEL': 'ALB', 'AUSTRITT': None}
        ctx, _ = _rw_cur(lastrowid=102)
        with patch('common.auth.mitarbeiter_login_karte',
                   return_value={'MA_ID': 99, 'VNAME': 'Anna', 'NAME': 'Albrecht',
                                 'LOGIN_NAME': 'aa'}), \
             patch.object(m, '_ma_by_cao_ma_id', return_value=personal), \
             patch.object(m, 'stempel_naechste_richtung', return_value='gehen'), \
             patch.object(m, 'get_db_rw', return_value=ctx):
            r2 = m.stempeln_karte('ABC', terminal_nr=None)
        self.assertTrue(r2['ok'])
        self.assertEqual(r2['richtung'], 'gehen')
        self.assertIn('Tschuess', r2['msg'])


class TestStempelPaareUndDauer(unittest.TestCase):
    """Paare kommen/gehen, Gesamtdauer ueber den Tag."""

    def _stempel(self, items):
        """items: list of (richtung, 'HH:MM') → dict list."""
        d = date(2026, 4, 18)
        return [
            {'REC_ID': i, 'RICHTUNG': r, 'ZEITPUNKT': datetime.combine(
                d, time.fromisoformat(t)), 'QUELLE': 'kiosk',
             'TERMINAL_NR': 1, 'KOMMENTAR': None}
            for i, (r, t) in enumerate(items, start=1)
        ]

    def test_einzelnes_paar(self):
        stempel = self._stempel([('kommen', '08:00'), ('gehen', '12:30')])
        paare = m._stempel_paare_tag(stempel)
        self.assertEqual(len(paare), 1)
        self.assertEqual((paare[0][1] - paare[0][0]).total_seconds() / 60, 270)

    def test_zwei_paare(self):
        stempel = self._stempel([
            ('kommen', '08:00'), ('gehen',  '12:00'),
            ('kommen', '13:00'), ('gehen',  '16:30'),
        ])
        paare = m._stempel_paare_tag(stempel)
        self.assertEqual(len(paare), 2)

    def test_unvollstaendig_wird_ignoriert(self):
        """Kommen ohne zugehoeriges Gehen darf die Zaehlung nicht stoeren."""
        stempel = self._stempel([
            ('kommen', '08:00'), ('gehen',  '12:00'),
            ('kommen', '13:00'),  # kein 'gehen' gefolgt
        ])
        paare = m._stempel_paare_tag(stempel)
        self.assertEqual(len(paare), 1)

    def test_doppel_kommen_ignoriert_zweites(self):
        """Bei 'kommen' nach 'kommen' bleibt das erste offen – simuliert
        vergessenes Ausstempeln. Das zweite 'kommen' ueberschreibt den
        Start, sodass nachtraegliche Korrekturen moeglich bleiben."""
        stempel = self._stempel([
            ('kommen', '08:00'),
            ('kommen', '13:00'),
            ('gehen',  '16:00'),
        ])
        paare = m._stempel_paare_tag(stempel)
        self.assertEqual(len(paare), 1)
        # Zweites 'kommen' (13:00) ueberschreibt das erste → 3h Arbeit.
        self.assertEqual((paare[0][1] - paare[0][0]).total_seconds() / 60, 180)

    def test_arbeitsdauer_min_summe(self):
        stempel = self._stempel([
            ('kommen', '08:00'), ('gehen',  '12:00'),  # 4h
            ('kommen', '13:00'), ('gehen',  '16:30'),  # 3,5h
        ])
        with patch.object(m, 'stempel_ma_zeitraum', return_value=stempel):
            self.assertEqual(
                m.stempel_arbeitsdauer_min(1, date(2026, 4, 18)),
                7 * 60 + 30,
            )


class TestStempelKorrekturen(unittest.TestCase):
    """Admin-Pfade: INSERT / UPDATE / DELETE mit Pflicht-Grund + Log-Eintrag."""

    def test_insert_ohne_grund_wirft(self):
        with self.assertRaises(ValueError):
            m.stempel_korrektur_insert(
                1, 'kommen', datetime(2026, 4, 18, 8), '', 42,
            )

    def test_insert_ungueltige_richtung_wirft(self):
        with self.assertRaises(ValueError):
            m.stempel_korrektur_insert(
                1, 'pause', datetime(2026, 4, 18, 8), 'x', 42,
            )

    def test_insert_schreibt_stempel_und_log(self):
        ctx, cur = _rw_cur(lastrowid=55)
        with patch.object(m, 'get_db_rw', return_value=ctx):
            rec_id = m.stempel_korrektur_insert(
                1, 'kommen', datetime(2026, 4, 18, 8, 0),
                'Karte vergessen', 42, kommentar='Abstimmung',
            )
        self.assertEqual(rec_id, 55)
        # Erst INSERT in STEMPEL, dann INSERT in KORREKTUR.
        self.assertEqual(len(cur.execute.call_args_list), 2)
        self.assertIn('INSERT INTO XT_PERSONAL_STEMPEL',
                      cur.execute.call_args_list[0].args[0])
        self.assertIn('INSERT INTO XT_PERSONAL_STEMPEL_KORREKTUR',
                      cur.execute.call_args_list[1].args[0])
        # Log-Parameter enthalten PERS_ID, REF=55, OPERATION='INSERT',
        # JSON-Bloecke (alt=None, neu mit ZEITPUNKT als ISO).
        log_params = cur.execute.call_args_list[1].args[1]
        self.assertEqual(log_params[0], 1)   # PERS_ID
        self.assertEqual(log_params[1], 55)  # REF_REC_ID
        self.assertEqual(log_params[2], 'INSERT')
        self.assertIsNone(log_params[3])     # FELDER_ALT_JSON
        neu_json = json.loads(log_params[4])
        self.assertEqual(neu_json['RICHTUNG'], 'kommen')
        self.assertIn('2026-04-18', neu_json['ZEITPUNKT'])

    def test_update_nicht_existent_liefert_null(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=ctx):
            n = m.stempel_korrektur_update(
                99, 'kommen', datetime(2026, 4, 18, 8), 'x', 42,
            )
        self.assertEqual(n, 0)

    def test_update_schreibt_update_und_log(self):
        """Alt-Zustand wird gelesen, UPDATE + Log erzeugt."""
        alt = {'PERS_ID': 1, 'RICHTUNG': 'gehen',
               'ZEITPUNKT': datetime(2026, 4, 18, 17, 5)}
        cur = MagicMock()
        cur.fetchone.return_value = alt
        cur.rowcount = 1
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=ctx):
            n = m.stempel_korrektur_update(
                77, 'gehen', datetime(2026, 4, 18, 16, 30),
                'Zeit korrigiert', 42,
            )
        self.assertEqual(n, 1)
        # 3 Execs: SELECT + UPDATE + LOG-INSERT
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any('SELECT' in s for s in sqls))
        self.assertTrue(any('UPDATE XT_PERSONAL_STEMPEL' in s for s in sqls))
        self.assertTrue(any('XT_PERSONAL_STEMPEL_KORREKTUR' in s for s in sqls))

    def test_delete_schreibt_delete_und_log(self):
        alt = {'PERS_ID': 1, 'RICHTUNG': 'kommen',
               'ZEITPUNKT': datetime(2026, 4, 18, 8), 'QUELLE': 'kiosk'}
        cur = MagicMock()
        cur.fetchone.return_value = alt
        ctx = MagicMock()
        ctx.__enter__.return_value = cur
        ctx.__exit__.return_value = False
        with patch.object(m, 'get_db_rw', return_value=ctx):
            n = m.stempel_korrektur_delete(77, 'Fehl-Scan', 42)
        self.assertEqual(n, 1)
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        self.assertTrue(any('DELETE FROM XT_PERSONAL_STEMPEL' in s for s in sqls))
        self.assertTrue(any('XT_PERSONAL_STEMPEL_KORREKTUR' in s for s in sqls))

    def test_delete_ohne_grund_wirft(self):
        with self.assertRaises(ValueError):
            m.stempel_korrektur_delete(77, '', 42)


if __name__ == '__main__':
    unittest.main()
