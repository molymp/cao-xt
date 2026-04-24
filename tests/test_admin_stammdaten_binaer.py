"""
Unit-Tests fuer admin-app/app/stammdaten_binaer.py.
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_binaer.py')


class _FakeCursor:

    def __init__(self, schemas, kategorien, stats,
                 erwartet_bytegroesse=True):
        self._schemas = schemas
        self._kategorien = kategorien
        self._stats = stats
        self._erwartet = erwartet_bytegroesse
        self._naechste = None
        self.letzter_sql = None

    def execute(self, sql, *args, **kwargs):
        self.letzter_sql = sql
        u = sql.upper()
        if 'INFORMATION_SCHEMA' in u:
            tab = args[0][0] if args else ''
            self._naechste = [
                {'COLUMN_NAME': s}
                for s in self._schemas.get(tab.upper(), [])
            ]
        elif 'FROM BINAER_KATEGORIE' in u:
            self._naechste = self._kategorien
        elif 'FROM BINAERDATEN' in u and 'GROUP BY' in u:
            self._naechste = self._stats
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
    sys.modules.pop('bin_test', None)
    spec = importlib.util.spec_from_file_location('bin_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_KAT_COLS = ['REC_ID', 'NAME', 'JSONDATEN']
_BD_COLS = ['REC_ID', 'BINAER_TYP', 'BYTEGROESSE', 'DATEN']


class TestListe(unittest.TestCase):

    def test_keine_tabellen(self):
        mod = _lade_modul(_FakeCursor(
            schemas={}, kategorien=[], stats=[]))
        res = mod.liste()
        self.assertEqual(res['kategorien'], [])
        self.assertEqual(res['total_anzahl'], 0)
        self.assertEqual(res['total_bytes'], 0)

    def test_kategorien_mit_stats(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'BINAER_KATEGORIE': _KAT_COLS,
                'BINAERDATEN': _BD_COLS,
            },
            kategorien=[
                {'REC_ID': 1, 'NAME': 'Datenblatt', 'JSONDATEN': '{}'},
                {'REC_ID': 2, 'NAME': 'Foto', 'JSONDATEN': ''},
                {'REC_ID': 3, 'NAME': 'Leer', 'JSONDATEN': None},
            ],
            stats=[
                {'BINAER_TYP': 1, 'ANZ': 17,
                 'SUM_B': 3200000, 'MAX_B': 2000000},
                {'BINAER_TYP': 2, 'ANZ': 80,
                 'SUM_B': 7200000, 'MAX_B': 800000},
            ],
        ))
        res = mod.liste()
        by_id = {k['id']: k for k in res['kategorien']}
        self.assertEqual(by_id[1]['name'], 'Datenblatt')
        self.assertEqual(by_id[1]['anzahl'], 17)
        self.assertEqual(by_id[1]['gesamt_bytes'], 3200000)
        self.assertEqual(by_id[1]['groesste_byte'], 2000000)
        self.assertEqual(by_id[2]['anzahl'], 80)
        # Leere Kategorie (keine Dateien)
        self.assertEqual(by_id[3]['anzahl'], 0)
        self.assertEqual(res['total_anzahl'], 17 + 80)
        self.assertEqual(res['total_bytes'], 3200000 + 7200000)

    def test_verwaiste_dateien_in_sammelkategorie(self):
        mod = _lade_modul(_FakeCursor(
            schemas={
                'BINAER_KATEGORIE': _KAT_COLS,
                'BINAERDATEN': _BD_COLS,
            },
            kategorien=[
                {'REC_ID': 1, 'NAME': 'Bekannt', 'JSONDATEN': ''},
            ],
            stats=[
                {'BINAER_TYP': 1, 'ANZ': 5, 'SUM_B': 500, 'MAX_B': 100},
                {'BINAER_TYP': 99, 'ANZ': 3, 'SUM_B': 300, 'MAX_B': 150},
                {'BINAER_TYP': None, 'ANZ': 2, 'SUM_B': 200, 'MAX_B': 120},
            ],
        ))
        res = mod.liste()
        by_id = {k['id']: k for k in res['kategorien']}
        self.assertEqual(by_id[1]['anzahl'], 5)
        self.assertIn(None, by_id)
        self.assertEqual(by_id[None]['name'], '(ohne / unbekannt)')
        self.assertEqual(by_id[None]['anzahl'], 3 + 2)
        self.assertEqual(by_id[None]['gesamt_bytes'], 300 + 200)
        self.assertEqual(by_id[None]['groesste_byte'], 150)

    def test_bytegroesse_spalte_wird_bevorzugt(self):
        """Wenn BYTEGROESSE existiert, wird kein OCTET_LENGTH genutzt."""
        cur = _FakeCursor(
            schemas={
                'BINAER_KATEGORIE': _KAT_COLS,
                'BINAERDATEN': ['REC_ID', 'BINAER_TYP', 'BYTEGROESSE',
                                'DATEN'],
            },
            kategorien=[],
            stats=[],
        )
        mod = _lade_modul(cur)
        mod.liste()
        self.assertIn('SUM(BYTEGROESSE)', cur.letzter_sql)
        self.assertNotIn('OCTET_LENGTH', cur.letzter_sql)

    def test_octet_length_fallback(self):
        """Alte DB ohne BYTEGROESSE-Spalte -> OCTET_LENGTH(DATEN)."""
        cur = _FakeCursor(
            schemas={
                'BINAER_KATEGORIE': _KAT_COLS,
                'BINAERDATEN': ['REC_ID', 'BINAER_TYP', 'DATEN'],
            },
            kategorien=[],
            stats=[],
        )
        mod = _lade_modul(cur)
        mod.liste()
        self.assertIn('OCTET_LENGTH(DATEN)', cur.letzter_sql)

    def test_jsondaten_gekuerzt(self):
        lang = 'x' * 1000
        mod = _lade_modul(_FakeCursor(
            schemas={'BINAER_KATEGORIE': _KAT_COLS,
                     'BINAERDATEN': _BD_COLS},
            kategorien=[
                {'REC_ID': 1, 'NAME': 'Lang', 'JSONDATEN': lang},
            ],
            stats=[],
        ))
        res = mod.liste()
        self.assertTrue(res['kategorien'][0]['jsondaten'].endswith(' …'))
        self.assertLess(len(res['kategorien'][0]['jsondaten']), 520)


if __name__ == '__main__':
    unittest.main()
