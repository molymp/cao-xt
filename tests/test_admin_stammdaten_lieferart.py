"""
Unit-Tests fuer admin-app/app/stammdaten_lieferart.py.

DB wird gestubbt; geprueft werden Trimmen, leeres/ungepflegtes TEXT,
BLOB-Decodierung und has_text-Flag.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_lieferart.py')


class _FakeCursor:

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, *args, **kwargs):
        pass

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade_modul(cursor):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: cursor
    sys.modules['db'] = fake_db
    spec = importlib.util.spec_from_file_location('sla_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor([]))
        self.assertEqual(mod.liste(), [])

    def test_name_und_text(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 1, 'NAME': 'Selbstabholung', 'TEXT': 'Bitte abholen.'},
        ]))
        res = mod.liste()
        self.assertEqual(res[0]['id'], 1)
        self.assertEqual(res[0]['name'], 'Selbstabholung')
        self.assertEqual(res[0]['text'], 'Bitte abholen.')
        self.assertTrue(res[0]['has_text'])

    def test_leerer_text_hat_has_text_false(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 2, 'NAME': 'DHL', 'TEXT': None},
            {'REC_ID': 3, 'NAME': 'UPS', 'TEXT': '   '},
            {'REC_ID': 4, 'NAME': 'Spedition', 'TEXT': ''},
        ]))
        res = mod.liste()
        for e in res:
            self.assertEqual(e['text'], '')
            self.assertFalse(e['has_text'])

    def test_blob_text_wird_decodiert(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 5, 'NAME': 'Versand',
             'TEXT': 'Versand mit DHL – Lieferzeit 1–2 Tage.'.encode('utf-8')},
        ]))
        res = mod.liste()
        self.assertIn('Lieferzeit', res[0]['text'])
        self.assertTrue(res[0]['has_text'])

    def test_name_wird_getrimmt(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 6, 'NAME': '  Abholung  ', 'TEXT': '  rand  '},
        ]))
        res = mod.liste()
        self.assertEqual(res[0]['name'], 'Abholung')
        self.assertEqual(res[0]['text'], 'rand')


if __name__ == '__main__':
    unittest.main()
