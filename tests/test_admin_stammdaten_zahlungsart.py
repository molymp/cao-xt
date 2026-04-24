"""
Unit-Tests fuer admin-app/app/stammdaten_zahlungsart.py.

Wir stubben ``db.get_db`` mit einem Fake-Cursor und pruefen die
Aufbereitung: Y/N -> Bool, FIBU_KONTEN-Split, leere Werte, Zahlen-Casts.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_zahlungsart.py')


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
    spec = importlib.util.spec_from_file_location('sza_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor([]))
        self.assertEqual(mod.liste(), [])

    def test_y_flag_wird_true(self):
        mod = _lade_modul(_FakeCursor([{
            'REC_ID': 1, 'NAME': 'Bar', 'TEXT_KURZ': '', 'TEXT_LANG': '',
            'FIBU_KONTEN': '', 'SKONTO_PROZ': 0, 'AKTIV_FLAG': 'Y',
            'NETTO_TAGE': 0, 'SKONTO_TAGE': 0, 'AUTOZAHL_FLAG': 'Y',
        }]))
        res = mod.liste()
        self.assertTrue(res[0]['aktiv'])
        self.assertTrue(res[0]['autozahl'])

    def test_n_und_leer_werden_false(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 2, 'NAME': 'x', 'TEXT_KURZ': '', 'TEXT_LANG': '',
             'FIBU_KONTEN': '', 'SKONTO_PROZ': 0, 'AKTIV_FLAG': 'N',
             'NETTO_TAGE': 0, 'SKONTO_TAGE': 0, 'AUTOZAHL_FLAG': None},
        ]))
        res = mod.liste()
        self.assertFalse(res[0]['aktiv'])
        self.assertFalse(res[0]['autozahl'])

    def test_fibu_konten_split(self):
        mod = _lade_modul(_FakeCursor([{
            'REC_ID': 3, 'NAME': 'Rg', 'TEXT_KURZ': 'k', 'TEXT_LANG': 'l',
            'FIBU_KONTEN': '1200, 1210,  , 1400', 'SKONTO_PROZ': 2.5,
            'AKTIV_FLAG': 'Y', 'NETTO_TAGE': 14, 'SKONTO_TAGE': 7,
            'AUTOZAHL_FLAG': 'N',
        }]))
        res = mod.liste()
        self.assertEqual(res[0]['fibu_konten'], ['1200', '1210', '1400'])
        self.assertEqual(res[0]['skonto_proz'], 2.5)
        self.assertEqual(res[0]['netto_tage'], 14)
        self.assertEqual(res[0]['skonto_tage'], 7)

    def test_leere_fibu_konten(self):
        mod = _lade_modul(_FakeCursor([{
            'REC_ID': 4, 'NAME': 'x', 'TEXT_KURZ': '', 'TEXT_LANG': '',
            'FIBU_KONTEN': None, 'SKONTO_PROZ': None, 'AKTIV_FLAG': '',
            'NETTO_TAGE': None, 'SKONTO_TAGE': None, 'AUTOZAHL_FLAG': '',
        }]))
        res = mod.liste()
        self.assertEqual(res[0]['fibu_konten'], [])
        self.assertEqual(res[0]['skonto_proz'], 0.0)
        self.assertEqual(res[0]['netto_tage'], 0)
        self.assertEqual(res[0]['skonto_tage'], 0)

    def test_name_und_text_werden_getrimmt(self):
        mod = _lade_modul(_FakeCursor([{
            'REC_ID': 5, 'NAME': '  Rechnung 14 Tage  ',
            'TEXT_KURZ': ' Zahlbar ', 'TEXT_LANG': '',
            'FIBU_KONTEN': '', 'SKONTO_PROZ': 0, 'AKTIV_FLAG': 'Y',
            'NETTO_TAGE': 14, 'SKONTO_TAGE': 0, 'AUTOZAHL_FLAG': 'N',
        }]))
        res = mod.liste()
        self.assertEqual(res[0]['name'], 'Rechnung 14 Tage')
        self.assertEqual(res[0]['text_kurz'], 'Zahlbar')


if __name__ == '__main__':
    unittest.main()
