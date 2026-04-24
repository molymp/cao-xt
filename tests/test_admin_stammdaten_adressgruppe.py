"""
Unit-Tests fuer admin-app/app/stammdaten_adressgruppe.py.

Tests decken ab:
- Schema ohne Parent-Spalte (flache Liste)
- Schema mit TOP_ID und mit alternativer PARENT_ID
- Parent-Werte 0 und -1 werden als 'keine Parent' behandelt
- Kinder-Zaehlung stimmt
- Y/N-Flag fuer DURCHSUCHEN
- SQL_TEXT-Dekodierung (Bytes) und hat_sql-Flag
- GLOBALRABATT als float
- VORGABEN-INI-Parsing fuer erechnung_typ
"""
import importlib.util
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_MODUL_PATH = os.path.join(
    _REPO_ROOT, 'admin-app', 'app', 'stammdaten_adressgruppe.py')


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
    sys.modules.pop('sag_test', None)
    spec = importlib.util.spec_from_file_location('sag_test', _MODUL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestListe(unittest.TestCase):

    def test_leere_tabelle(self):
        mod = _lade_modul(_FakeCursor(['REC_ID', 'NAME'], []))
        res = mod.liste()
        self.assertIsNone(res['parent_spalte'])
        self.assertEqual(res['eintraege'], [])

    def test_ohne_parent_spalte_flache_liste(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'DURCHSUCHEN'],
            [
                {'REC_ID': 1, 'NAME': 'Kunden', 'DURCHSUCHEN': 'Y'},
                {'REC_ID': 2, 'NAME': 'Lieferanten', 'DURCHSUCHEN': 'Y'},
            ],
        ))
        res = mod.liste()
        self.assertIsNone(res['parent_spalte'])
        self.assertEqual(len(res['eintraege']), 2)
        for e in res['eintraege']:
            self.assertIsNone(e['parent_id'])
            self.assertEqual(e['kinder'], 0)
            self.assertTrue(e['durchsuchen'])

    def test_mit_top_id_baum(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TOP_ID', 'DURCHSUCHEN'],
            [
                {'REC_ID': 1, 'NAME': 'Kunden',       'TOP_ID': 0,
                 'DURCHSUCHEN': 'Y'},
                {'REC_ID': 2, 'NAME': 'Gastro',       'TOP_ID': 1,
                 'DURCHSUCHEN': 'Y'},
                {'REC_ID': 3, 'NAME': 'Endkunden',    'TOP_ID': 1,
                 'DURCHSUCHEN': 'Y'},
                {'REC_ID': 4, 'NAME': 'Restaurants',  'TOP_ID': 2,
                 'DURCHSUCHEN': 'Y'},
            ],
        ))
        res = mod.liste()
        self.assertEqual(res['parent_spalte'], 'TOP_ID')

        by_id = {e['id']: e for e in res['eintraege']}
        # Kunden ist Wurzel (TOP_ID=0 → None)
        self.assertIsNone(by_id[1]['parent_id'])
        self.assertEqual(by_id[1]['kinder'], 2)  # Gastro + Endkunden
        # Gastro hat Parent=1 und 1 Kind (Restaurants)
        self.assertEqual(by_id[2]['parent_id'], 1)
        self.assertEqual(by_id[2]['kinder'], 1)
        # Restaurants ist Blatt
        self.assertEqual(by_id[4]['parent_id'], 2)
        self.assertEqual(by_id[4]['kinder'], 0)

    def test_alternative_parent_spalte_parent_id(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'PARENT_ID'],
            [
                {'REC_ID': 10, 'NAME': 'Oben', 'PARENT_ID': None},
                {'REC_ID': 11, 'NAME': 'Unten', 'PARENT_ID': 10},
            ],
        ))
        res = mod.liste()
        self.assertEqual(res['parent_spalte'], 'PARENT_ID')
        by_id = {e['id']: e for e in res['eintraege']}
        self.assertIsNone(by_id[10]['parent_id'])
        self.assertEqual(by_id[11]['parent_id'], 10)

    def test_parent_minus_eins_ist_wurzel(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'TOP_ID'],
            [
                {'REC_ID': 1, 'NAME': 'Root-A', 'TOP_ID': -1},
                {'REC_ID': 2, 'NAME': 'Root-B', 'TOP_ID': 0},
            ],
        ))
        res = mod.liste()
        for e in res['eintraege']:
            self.assertIsNone(e['parent_id'])

    def test_durchsuchen_y_n(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'DURCHSUCHEN'],
            [
                {'REC_ID': 1, 'NAME': 'a', 'DURCHSUCHEN': 'Y'},
                {'REC_ID': 2, 'NAME': 'b', 'DURCHSUCHEN': 'N'},
                {'REC_ID': 3, 'NAME': 'c', 'DURCHSUCHEN': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertTrue(by_id[1]['durchsuchen'])
        self.assertFalse(by_id[2]['durchsuchen'])
        self.assertFalse(by_id[3]['durchsuchen'])

    def test_sql_text_flag_und_bytes(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'SQL_TEXT'],
            [
                {'REC_ID': 1, 'NAME': 'Dynamisch',
                 'SQL_TEXT': 'ORT = "Berlin"'},
                {'REC_ID': 2, 'NAME': 'Statisch',
                 'SQL_TEXT': ''},
                {'REC_ID': 3, 'NAME': 'Blob',
                 'SQL_TEXT': 'PLZ LIKE "1%"'.encode('utf-8')},
                {'REC_ID': 4, 'NAME': 'None', 'SQL_TEXT': None},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertTrue(by_id[1]['hat_sql'])
        self.assertFalse(by_id[2]['hat_sql'])
        self.assertTrue(by_id[3]['hat_sql'])
        self.assertFalse(by_id[4]['hat_sql'])

    def test_globalrabatt_wird_float(self):
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'GLOBALRABATT'],
            [
                {'REC_ID': 1, 'NAME': 'a', 'GLOBALRABATT': 2.5},
                {'REC_ID': 2, 'NAME': 'b', 'GLOBALRABATT': None},
                {'REC_ID': 3, 'NAME': 'c', 'GLOBALRABATT': 0},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['globalrabatt'], 2.5)
        self.assertIsNone(by_id[2]['globalrabatt'])
        self.assertEqual(by_id[3]['globalrabatt'], 0.0)

    def test_vorgaben_erechnung_typ(self):
        vorgaben_xr = 'erechnung_typ=xrechnung\nweitere_option=42\n'
        vorgaben_zf = '[section]\nERECHNUNG_TYP = ZUGFeRD\n'
        vorgaben_deakt = 'erechnung_typ=deaktiviert'
        vorgaben_leer = ''
        vorgaben_muell = 'erechnung_typ=foo\n'
        mod = _lade_modul(_FakeCursor(
            ['REC_ID', 'NAME', 'VORGABEN'],
            [
                {'REC_ID': 1, 'NAME': 'XR',    'VORGABEN': vorgaben_xr},
                {'REC_ID': 2, 'NAME': 'ZF',    'VORGABEN': vorgaben_zf},
                {'REC_ID': 3, 'NAME': 'Deakt', 'VORGABEN': vorgaben_deakt},
                {'REC_ID': 4, 'NAME': 'Leer',  'VORGABEN': vorgaben_leer},
                {'REC_ID': 5, 'NAME': 'Muell', 'VORGABEN': vorgaben_muell},
                {'REC_ID': 6, 'NAME': 'Null',  'VORGABEN': None},
                # BLOB-Variante
                {'REC_ID': 7, 'NAME': 'Blob',
                 'VORGABEN': b'erechnung_typ=xrechnung'},
            ],
        ))
        by_id = {e['id']: e for e in mod.liste()['eintraege']}
        self.assertEqual(by_id[1]['erechnung_typ'], 'xrechnung')
        self.assertEqual(by_id[2]['erechnung_typ'], 'zugferd')
        self.assertEqual(by_id[3]['erechnung_typ'], 'deaktiviert')
        self.assertIsNone(by_id[4]['erechnung_typ'])
        self.assertIsNone(by_id[5]['erechnung_typ'])  # unbekannter Wert
        self.assertIsNone(by_id[6]['erechnung_typ'])
        self.assertEqual(by_id[7]['erechnung_typ'], 'xrechnung')


if __name__ == '__main__':
    unittest.main()
