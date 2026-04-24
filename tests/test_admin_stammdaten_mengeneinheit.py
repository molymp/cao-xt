"""
Unit-Tests fuer admin-app/app/stammdaten_mengeneinheit.py.

Wir stubben ``db.get_db`` mit einem Fake-Cursor, der vorgegebene
Datensaetze liefert. Das deckt die reine Aufbereitungs-Logik ab
(EN16931-Klartext, Sortierung, leere Codes) ohne echte DB.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_mengeneinheit.py')


class _FakeCursor:
    """Minimaler Cursor: speichert den letzten execute-Aufruf und
    gibt die per ``_rows`` hinterlegte Liste zurueck."""

    def __init__(self, rows):
        self._rows = rows
        self.letzte_sql = None

    def execute(self, sql, *args, **kwargs):
        self.letzte_sql = sql

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _lade_modul(cursor):
    fake_db = types.ModuleType('db')
    fake_db.get_db = lambda: cursor  # context-manager-faehig (siehe __enter__)
    sys.modules['db'] = fake_db
    spec = importlib.util.spec_from_file_location('sme_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor([]))
        self.assertEqual(mod.liste(), [])

    def test_bekannter_code_bekommt_klartext(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 1, 'BEZEICHNUNG': 'Stueck', 'ME_CODE': 'H87'},
        ]))
        res = mod.liste()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['me_code'], 'H87')
        self.assertEqual(res[0]['me_code_label'], 'H87 (Stueck)')

    def test_unbekannter_code_bleibt_pur(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 42, 'BEZEICHNUNG': 'Spezial', 'ME_CODE': 'XYZ'},
        ]))
        res = mod.liste()
        self.assertEqual(res[0]['me_code'], 'XYZ')
        self.assertEqual(res[0]['me_code_label'], 'XYZ')

    def test_leerer_code_wird_als_leer_markiert(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 16, 'BEZEICHNUNG': 'AE', 'ME_CODE': None},
            {'REC_ID': 30, 'BEZEICHNUNG': 'Blatt', 'ME_CODE': '  '},
        ]))
        res = mod.liste()
        self.assertEqual(res[0]['me_code'], '')
        self.assertEqual(res[0]['me_code_label'], '')
        self.assertEqual(res[1]['me_code'], '')

    def test_bezeichnung_wird_getrimmt(self):
        mod = _lade_modul(_FakeCursor([
            {'REC_ID': 7, 'BEZEICHNUNG': ' Kg  ', 'ME_CODE': 'KGM'},
        ]))
        res = mod.liste()
        self.assertEqual(res[0]['bezeichnung'], 'Kg')
        self.assertEqual(res[0]['me_code_label'], 'KGM (Kilogramm)')


if __name__ == '__main__':
    unittest.main()
