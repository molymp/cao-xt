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


class TestJsonDefault(unittest.TestCase):

    def test_date_wird_serialisiert(self):
        s = json.dumps({'d': date(2026, 1, 1)}, default=m._json_default)
        self.assertIn('2026-01-01', s)

    def test_unbekannter_typ_wirft(self):
        with self.assertRaises(TypeError):
            json.dumps({'x': object()}, default=m._json_default)


if __name__ == '__main__':
    unittest.main()
