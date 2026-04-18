"""
Unit-Tests fuer modules/wawi/personal/models.py und tools/import_csv.py.

Kein DB-Zugriff – DB-abhaengige Funktionen werden gemockt.
"""
import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from modules.wawi.personal import models as m
from modules.wawi.personal.tools import import_csv as ic


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
        with patch('modules.wawi.personal.models.get_db_rw',
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
        with patch('modules.wawi.personal.models.get_db_rw',
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
        cur.fetchone.return_value = ({'STATUS': aktuell_status}
                                     if aktuell_status else None)
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


class TestKorrekturGrund(unittest.TestCase):

    def test_leerer_grund_wirft(self):
        with self.assertRaises(ValueError):
            m.urlaub_korrektur_anlegen(1, 2026, 3.0, '', None, 2)
        with self.assertRaises(ValueError):
            m.urlaub_korrektur_anlegen(1, 2026, 3.0, '   ', None, 2)


if __name__ == '__main__':
    unittest.main()
