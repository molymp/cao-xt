"""
Unit-Tests fuer admin-app/app/stammdaten_land.py.

DB wird gestubbt. Geprueft werden:
- Schema-Introspektion (nur Pflichtspalten vorhanden vs. alle Spalten)
- MwSt-Aufbereitung (None vs. 0.0)
- EU-Flag Y/N → Bool
- Trimmen
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_land.py')


class _FakeCursor:

    def __init__(self, schema_spalten, daten_rows):
        self._schema = [{'COLUMN_NAME': s} for s in schema_spalten]
        self._daten = daten_rows
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        if 'INFORMATION_SCHEMA' in sql.upper():
            self._naechste = self._schema
        else:
            self._naechste = self._daten

    def fetchall(self):
        return self._naechste

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade_modul(cursor):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: cursor
    sys.modules['db'] = fake_db
    sys.modules.pop('sland_test', None)
    spec = importlib.util.spec_from_file_location('sland_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ALLE = ['ID', 'NAME', 'NAME2', 'ISO_CODE_3', 'VORWAHL', 'WAEHRUNG',
        'SPRACHE', 'POST_CODE', 'EU_LAND', 'FORMAT',
        'MWST_1', 'MWST_2', 'MWST_3', 'ERLOESKONTO']


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(_ALLE, []))
        self.assertEqual(mod.liste(), [])

    def test_minimales_schema(self):
        """Nur ID + NAME vorhanden – Rest bleibt leer."""
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME'],
            [{'ID': 'DE', 'NAME': 'Deutschland'}],
        ))
        res = mod.liste()
        self.assertEqual(res[0]['id'], 'DE')
        self.assertEqual(res[0]['name'], 'Deutschland')
        self.assertEqual(res[0]['mwst'], [None, None, None])
        self.assertFalse(res[0]['eu_land'])
        self.assertEqual(res[0]['iso3'], '')
        self.assertIsNone(res[0]['erloeskonto'])

    def test_volles_schema_deutschland(self):
        mod = _lade_modul(_FakeCursor(_ALLE, [{
            'ID': 'DE', 'NAME': 'Deutschland', 'NAME2': 'Germany',
            'ISO_CODE_3': 'DEU', 'VORWAHL': '+49', 'WAEHRUNG': 'EUR',
            'SPRACHE': 'DE', 'POST_CODE': '#####', 'EU_LAND': 'Y',
            'FORMAT': 1,
            'MWST_1': 19.0, 'MWST_2': 7.0, 'MWST_3': 0.0,
            'ERLOESKONTO': 8400,
        }]))
        e = mod.liste()[0]
        self.assertEqual(e['iso3'], 'DEU')
        self.assertTrue(e['eu_land'])
        self.assertEqual(e['mwst'], [19.0, 7.0, 0.0])
        self.assertEqual(e['erloeskonto'], 8400)
        self.assertEqual(e['waehrung'], 'EUR')

    def test_mwst_none_bleibt_none(self):
        """NULL in MwSt-Spalte != 0.0 (unterscheiden 'nicht gepflegt'
        vs. 'explicit 0')."""
        mod = _lade_modul(_FakeCursor(_ALLE, [{
            'ID': 'CH', 'NAME': 'Schweiz', 'NAME2': '', 'ISO_CODE_3': 'CHE',
            'VORWAHL': '+41', 'WAEHRUNG': 'CHF', 'SPRACHE': 'DE',
            'POST_CODE': '####', 'EU_LAND': 'N', 'FORMAT': 1,
            'MWST_1': None, 'MWST_2': None, 'MWST_3': None,
            'ERLOESKONTO': None,
        }]))
        e = mod.liste()[0]
        self.assertEqual(e['mwst'], [None, None, None])
        self.assertIsNone(e['erloeskonto'])
        self.assertFalse(e['eu_land'])

    def test_eu_flag_verschiedene_werte(self):
        mod = _lade_modul(_FakeCursor(['ID', 'NAME', 'EU_LAND'], [
            {'ID': 'FR', 'NAME': 'Frankreich', 'EU_LAND': 'Y'},
            {'ID': 'CH', 'NAME': 'Schweiz',    'EU_LAND': 'N'},
            {'ID': 'NO', 'NAME': 'Norwegen',   'EU_LAND': None},
            {'ID': 'XX', 'NAME': 'X',          'EU_LAND': 'y'},  # klein
        ]))
        res = mod.liste()
        # sortiert nach NAME: Frankreich, Norwegen, Schweiz, X
        self.assertTrue(res[0]['eu_land'])   # Frankreich
        self.assertFalse(res[1]['eu_land'])  # Norwegen
        self.assertFalse(res[2]['eu_land'])  # Schweiz
        self.assertTrue(res[3]['eu_land'])   # X ('y' klein)

    def test_name_wird_getrimmt(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'WAEHRUNG'],
            [{'ID': '  AT ', 'NAME': ' Oesterreich ', 'WAEHRUNG': ' EUR '}],
        ))
        e = mod.liste()[0]
        self.assertEqual(e['id'], 'AT')
        self.assertEqual(e['name'], 'Oesterreich')
        self.assertEqual(e['waehrung'], 'EUR')

    def test_format_string_wird_int(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'FORMAT'],
            [{'ID': 'DE', 'NAME': 'D', 'FORMAT': '3'}],
        ))
        self.assertEqual(mod.liste()[0]['format'], 3)

    def test_format_fehlerhaft_wird_none(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'FORMAT'],
            [{'ID': 'DE', 'NAME': 'D', 'FORMAT': 'xxx'}],
        ))
        self.assertIsNone(mod.liste()[0]['format'])


if __name__ == '__main__':
    unittest.main()
