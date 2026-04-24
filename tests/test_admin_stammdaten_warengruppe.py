"""
Unit-Tests fuer admin-app/app/stammdaten_warengruppe.py.

Tests decken ab:
- Leere Tabelle
- Baum via TOP_ID (-1/0 -> Wurzel)
- Kinder-Zaehlung
- Y/N-Flag DURCHSUCHEN
- Kalk-Faktoren als Liste + hat_kalk-Flag
- DEF_EKTO/DEF_AKTO: -1 -> None
- STEUER_CODE -> Label-Map
- BESCHREIBUNG als Bytes wird dekodiert
- WGR_RABATT als Float
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_warengruppe.py')


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
    sys.modules.pop('swg_test', None)
    spec = importlib.util.spec_from_file_location('swg_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(['ID', 'NAME'], []))
        self.assertEqual(mod.liste()['eintraege'], [])

    def test_top_id_baum(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'TOP_ID'],
            [
                {'ID': 1, 'NAME': 'Hardware',  'TOP_ID': -1},
                {'ID': 2, 'NAME': 'Mainboard', 'TOP_ID': 1},
                {'ID': 3, 'NAME': 'CPU',       'TOP_ID': 1},
                {'ID': 4, 'NAME': 'AMD',       'TOP_ID': 3},
                {'ID': 5, 'NAME': 'Root-Null', 'TOP_ID': 0},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertIsNone(by_id[1]['parent_id'])
        self.assertIsNone(by_id[5]['parent_id'])  # 0 == Wurzel
        self.assertEqual(by_id[2]['parent_id'], 1)
        self.assertEqual(by_id[3]['parent_id'], 1)
        self.assertEqual(by_id[4]['parent_id'], 3)
        self.assertEqual(by_id[1]['kinder'], 2)   # Mainboard + CPU
        self.assertEqual(by_id[3]['kinder'], 1)   # AMD
        self.assertEqual(by_id[4]['kinder'], 0)

    def test_durchsuchen_y_n(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'DURCHSUCHEN'],
            [
                {'ID': 1, 'NAME': 'a', 'DURCHSUCHEN': 'Y'},
                {'ID': 2, 'NAME': 'b', 'DURCHSUCHEN': 'N'},
                {'ID': 3, 'NAME': 'c', 'DURCHSUCHEN': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertTrue(by_id[1]['durchsuchen'])
        self.assertFalse(by_id[2]['durchsuchen'])
        self.assertFalse(by_id[3]['durchsuchen'])

    def test_kalk_faktoren_liste(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'VK1_FAKTOR', 'VK2_FAKTOR', 'VK3_FAKTOR',
             'VK4_FAKTOR', 'VK5_FAKTOR'],
            [
                {'ID': 1, 'NAME': 'mitKalk',
                 'VK1_FAKTOR': 1.5, 'VK2_FAKTOR': 1.8, 'VK3_FAKTOR': 2.0,
                 'VK4_FAKTOR': 2.2, 'VK5_FAKTOR': 2.5},
                {'ID': 2, 'NAME': 'ohneKalk',
                 'VK1_FAKTOR': 0, 'VK2_FAKTOR': 0, 'VK3_FAKTOR': 0,
                 'VK4_FAKTOR': 0, 'VK5_FAKTOR': 0},
                {'ID': 3, 'NAME': 'null',
                 'VK1_FAKTOR': None, 'VK2_FAKTOR': None, 'VK3_FAKTOR': None,
                 'VK4_FAKTOR': None, 'VK5_FAKTOR': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['kalk'], [1.5, 1.8, 2.0, 2.2, 2.5])
        self.assertTrue(by_id[1]['hat_kalk'])
        self.assertFalse(by_id[2]['hat_kalk'])
        self.assertEqual(by_id[3]['kalk'], [None, None, None, None, None])
        self.assertFalse(by_id[3]['hat_kalk'])

    def test_def_ekto_akto(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'DEF_EKTO', 'DEF_AKTO'],
            [
                {'ID': 1, 'NAME': 'a', 'DEF_EKTO': 3400, 'DEF_AKTO': 8400},
                {'ID': 2, 'NAME': 'b', 'DEF_EKTO': -1,   'DEF_AKTO': 0},
                {'ID': 3, 'NAME': 'c', 'DEF_EKTO': None, 'DEF_AKTO': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['def_ekto'], 3400)
        self.assertEqual(by_id[1]['def_akto'], 8400)
        # -1 und 0 zaehlen als 'nicht gesetzt'
        self.assertIsNone(by_id[2]['def_ekto'])
        self.assertIsNone(by_id[2]['def_akto'])
        self.assertIsNone(by_id[3]['def_ekto'])
        self.assertIsNone(by_id[3]['def_akto'])

    def test_steuer_code_label(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'STEUER_CODE'],
            [
                {'ID': 1, 'NAME': 'frei', 'STEUER_CODE': 0},
                {'ID': 2, 'NAME': 'voll', 'STEUER_CODE': 1},
                {'ID': 3, 'NAME': 'erm',  'STEUER_CODE': 2},
                {'ID': 4, 'NAME': 'rsv',  'STEUER_CODE': 3},
                {'ID': 5, 'NAME': 'unk',  'STEUER_CODE': 7},
                {'ID': 6, 'NAME': 'null', 'STEUER_CODE': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['steuer_label'], 'ohne MwSt')
        self.assertEqual(by_id[2]['steuer_label'], 'voll (19%)')
        self.assertEqual(by_id[3]['steuer_label'], 'erm. (7%)')
        self.assertEqual(by_id[4]['steuer_label'], 'Reserve')
        self.assertEqual(by_id[5]['steuer_label'], '')  # unbekannt
        self.assertIsNone(by_id[6]['steuer_code'])
        self.assertEqual(by_id[6]['steuer_label'], '')

    def test_beschreibung_bytes(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'BESCHREIBUNG'],
            [
                {'ID': 1, 'NAME': 'a',
                 'BESCHREIBUNG': 'Normaltext'},
                {'ID': 2, 'NAME': 'b',
                 'BESCHREIBUNG': 'Als Blob'.encode('utf-8')},
                {'ID': 3, 'NAME': 'c', 'BESCHREIBUNG': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['beschreibung'], 'Normaltext')
        self.assertEqual(by_id[2]['beschreibung'], 'Als Blob')
        self.assertEqual(by_id[3]['beschreibung'], '')

    def test_wgr_rabatt_float(self):
        mod = _lade_modul(_FakeCursor(
            ['ID', 'NAME', 'WGR_RABATT'],
            [
                {'ID': 1, 'NAME': 'a', 'WGR_RABATT': 5.0},
                {'ID': 2, 'NAME': 'b', 'WGR_RABATT': 0},
                {'ID': 3, 'NAME': 'c', 'WGR_RABATT': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['wgr_rabatt'], 5.0)
        self.assertEqual(by_id[2]['wgr_rabatt'], 0.0)
        self.assertIsNone(by_id[3]['wgr_rabatt'])


if __name__ == '__main__':
    unittest.main()
