"""
Unit-Tests fuer admin-app/app/stammdaten_export.py.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_export.py')


class _FakeCursor:

    def __init__(self, schemas, daten):
        self._schemas = schemas
        self._daten = daten
        self._naechste = None

    def execute(self, sql, *args, **kwargs):
        u = sql.upper()
        if 'INFORMATION_SCHEMA' in u:
            tab = args[0][0] if args else ''
            self._naechste = [
                {'COLUMN_NAME': s}
                for s in self._schemas.get(tab.upper(), [])
            ]
        elif 'FROM EXPORT_KATEGORIEN' in u:
            self._naechste = self._daten.get('EXPORT_KATEGORIEN', [])
        elif 'FROM EXPORT' in u:
            self._naechste = self._daten.get('EXPORT', [])
        else:
            self._naechste = []

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
    sys.modules.pop('exp_test', None)
    spec = importlib.util.spec_from_file_location('exp_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_EXPORT_COLS = [
    'ID', 'KURZBEZ', 'INFO', 'QUERY', 'FELDER', 'FORMAT', 'FILENAME',
    'LAST_CHANGE', 'CHANGE_NAME', 'STATISTIK_FLAG', 'SUBKATEGORIE',
    'KATEGORIE_ID', 'MA_ID', 'FORMULAR',
]


class TestListe(unittest.TestCase):

    def test_keine_export_tabelle(self):
        mod = _lade_modul(_FakeCursor(schemas={}, daten={}))
        res = mod.liste()
        self.assertEqual(res['kategorien'], [])
        self.assertEqual(res['eintraege'], [])

    def test_kategorien_mit_anzahl(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'EXPORT': _EXPORT_COLS,
                'EXPORT_KATEGORIEN': ['REC_ID', 'KURZNAME', 'BESCHREIBUNG'],
            },
            daten={
                'EXPORT_KATEGORIEN': [
                    {'REC_ID': 1, 'KURZNAME': 'Rechnungen',
                     'BESCHREIBUNG': 'Alle Rechnungs-Reports'},
                    {'REC_ID': 2, 'KURZNAME': 'DATEV',
                     'BESCHREIBUNG': 'DATEV-Export'},
                ],
                'EXPORT': [
                    {'ID': 10, 'KURZBEZ': 'Offene Posten',
                     'KATEGORIE_ID': 1, 'FORMAT': 'XLS',
                     'STATISTIK_FLAG': 0, 'FORMULAR_LEN': 0},
                    {'ID': 11, 'KURZBEZ': 'Zahlungslauf',
                     'KATEGORIE_ID': 1, 'FORMAT': 'PDF',
                     'STATISTIK_FLAG': 1, 'FORMULAR_LEN': 32768},
                    {'ID': 12, 'KURZBEZ': 'DATEV Export',
                     'KATEGORIE_ID': 2, 'FORMAT': 'CSV',
                     'STATISTIK_FLAG': 0, 'FORMULAR_LEN': 0},
                ],
            },
        ))
        res = mod.liste()
        self.assertEqual(len(res['kategorien']), 2)
        by_id = {k['id']: k for k in res['kategorien']}
        self.assertEqual(by_id[1]['name'], 'Rechnungen')
        self.assertEqual(by_id[1]['anzahl'], 2)
        self.assertEqual(by_id[2]['anzahl'], 1)
        self.assertEqual(len(res['eintraege']), 3)

    def test_verwaister_eintrag_bekommt_virtuelle_kategorie(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'EXPORT': _EXPORT_COLS,
                'EXPORT_KATEGORIEN': ['REC_ID', 'KURZNAME', 'BESCHREIBUNG'],
            },
            daten={
                'EXPORT_KATEGORIEN': [
                    {'REC_ID': 1, 'KURZNAME': 'R', 'BESCHREIBUNG': ''},
                ],
                'EXPORT': [
                    {'ID': 10, 'KURZBEZ': 'A', 'KATEGORIE_ID': 1,
                     'FORMULAR_LEN': 0},
                    {'ID': 11, 'KURZBEZ': 'B', 'KATEGORIE_ID': 99,
                     'FORMULAR_LEN': 0},
                    {'ID': 12, 'KURZBEZ': 'C', 'KATEGORIE_ID': None,
                     'FORMULAR_LEN': 0},
                ],
            },
        ))
        res = mod.liste()
        by_id = {k['id']: k for k in res['kategorien']}
        self.assertEqual(by_id[1]['anzahl'], 1)
        # Virtuelle Kategorie sammelt 11 und 12 ein (unbekannte/fehlende ID)
        self.assertIn(None, by_id)
        self.assertEqual(by_id[None]['name'], '(ohne / unbekannt)')
        self.assertEqual(by_id[None]['anzahl'], 2)

    def test_query_kurz_und_formular_bytes(self):
        langer_sql = 'SELECT * FROM KUNDEN WHERE ' + 'x' * 500
        mod = _lade_modul(_FakeCursor(
            schemas={'EXPORT': _EXPORT_COLS,
                     'EXPORT_KATEGORIEN': ['REC_ID']},
            daten={
                'EXPORT_KATEGORIEN': [],
                'EXPORT': [
                    {'ID': 1, 'KURZBEZ': 'Kunden',
                     'QUERY': langer_sql,
                     'FORMULAR_LEN': 123456},
                ],
            },
        ))
        res = mod.liste()
        e = res['eintraege'][0]
        self.assertTrue(e['query_kurz'].endswith(' …'))
        self.assertLess(len(e['query_kurz']), len(langer_sql))
        self.assertTrue(e['hat_formular'])
        self.assertEqual(e['formular_bytes'], 123456)

    def test_statistik_flag_und_query_bytes(self):
        mod = _lade_modul(_FakeCursor(
            schemas={'EXPORT': _EXPORT_COLS,
                     'EXPORT_KATEGORIEN': ['REC_ID']},
            daten={
                'EXPORT_KATEGORIEN': [],
                'EXPORT': [
                    {'ID': 1, 'KURZBEZ': 'Stat', 'STATISTIK_FLAG': 1,
                     'QUERY': 'Bytes-Query'.encode('utf-8'),
                     'FORMULAR_LEN': 0},
                    {'ID': 2, 'KURZBEZ': 'NonStat', 'STATISTIK_FLAG': 0,
                     'FORMULAR_LEN': 0},
                ],
            },
        ))
        res = mod.liste()
        by_id = {e['id']: e for e in res['eintraege']}
        self.assertTrue(by_id[1]['statistik'])
        self.assertFalse(by_id[2]['statistik'])
        # Bytes-Memo wurde dekodiert
        self.assertEqual(by_id[1]['query_kurz'], 'Bytes-Query')


if __name__ == '__main__':
    unittest.main()
